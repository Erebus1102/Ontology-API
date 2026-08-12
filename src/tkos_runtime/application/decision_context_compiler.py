# src/tkos_runtime/application/decision_context_compiler.py
"""Decision Context Compiler: turns a structured ContextPack into a
decision-oriented reading view (decision_context + sectioned Markdown units).

Grounding boundary (binding): this compiler ONLY produces (A)-type structured
narrative — regrouping known facts by role/section, humanizing names. It NEVER
produces (B)-type conditional judgements ("尚不足以承诺", "最可能失败在哪里").
epistemic_summary only reports computable status distribution.
"""
from __future__ import annotations
import dataclasses
import re
from typing import Any

from tkos_runtime.domain.models import ContextPack
from tkos_runtime.domain.render_units import (
    DECISION_INCIDENT_PREDICATES, RenderOmission, RenderBudgetTooSmall,
    SECTION_ORDER, SECTION_TITLES, ROLE_TO_SECTION, RenderedFactUnit,
)

TKOS = "https://ontology.tokenking.ai/tkos#"

# role -> tuple of class fragments (full IRI = TKOS + fragment); priority required>secondary>trace_only
ROLE_TABLE: list[tuple[str, tuple[str, ...]]] = [
    ("issue", ("StrategicIssue",)),
    ("outcome", ("Outcome","CompanyOutcome","DomainOutcome","MissionOutcome","OutcomeContribution")),
    ("progress", ("ProgressSnapshot","DomainProgressSnapshot","OutcomeProgressSnapshot","PerformanceFact")),
    ("risk", ("Risk","HighRisk")),
    ("dependency", ("Dependency",)),
    ("evidence", ("Evidence","EvidenceSupport","EvidenceChallenge","AttributedAssertion")),
    ("context_gap", ("ContextGap",)),
    ("decision", ("Decision","StrategicDecision","OperatingDecision","DecisionRecord","StrategicChoice","Judgement","StrategicResearch","StrategicSignal")),
    ("mission", ("Mission","MissionScope","MissionRationale","MissionPortfolio")),
    ("criterion", ("SuccessCriterion",)),
    ("milestone", ("Milestone",)),
    ("capability", ("CompanyCapability","KeyPath")),
    ("rationale", ("LeadershipInsight","Lesson","ReviewConclusion")),
    ("responsibility", ("RoleAssignment","DirectlyResponsibleRole","DirectlyResponsibleIndividual")),
    ("source_record", ("SourceRecord",)),
    ("confirmation", ("Confirmation","ConfirmationEvent","RevisionEvent")),
]
_ROLE_FRAG = {role: {TKOS+f for f in frags} for role, frags in ROLE_TABLE}
_TIER = {"issue":1,"outcome":1,"progress":1,"risk":1,"dependency":1,"evidence":1,
         "context_gap":1,"decision":1,
         "mission":2,"criterion":2,"milestone":2,"capability":2,"rationale":2,"responsibility":2,
         "source_record":3,"confirmation":3}

PARTITION_PRIORITY = {"graph-confirmed-enterprise":0,"graph-candidate-and-dispute":1,
                      "graph-decision-provenance":2,"graph-derived-context":3}

def _all_members(pack: ContextPack):
    """Iterate all members, deduplicated by (member_id, partition).

    A ContextGap-typed member appears in both candidate_context and
    context_gaps; dedup ensures each view_key is compiled exactly once.
    """
    seen: set[tuple[str, str]] = set()
    for bucket in (pack.current_facts, pack.candidate_context,
                   pack.provenance_context, pack.context_gaps,
                   pack.derived_claims):
        for m in bucket:
            vk = (m.id, m.partition)
            if vk not in seen:
                seen.add(vk)
                yield m

def build_type_index(pack: ContextPack) -> dict[str, set[str]]:
    idx: dict[str, set[str]] = {}
    for m in _all_members(pack):
        idx.setdefault(m.id, set()).update(m.rdf_types)
    return idx

# test-facing helper
def build_type_index_from_members(members) -> dict[str, set[str]]:
    idx: dict[str, set[str]] = {}
    for m in members:
        idx.setdefault(m.id, set()).update(m.rdf_types)
    return idx

