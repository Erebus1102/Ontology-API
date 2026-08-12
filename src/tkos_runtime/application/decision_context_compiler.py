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
    SECTION_ORDER, ROLE_TO_SECTION, RenderedFactUnit,
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
    yield from pack.current_facts
    yield from pack.candidate_context
    yield from pack.provenance_context
    yield from pack.context_gaps
    yield from pack.derived_claims

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

def build_name_index(pack) -> dict[str, str]:
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
    return idx  # caller may surface warnings separately if needed

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
    """Two-pass budget allocation: greedy fill by slot ratio, gaps non-reclaimable.

    Returns (selected, omissions). Raises RenderBudgetTooSmall when max_chars < floor.
    """
    floor = mandatory_floor(pack)
    if max_chars < floor:
        raise RenderBudgetTooSmall(max_chars, floor)

    if type_index is None:
        type_index = build_type_index(pack)

    # fixed_text: section titles + footer + epistemic summary (generous estimate)
    fixed_text = 500
    usable = max(1, max_chars - fixed_text)

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
        name_index = build_name_index(pack)
        warnings: list[str] = []

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

        # ── Budget selection ───────────────────────────────────────────────
        selected, omissions = allocate_budget(
            units_by_section, pack, max_chars, type_index,
        )

        # ── Build decision_context dict ────────────────────────────────────
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
            "epistemic_summary": "",
        }

        # Root issue: first issue-role member from the budget-selected set
        for section in SECTION_ORDER:
            for u in selected.get(section, []):
                role = classify_role(u.member_id, type_index)
                if role == "issue" and not dc["issue"]:
                    dc["issue"] = {
                        "member_id": u.member_id,
                        "name": name_index.get(u.member_id, u.member_id),
                        "claim": u.canonical_claim,
                        "partition": u.partition,
                        "source_graphs": list(u.source_graphs),
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

        # All gaps in decision_context.gaps (full, not just budget-selected)
        gap_ids_from_units = {u.member_id for u in selected.get("gaps", [])}
        for g in pack.context_gaps:
            if g.id not in gap_ids_from_units:
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

        # Render omissions
        for o in omissions:
            dc["render_omissions"].append({
                "member_id": o.member_id,
                "partition": o.partition,
                "role": o.role,
                "reason": o.reason,
            })

        # Epistemic summary — computable status distribution, no (B)-type phrasing
        n_candidate = len(pack.candidate_context)
        n_gap = len(pack.context_gaps)
        n_provenance = len(pack.provenance_context)
        n_confirmed = len(pack.current_facts)
        dc["epistemic_summary"] = (
            f"已确认事实 {n_confirmed} 项，候选视图 {n_candidate} 项"
            f"（其中信息缺口 {n_gap} 项），溯源视图 {n_provenance} 项。"
        )

        return CompiledDecisionContext(
            decision_context=dc,
            units_by_section=selected,
            omissions=omissions,
            warnings=warnings,
        )