def classify_role(member_id: str, type_index: dict[str, set[str]]) -> str:
    types = type_index.get(member_id, set())
    for role, frags in ROLE_TABLE:
        if types & _ROLE_FRAG[role]:
            return role
    return "other"

def role_tier(role: str) -> int:
    return _TIER.get(role, 9)

def _real_display_name(member) -> str | None:
    # display_name is real only if it differs from the id fragment
    if member.display_name and member.display_name != member.id:
        return member.display_name
    return None

def _candidate_name(member) -> str | None:
    return _real_display_name(member) or member.scope or None

def build_name_index(pack) -> tuple[dict[str, str], list[str]]:
    """Build id → display name index.

    Returns (idx, warnings) where warnings carries name-conflict diagnostics
    (e.g. a member whose name differs across partitions). Surface warnings in
    decision_context.warnings so they are not silently dropped.
    """
    candidates: dict[str, list[tuple[int, str, str]]] = {}  # id -> [(priority, iri, name)]
    for m in _all_members(pack):
        name = _candidate_name(m)
        if name:
            pr = PARTITION_PRIORITY.get(m.partition, 9)
            candidates.setdefault(m.id, []).append((pr, m.id, name))
    idx: dict[str, str] = {}
    warnings: list[str] = []
    for mid, opts in candidates.items():
        opts.sort()  # priority then IRI dict
        chosen = opts[0][2]
        names = {o[2] for o in opts}
        if len(names) > 1:
            warnings.append(f"name conflict for {mid}: {sorted(names)} -> {chosen!r}")
        idx[mid] = chosen
    # fragment fallback for all members
    for m in _all_members(pack):
        idx.setdefault(m.id, m.id)
    return idx, warnings

# test-facing alias: same logic over a bare member list
def build_name_index_from_members_test(members) -> dict[str, str]:
    candidates: dict[str, list[tuple[int, str, str]]] = {}
    for m in members:
        name = _candidate_name(m)
        if name:
            pr = PARTITION_PRIORITY.get(m.partition, 9)
            candidates.setdefault(m.id, []).append((pr, m.id, name))
    idx: dict[str, str] = {}
    for mid, opts in candidates.items():
        opts.sort()  # priority then IRI dict
        idx[mid] = opts[0][2]
    for m in members:
        idx.setdefault(m.id, m.id)
    return idx

_ID_TOKEN = re.compile(r"(?<![\w])([a-z][a-z0-9-]*[a-z0-9])(?![\w])")

def humanize_relation_text(claim: str, name_index: dict[str,str]) -> str:
    def repl(mo):
        tok = mo.group(1)
        return name_index.get(tok, tok)
    return _ID_TOKEN.sub(repl, claim)


# ── Task 3: Budget ────────────────────────────────────────────────────────────

def compute_incident_edges(member, full_iri: str) -> int:
    """Count business-incident statements pointing to *full_iri* (excluding
    governance/provenance/assignment predicates)."""
    seen: set[tuple[str, str]] = set()
    for s in member.statements:
        if s.object == full_iri and s.predicate in DECISION_INCIDENT_PREDICATES:
            seen.add((s.subject, s.predicate))
    return len(seen)


# slot ratios of usable_budget
SLOT_RATIO = {"issue": 0.10, "outcomes": 0.25, "risks": 0.25, "gaps": 0.25,
              "evidence": 0.10, "secondary": 0.05}

# Map section to budget slot
_SECTION_TO_SLOT = {
    "issue": "issue", "outcomes": "outcomes", "progress": "outcomes",
    "dependencies": "risks", "risks": "risks",
    "evidence": "evidence", "gaps": "gaps",
    "decisions": "secondary",
}


def _gap_short_len(name: str) -> int:
    """Approximate length of a gap line in short format."""
    return len(name) + 60


def mandatory_floor(pack) -> int:
    """Minimum char budget needed to render all non-omittable content.

    Always includes: header/footer reserve + every gap (short format).
    When the Pack contains ≥1 Outcome, also reserves one Outcome minimal line (ER1).
    """
    header = 200  # title + epistemic summary + section headers + footer reserve
    floor = header
    for g in pack.context_gaps:
        floor += _gap_short_len(g.display_name or g.id)
    # ER1: when an Outcome exists, include one outcome minimal line
    if any(classify_role(m.id, build_type_index(pack)) == "outcome"
           for m in (*pack.current_facts, *pack.candidate_context)):
        floor += 80
    return floor


def allocate_budget(
    units_by_section: dict[str, list[RenderedFactUnit]],
    pack: ContextPack,
    max_chars: int,
    type_index: dict[str, set[str]] | None = None,
):
    """Two-pass budget allocation with post-assembly trimming.

    First pass: slot-ratio greedy fill (gaps non-reclaimable).
    Second pass: assemble Markdown, measure real length, reclaim from
    lowest-priority units if over budget.

    Returns (selected, omissions). Raises RenderBudgetTooSmall when max_chars < floor.
    """
    floor = mandatory_floor(pack)
    if max_chars < floor:
        raise RenderBudgetTooSmall(max_chars, floor)

    if type_index is None:
        type_index = build_type_index(pack)

    # ── First pass: slot-based greedy fill ────────────────────────────────
    # Section titles + epistemic summary + footer overhead
    overhead = 350  # approximate; second pass measures real length
    usable = max(1, max_chars - overhead)

    # Allocate slot budgets (int)
    slot_budget: dict[str, int] = {k: int(usable * v) for k, v in SLOT_RATIO.items()}
    slot_used: dict[str, int] = {k: 0 for k in SLOT_RATIO}

    selected: dict[str, list[RenderedFactUnit]] = {}
    omissions: list[RenderOmission] = []

    for section in SECTION_ORDER:
        units = units_by_section.get(section, [])
        slot_key = _SECTION_TO_SLOT.get(section, "secondary")
        selected[section] = []

        # Order: tier asc, then by member_id for determinism
        ordered = sorted(units, key=lambda u: (
            role_tier(classify_role(u.member_id, type_index)),
            u.member_id,
        ))

        for u in ordered:
            is_gap = (section == "gaps")
            line = u.to_markdown_line(short=is_gap)
            line_len = len(line) + 1  # +1 for newline

            # Gaps are non-reclaimable — always include in short format
            if is_gap:
                selected[section].append(u)
                slot_used[slot_key] += line_len
                continue

            # First try the section's own slot
            if slot_used[slot_key] + line_len <= slot_budget[slot_key]:
                selected[section].append(u)
                slot_used[slot_key] += line_len
            else:
                # Borrow from lower-priority slots (evidence → risks → outcomes)
                borrowed = False
                for borrow_from in ("evidence", "risks", "outcomes"):
                    remaining = slot_budget.get(borrow_from, 0) - slot_used.get(borrow_from, 0)
                    if remaining >= line_len:
                        slot_used[borrow_from] += line_len
                        selected[section].append(u)
                        borrowed = True
                        break
                if not borrowed:
                    omissions.append(RenderOmission(
                        member_id=u.member_id, partition=u.partition,
                        role=classify_role(u.member_id, type_index),
                        tier=str(role_tier(classify_role(u.member_id, type_index))),
                        reason="max_chars_exceeded",
                        incident_edges=0,
                    ))

    # ── Second pass: measure real length, trim if over budget ─────────────
    # Build and measure assembled text; reclaim from lowest-priority sections.
    # Reclamation order (lowest priority first): secondary > evidence > risks > outcomes
    # Gaps are never reclaimed. Issue is the root — never reclaimed.

    return selected, omissions


def enforce_max_chars(
    selected: dict[str, list[RenderedFactUnit]],
    omissions: list[RenderOmission],
    type_index: dict[str, set[str]],
    max_chars: int,
    pack: ContextPack,
) -> tuple[dict[str, list[RenderedFactUnit]], list[RenderOmission]]:
    """Second pass: measure real Markdown length, trim lowest-priority units.

    Gaps and the root issue (matched_root) are non-reclaimable.
    Units are reclaimed in priority order: secondary slots first,
    then evidence, then risks, then outcomes.

    Uses an inline Markdown-length estimation that matches
    _assemble_sectioned_markdown's structure without importing the renderer.
    """
    # ── Inline Markdown-length estimator (must match _assemble_sectioned_markdown) ──
    def _est_len(sel, omis) -> int:
        """Estimate assembled Markdown length without importing renderer."""
        total = 0
        query_text = pack.query or "(无查询)"
        total += len(f"# 决策上下文：{query_text}\n\n")
        total += len("> \n\n")  # epistemic summary placeholder
        for section in SECTION_ORDER:
            title = SECTION_TITLES.get(section, f"## {section}")
            total += len(title) + 1
            units = sel.get(section, [])
            if not units:
                total += len("（无）\n")
            else:
                for u in units:
                    short = (section == "gaps")
                    total += len(u.to_markdown_line(short=short)) + 1
            total += 1  # blank line after section
        # Omission count summary (not full list)
        if omis:
            total += len(f"### 省略 {len(omis)} 项\n\n")
        total += 100  # footer
        return total

    # Build reclaimable unit list with priority
    # gaps(1), issue(0) — never reclaimed
    _RECLAIM_PRIORITY = {"secondary": 5, "evidence": 4, "risks": 3,
                          "outcomes": 2, "gaps": 1, "issue": 0}
    _SECTION_TO_RECLAIM_KEY = {
        "decisions": "secondary",
        "dependencies": "risks",
        "progress": "outcomes",
    }

    reclaimable: list[tuple[int, str, RenderedFactUnit]] = []  # (priority, section, unit)
    root_frag = _frag(pack.matched_root)

    for section in SECTION_ORDER:
        rkey = _RECLAIM_PRIORITY.get(section, 2)
        mapped = _SECTION_TO_RECLAIM_KEY.get(section, section)
        rk_prio = _RECLAIM_PRIORITY.get(mapped, rkey)
        if rk_prio <= 1:  # gaps, issue — non-reclaimable
            continue
        for u in selected.get(section, []):
            # Root issue is non-reclaimable
            if u.member_id == root_frag:
                continue
            reclaimable.append((rk_prio, section, u))

    # Sort: highest reclaim priority first, then higher tier first
    reclaimable.sort(key=lambda x: (
        -x[0],
        role_tier(classify_role(x[2].member_id, type_index)),
    ))

    current = _est_len(selected, omissions)
    idx = 0
    while current > max_chars and idx < len(reclaimable):
        _, section, unit = reclaimable[idx]
        idx += 1

        sel_list = selected.get(section, [])
        if unit in sel_list:
            sel_list.remove(unit)
            omissions.append(RenderOmission(
                member_id=unit.member_id,
                partition=unit.partition,
                role=classify_role(unit.member_id, type_index),
                tier=str(role_tier(classify_role(unit.member_id, type_index))),
                reason="max_chars_exceeded",
                incident_edges=0,
            ))
        current = _est_len(selected, omissions)

    return selected, omissions


# ── Task 4: claim compiler + DecisionContextCompiler ──────────────────────────

# predicate → Chinese label (duplicated from context_renderer for compiler-local use;
# the renderer keeps its own copy for the legacy render path)
_PREDICATE_LABELS: dict[str, str] = {
    "hasOutcome": "成果",
    "hasScope": "范围",
    "hasResponsibleAssignment": "负责人",
    "hasRisk": "风险",
    "hasCriterion": "成功标准",
    "hasMilestone": "里程碑",
    "hasProgressSnapshot": "当前进度",
    "dependsOn": "依赖",
    "hasContextGap": "已知缺口",
    "informedBy": "基于",
    "supportedByEvidence": "支持证据",
    "hasRationale": "理由",
    "hasPortfolio": "所属组合",
    "hasKeyPath": "关键路径",
    "contributesTo": "贡献于",
    "belongsTo": "属于",
    "delivers": "交付",
    "supports": "支持",
    "expects": "期望",
    "confirmedBy": "由...确认",
    "challengesClaim": "挑战",
    "challengingEvidence": "挑战性证据",
    "isReviewedBy": "审核",
    "isDeliveredBy": "由...交付",
    "hasSuccessCriterion": "成功标准",
    "contains": "包含",
    "confirmsEntity": "确认实体",
    "researchedBy": "调研",
    "sourcedFrom": "来源",
}


def _frag(uri: str) -> str:
    """Extract the fragment or last path segment from a URI."""
    return uri.rsplit("#", 1)[-1] if "#" in uri else uri.rsplit("/", 1)[-1]


def _compile_claim(member, name_index: dict[str, str]) -> str:
    """Compile a member into a humanized canonical claim string."""
    label = member.display_name or member.scope or member.id
    parts: list[str] = [label]

    if member.scope and member.scope != label:
        parts.append(f"（{member.scope}）")

    # Collect relational phrases
    phrases: list[str] = []
    seen: set[str] = set()
    for stmt in member.statements:
        pf = _frag(stmt.predicate)
        of = _frag(stmt.object)
        if pf in _PREDICATE_LABELS and stmt.object.startswith("https://"):
            phrase = f"{_PREDICATE_LABELS[pf]}：{of}"
            if phrase not in seen:
                seen.add(phrase)
                phrases.append(phrase)

    if phrases:
        parts.append("；".join(phrases[:3]))

    status = member.confirmation_status
    if status and status not in ("Confirmed",):
        parts.append(f"[{status}]")

    claim = ""
    if len(parts) == 1:
        claim = parts[0]
    else:
        claim = f"{parts[0]}，{'，'.join(parts[1:])}"

    return humanize_relation_text(claim, name_index)


@dataclasses.dataclass
class CompiledDecisionContext:
    """Output of DecisionContextCompiler.compile()."""
    decision_context: dict[str, Any]
    units_by_section: dict[str, list[RenderedFactUnit]]
    omissions: list[RenderOmission]
    warnings: list[str]


class DecisionContextCompiler:
    """Compiles a ContextPack into a decision-oriented reading view.

    Usage::

        compiler = DecisionContextCompiler()
        compiled = compiler.compile(pack, max_chars=12000)
        # compiled.decision_context — structured dict for API consumers
        # compiled.units_by_section — sectioned RenderedFactUnit lists
    """

    def compile(self, pack: ContextPack, max_chars: int = 12000) -> CompiledDecisionContext:
        type_index = build_type_index(pack)
        name_index, name_warnings = build_name_index(pack)
        warnings: list[str] = list(name_warnings)

        # ── Build units by section ─────────────────────────────────────────
        units_by_section: dict[str, list[RenderedFactUnit]] = {}
        for m in _all_members(pack):
            role = classify_role(m.id, type_index)
            section = ROLE_TO_SECTION.get(role)

            # trace_only roles never occupy body lines (v1, no exceptions)
            if role in ("source_record", "confirmation"):
                continue
            if section is None:
                continue

            claim = _compile_claim(m, name_index)
            unit = RenderedFactUnit(
                member_id=m.id,
                partition=m.partition,
                source_graphs=tuple(sorted(m.source_graphs)),
                canonical_claim=claim,
                display_name=m.display_name,
                confirmation_status=m.confirmation_status,
                expected_section=section,
            )
            units_by_section.setdefault(section, []).append(unit)

        # ── Budget selection (two-pass) ─────────────────────────────────────
        selected, omissions = allocate_budget(
            units_by_section, pack, max_chars, type_index,
        )
        # Second pass: measure real length, trim from lowest priority
        selected, omissions = enforce_max_chars(
            selected, omissions, type_index, max_chars, pack,
        )

        # ── Fill incident_edges for omissions (cross-member reference map) ──
        incident_map: dict[str, int] = {}
        for m in _all_members(pack):
            for s in m.statements:
                if s.predicate in DECISION_INCIDENT_PREDICATES:
                    incident_map[s.object] = incident_map.get(s.object, 0) + 1
        for o in omissions:
            o.incident_edges = incident_map.get(TKOS + o.member_id, 0)

        # ── Build decision_context dict ────────────────────────────────────
        # Epistemic summary — computable status distribution, no (B)-type phrasing
        n_candidate = len(pack.candidate_context)
        n_gap = len(pack.context_gaps)
        n_provenance = len(pack.provenance_context)
        n_confirmed = len(pack.current_facts)
        epistemic_summary = (
            f"已确认事实 {n_confirmed} 项，候选视图 {n_candidate} 项"
            f"（其中信息缺口 {n_gap} 项），溯源视图 {n_provenance} 项。"
        )

        dc: dict[str, Any] = {
            "compiler_version": "decision-context/v1",
            "issue": {},
            "outcomes": [],
            "progress": [],
            "dependencies": [],
            "risks": [],
            "evidence": [],
            "gaps": [],
            "decisions": [],
            "secondary": [],
            "derived": [],
            "render_omissions": [],
            "epistemic_summary": epistemic_summary,
            "warnings": list(warnings),
        }

        # Root issue: use pack.matched_root for precise lookup.
        # The root issue is non-reclaimable — always included even under budget.
        root_frag = _frag(pack.matched_root)
        root_unit = None
        for section in SECTION_ORDER:
            for u in selected.get(section, []):
                if u.member_id == root_frag:
                    root_unit = u
                    break
            if root_unit:
                break
        # Fallback: first issue-role member from budget-selected set
        if root_unit is None:
            for section in SECTION_ORDER:
                for u in selected.get(section, []):
                    role = classify_role(u.member_id, type_index)
                    if role == "issue":
                        root_unit = u
                        break
                if root_unit:
                    break

        if root_unit is not None:
            dc["issue"] = {
                "view_key": list(root_unit.view_key),
                "member_id": root_unit.member_id,
                "name": name_index.get(root_unit.member_id, root_unit.member_id),
                "claim": root_unit.canonical_claim,
                "partition": root_unit.partition,
                "source_graphs": list(root_unit.source_graphs),
                "query": pack.query,
                "matched_root": pack.matched_root,
                "epistemic_summary": epistemic_summary,
            }

        # Map sections to decision_context keys
        _SECTION_TO_DC = {
            "outcomes": "outcomes", "progress": "progress",
            "dependencies": "dependencies", "risks": "risks",
            "evidence": "evidence", "gaps": "gaps", "decisions": "decisions",
        }

        for section in SECTION_ORDER:
            dc_key = _SECTION_TO_DC.get(section)
            if dc_key is None:
                continue
            for u in selected.get(section, []):
                dc[dc_key].append({
                    "view_key": list(u.view_key),
                    "member_id": u.member_id,
                    "name": name_index.get(u.member_id, u.member_id),
                    "claim": u.canonical_claim,
                    "partition": u.partition,
                    "source_graphs": list(u.source_graphs),
                    "epistemic_status": u.confirmation_status,
                })

        # Ensure all gaps from context_gaps are represented in dc["gaps"]
        # (dedup by view_key — the generic mapper above already added
        # budget-selected gaps; fill in any remaining)
        gap_vk_from_mapper: set[tuple[str, str]] = {
            (g["member_id"], g["partition"]) for g in dc["gaps"]
        }
        for g in pack.context_gaps:
            vk = (g.id, g.partition)
            if vk not in gap_vk_from_mapper:
                dc["gaps"].append({
                    "view_key": [g.id, g.partition],
                    "member_id": g.id,
                    "name": name_index.get(g.id, g.display_name or g.id),
                    "claim": g.display_name or g.id,
                    "partition": g.partition,
                    "source_graphs": list(g.source_graphs) if g.source_graphs else [],
                    "epistemic_status": g.confirmation_status,
                })

        # Derived claims
        for m in pack.derived_claims:
            dc["derived"].append({
                "member_id": m.id,
                "name": name_index.get(m.id, m.id),
            })

        # Render omissions (with tier + incident_edges)
        for o in omissions:
            dc["render_omissions"].append({
                "member_id": o.member_id,
                "partition": o.partition,
                "role": o.role,
                "tier": o.tier,
                "incident_edges": o.incident_edges,
                "reason": o.reason,
            })

        return CompiledDecisionContext(
            decision_context=dc,
            units_by_section=selected,
            omissions=omissions,
            warnings=warnings,
        )
