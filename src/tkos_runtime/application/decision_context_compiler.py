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

from tkos_runtime.domain.models import ContextPack, ContextRootMissingError
from tkos_runtime.domain.render_units import (
    DECISION_INCIDENT_PREDICATES, RenderOmission, RenderBudgetTooSmall,
    SECTION_ORDER, SECTION_TITLES, ROLE_TO_SECTION, RenderedFactUnit,
    assemble_sectioned_markdown,
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


def _epistemic_summary(pack: ContextPack) -> str:
    """Computable status distribution — no (B)-type judgement phrasing."""
    return (
        f"已确认事实 {len(pack.current_facts)} 项，候选视图 {len(pack.candidate_context)} 项"
        f"（其中信息缺口 {len(pack.context_gaps)} 项），溯源视图 {len(pack.provenance_context)} 项。"
    )


def mandatory_view_keys(
    pack: ContextPack,
    units_by_section: dict[str, list[RenderedFactUnit]],
    type_index: dict[str, set[str]] | None = None,
) -> set[tuple[str, str]]:
    """View keys that must never be omitted: the root (matched_root), every
    gap, every proven related-issue view, and — when the pack has outcome
    units — at least one outcome.

    P0-1: root 按 member_id 在**全部 section** 中查找（不再假设 root 是
    StrategicIssue 归 issue section）。Research/Outcome/Mission 等实体
    查询合法，其 root 同样受保护。

    R4: proven related-issue 视图为 mandatory——决策上下文的 structured
    related_issue 与 Markdown"关联经营议题"必须同生同灭（评审四审：
    不得出现 related_issue 有值但正文被预算裁剪的不一致）。
    """
    if type_index is None:
        type_index = build_type_index(pack)
    keys: set[tuple[str, str]] = set()
    if pack.matched_root:
        root_frag = _frag(pack.matched_root)
        for section in SECTION_ORDER:
            found = False
            for u in units_by_section.get(section, []):
                if u.member_id == root_frag:
                    keys.add(u.view_key)
                    found = True
                    break
            if found:
                break
    for pv in proven_related_issue_views(pack, type_index):
        keys.add((pv["member_id"], pv["partition"]))
    for u in units_by_section.get("gaps", []):
        keys.add(u.view_key)
    outcomes = units_by_section.get("outcomes", [])
    if outcomes:
        keys.add(outcomes[0].view_key)
    return keys


def mandatory_floor(
    pack: ContextPack,
    units_by_section: dict[str, list[RenderedFactUnit]],
    mandatory_keys: set[tuple[str, str]] | None = None,
    type_index: dict[str, set[str]] | None = None,
) -> int:
    """Exact minimum char budget: mandatory views + fixed text.

    Computed from the real sectioned assembly — mandatory units in their
    actual short/long line format (complete three-part anchors), real
    section titles, real epistemic summary, empty-section placeholders and
    footer. Includes the worst-case omission summary (every non-mandatory
    unit omitted), so a request of exactly max_chars == floor renders the
    mandatory views only and never overflows.
    """
    if type_index is None:
        type_index = build_type_index(pack)
    if mandatory_keys is None:
        mandatory_keys = mandatory_view_keys(pack, units_by_section)

    mandatory_units = {
        section: [u for u in units if u.view_key in mandatory_keys]
        for section, units in units_by_section.items()
    }
    # Worst case: every non-mandatory unit ends up in the omission summary.
    all_omitted = [
        RenderOmission(
            member_id=u.member_id, partition=u.partition,
            role=classify_role(u.member_id, type_index),
            tier=str(role_tier(classify_role(u.member_id, type_index))),
            reason="max_chars_exceeded", incident_edges=0,
        )
        for units in units_by_section.values()
        for u in units
        if u.view_key not in mandatory_keys
    ]
    return len(assemble_sectioned_markdown(
        mandatory_units, _epistemic_summary(pack), all_omitted, pack,
    ))


def allocate_budget(
    units_by_section: dict[str, list[RenderedFactUnit]],
    pack: ContextPack,
    max_chars: int,
    type_index: dict[str, set[str]] | None = None,
    mandatory_keys: set[tuple[str, str]] | None = None,
):
    """Two-pass budget allocation with exact post-assembly trimming.

    First pass: mandatory views (root issue + all gaps + one outcome) are
    pre-selected and bypass slot competition; remaining units fill their
    ratio slots with borrowing. Raises RenderBudgetTooSmall when max_chars
    cannot hold the mandatory views (real assembled length).
    Second pass (enforce_max_chars): assemble real Markdown, reclaim from
    the lowest-priority non-mandatory units until within budget.

    Returns (selected, omissions).
    """
    if type_index is None:
        type_index = build_type_index(pack)
    if mandatory_keys is None:
        mandatory_keys = mandatory_view_keys(pack, units_by_section)

    # Floor: exact real length of mandatory views + fixed text (incl. the
    # worst-case omission summary). max_chars below this can never succeed.
    floor = mandatory_floor(pack, units_by_section, mandatory_keys, type_index)
    if max_chars < floor:
        raise RenderBudgetTooSmall(max_chars, floor)

    # ── First pass: mandatory views pre-selected, bypass slot competition ──
    # Section titles + epistemic summary + footer overhead (approximate;
    # the second pass measures real length exactly).
    overhead = 350
    usable = max(1, max_chars - overhead)

    # Allocate slot budgets (int)
    slot_budget: dict[str, int] = {k: int(usable * v) for k, v in SLOT_RATIO.items()}
    slot_used: dict[str, int] = {k: 0 for k in SLOT_RATIO}

    selected: dict[str, list[RenderedFactUnit]] = {}
    omissions: list[RenderOmission] = []
    for section in SECTION_ORDER:
        selected[section] = []

    for section in SECTION_ORDER:
        for u in units_by_section.get(section, []):
            if u.view_key not in mandatory_keys:
                continue
            selected[section].append(u)
            slot_key = _SECTION_TO_SLOT.get(section, "secondary")
            line_len = len(u.to_markdown_line(short=(section == "gaps"))) + 1
            slot_used[slot_key] += line_len

    # ── First pass (cont.): slot-ratio greedy fill for the remainder ──────
    for section in SECTION_ORDER:
        units = units_by_section.get(section, [])
        slot_key = _SECTION_TO_SLOT.get(section, "secondary")

        # Order: tier asc, then by member_id for determinism
        ordered = sorted(units, key=lambda u: (
            role_tier(classify_role(u.member_id, type_index)),
            u.member_id,
        ))

        for u in ordered:
            if u.view_key in mandatory_keys:
                continue
            line = u.to_markdown_line(short=(section == "gaps"))
            line_len = len(line) + 1  # +1 for newline

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


def enforce_max_chars(
    selected: dict[str, list[RenderedFactUnit]],
    omissions: list[RenderOmission],
    type_index: dict[str, set[str]],
    max_chars: int,
    pack: ContextPack,
    mandatory_keys: set[tuple[str, str]] | None = None,
) -> tuple[dict[str, list[RenderedFactUnit]], list[RenderOmission]]:
    """Second pass: assemble real Markdown, trim lowest-priority units.

    Reclamation order (lowest priority first): secondary > evidence > risks
    > outcomes. Mandatory views (root issue, gaps, first outcome) are never
    reclaimed. Length is measured with the same assembly the renderer uses,
    so the budget is exact — no estimator drift.
    """
    if mandatory_keys is None:
        mandatory_keys = mandatory_view_keys(pack, selected)

    # Build reclaimable unit list with priority
    # gaps(1), issue(0) — only via mandatory_keys are they non-reclaimable
    _RECLAIM_PRIORITY = {"secondary": 5, "evidence": 4, "risks": 3,
                          "outcomes": 2, "gaps": 1, "issue": 0}
    _SECTION_TO_RECLAIM_KEY = {
        "decisions": "secondary",
        "dependencies": "risks",
        "progress": "outcomes",
    }

    reclaimable: list[tuple[int, str, RenderedFactUnit]] = []  # (priority, section, unit)
    for section in SECTION_ORDER:
        rkey = _RECLAIM_PRIORITY.get(section, 2)
        mapped = _SECTION_TO_RECLAIM_KEY.get(section, section)
        rk_prio = _RECLAIM_PRIORITY.get(mapped, rkey)
        for u in selected.get(section, []):
            if u.view_key in mandatory_keys:
                continue
            reclaimable.append((rk_prio, section, u))

    # Sort: highest reclaim priority first, then higher tier first
    reclaimable.sort(key=lambda x: (
        -x[0],
        role_tier(classify_role(x[2].member_id, type_index)),
    ))

    summary = _epistemic_summary(pack)
    current = len(assemble_sectioned_markdown(selected, summary, omissions, pack))
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
        current = len(assemble_sectioned_markdown(selected, summary, omissions, pack))

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


def proven_related_issue_views(
    pack: ContextPack,
    type_index: dict[str, set[str]],
) -> list[dict[str, Any]]:
    """Proven related-issue views（评审四审契约，单一事实来源）。

    StrategicIssue 成员（≠ root）中，存在显式 DECISION_INCIDENT_
    PREDICATES 业务边连接 matched_root（双向）的成员——其全部视图
    （member_id, partition）均为"已证明的关联经营议题视图"。稳定排序
    （member_id, partition）取序。同一视图集合同时驱动：

      * decision_context.related_issue（取序首）
      * Markdown "关联经营议题" 章节（issue section 单元来源）
      * 预算选择与 omission（proven 视图为 mandatory，永不裁剪）
      * section-aware LLM 校验（期望视图集 = compiled issue section）

    视图粒度不按 member_id 合并跨分区视图（评审四审：保留
    view_key=(member_id, partition)）。
    """
    root = pack.matched_root
    root_frag = _frag(root) if root else None
    if not root_frag:
        return []
    cand_ids: set[str] = set()
    cand_views: set[tuple[str, str]] = set()
    for m in _all_members(pack):
        if m.id == root_frag or classify_role(m.id, type_index) != "issue":
            continue
        cand_ids.add(m.id)
        cand_views.add((m.id, m.partition))
    proven_ids: set[str] = set()
    edge_by_member: dict[str, list[tuple[str, str]]] = {}
    for m in _all_members(pack):
        for s in m.statements:
            if s.predicate not in DECISION_INCIDENT_PREDICATES:
                continue
            if str(s.subject).startswith(TKOS) and s.subject == root:
                oid = _frag(s.object)
                if oid in cand_ids:
                    proven_ids.add(oid)
                    edge_by_member.setdefault(oid, []).append(
                        (s.predicate, s.source_graph))
            elif (str(s.object).startswith(TKOS) and s.object == root):
                sid = _frag(s.subject)
                if sid in cand_ids:
                    proven_ids.add(sid)
                    edge_by_member.setdefault(sid, []).append(
                        (s.predicate, s.source_graph))
    result: list[dict[str, Any]] = []
    for mid, part in sorted(cand_views):
        if mid not in proven_ids:
            continue
        predicate, edge_sg = sorted(edge_by_member[mid])[0]
        result.append({
            "view_key": [mid, part],
            "member_id": mid,
            "partition": part,
            "predicate": _frag(predicate),
            "edge_source_graph": edge_sg,
        })
    return result


def _build_units_by_section(
    pack: ContextPack,
    type_index: dict[str, set[str]],
    name_index: dict[str, str],
) -> dict[str, list[RenderedFactUnit]]:
    """Compile all pack members into sectioned RenderedFactUnit lists.

    trace_only roles (source_record, confirmation) never occupy body lines
    (v1, no exceptions). matched_root 统一进 anchor（任何类型——用户审定的
    选项 2：非 ROLE_TABLE 类型 root 也生成通用 anchor 单元，保证可编译）。
    issue 章节只承载 proven_related_issue_views（评审四审：无显式业务边
    的 StrategicIssue 不进"关联经营议题"，与 related_issue=null 一致）。
    """
    units_by_section: dict[str, list[RenderedFactUnit]] = {}
    root_frag = _frag(pack.matched_root) if pack.matched_root else None
    proven_issue_keys = {
        (pv["member_id"], pv["partition"])
        for pv in proven_related_issue_views(pack, type_index)
    }
    for m in _all_members(pack):
        role = classify_role(m.id, type_index)
        section = ROLE_TO_SECTION.get(role)
        if role in ("source_record", "confirmation"):
            continue
        if section is None:
            # P0-4（评审 B4 反例）：非 ROLE_TABLE 类型（如
            # CompetitiveBarrier/barrier-five-control-points）仍可作
            # matched_root → 通用 anchor 单元。非 root 的 other 成员
            # 保持跳过（v1 不加噪）。
            if m.id != root_frag:
                continue
            section = "anchor"
        # root 统一进 anchor：用户本次问题所问实体就是查询锚点。
        # 其他 StrategicIssue 只作"关联经营议题"（issue 章节）——且
        # 仅限已证明（显式业务边）的视图（评审四审契约）。
        if m.id == root_frag:
            section = "anchor"
        elif section == "issue" and (m.id, m.partition) not in proven_issue_keys:
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
    return units_by_section


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

    @staticmethod
    def _verify_root_integrity(
        pack: ContextPack,
        dc: dict[str, Any],
        selected: dict[str, list[RenderedFactUnit]],
        omissions: list[RenderOmission],
    ) -> None:
        """P0-3: matched_root 必须与最终输出一致（全链路硬校验）。

        检查五项，任一失败即 ContextRootMissingError（→ 500）：
        1. root 存在于最终视图（防 ghost-root 静默丢失）
        2. root 不在 render_omissions（防预算裁剪 root）
        3. issue.member_id == fragment(matched_root)——仅当 issue 非空
           （评审三审契约：非 Issue root 的 issue = null，此时只校验
           anchor；issue 字段只允许承载 StrategicIssue）
        4. issue.matched_root == pack.matched_root（同上条件，防替换）
        5. anchor.member_id == fragment(matched_root)（评审 B3：查询锚点
           必须指向 root；正文级校验在 render() 装配后另行检查）
        """
        root_frag = _frag(pack.matched_root)
        present = any(
            u.member_id == root_frag
            for units in selected.values() for u in units
        )
        if not present:
            raise ContextRootMissingError(
                f"matched_root 不在最终视图中：{pack.matched_root}",
                matched_root=pack.matched_root,
                stage="decision_context_compilation",
            )
        if any(o.member_id == root_frag for o in omissions):
            raise ContextRootMissingError(
                f"matched_root 被裁剪进 render_omissions：{root_frag}",
                matched_root=pack.matched_root,
                stage="decision_context_compilation",
            )
        issue = dc.get("issue")
        if issue is not None:
            if issue.get("member_id") != root_frag:
                raise ContextRootMissingError(
                    f"issue.member_id 与 matched_root 不一致："
                    f"{issue.get('member_id')!r} != {root_frag!r}",
                    matched_root=pack.matched_root,
                    stage="decision_context_compilation",
                )
            if issue.get("matched_root") != pack.matched_root:
                raise ContextRootMissingError(
                    f"issue.matched_root 与 pack.matched_root 不一致："
                    f"{issue.get('matched_root')!r} != {pack.matched_root!r}",
                    matched_root=pack.matched_root,
                    stage="decision_context_compilation",
                )
        anchor = dc.get("anchor", {})
        if anchor.get("member_id") != root_frag:
            raise ContextRootMissingError(
                f"anchor.member_id 与 matched_root 不一致："
                f"{anchor.get('member_id')!r} != {root_frag!r}",
                matched_root=pack.matched_root,
                stage="decision_context_compilation",
            )

    def compile(self, pack: ContextPack, max_chars: int = 12000) -> CompiledDecisionContext:
        type_index = build_type_index(pack)
        name_index, name_warnings = build_name_index(pack)
        warnings: list[str] = list(name_warnings)

        # Epistemic summary — computable status distribution, no (B)-type phrasing
        epistemic_summary = _epistemic_summary(pack)

        # ── Build units by section ─────────────────────────────────────────
        units_by_section = _build_units_by_section(pack, type_index, name_index)

        # ── Budget selection (two-pass, exact) ─────────────────────────────
        # Mandatory views (root issue + all gaps + one outcome) are computed
        # up front, pre-selected in the first pass, and never reclaimed in
        # the second pass. max_chars < mandatory_floor → RenderBudgetTooSmall.
        mandatory_keys = mandatory_view_keys(
            pack, units_by_section, type_index)
        selected, omissions = allocate_budget(
            units_by_section, pack, max_chars, type_index,
            mandatory_keys=mandatory_keys,
        )
        # Second pass: measure real assembled length, trim from lowest priority
        selected, omissions = enforce_max_chars(
            selected, omissions, type_index, max_chars, pack,
            mandatory_keys=mandatory_keys,
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

        # Root: use pack.matched_root for precise lookup across ALL sections
        # (P0-1: root 不限定 StrategicIssue；按 member_id 全局找，且 root 为
        # mandatory view 永不进 omissions）。P0-2: root 视图缺失 = 完整性
        # 错误 → ContextRootMissingError，绝不 fallback 到别的 issue。
        root_frag = _frag(pack.matched_root)
        root_unit = None
        for section in SECTION_ORDER:
            for u in selected.get(section, []):
                if u.member_id == root_frag:
                    root_unit = u
                    break
            if root_unit:
                break
        if root_unit is None:
            raise ContextRootMissingError(
                f"matched_root 未进入最终视图：{pack.matched_root}",
                matched_root=pack.matched_root,
                stage="decision_context_compilation",
            )

        # P0-4（评审三审契约）：issue 只承载 StrategicIssue。root 的
        # rdf_types 不含 StrategicIssue（Research/Outcome/CompetitiveBarrier
        # 等）时 issue = null——Agent 不得把研究对象解释成经营议题；
        # anchor 始终 = matched_root（任何类型）。
        root_types_full = type_index.get(root_frag, set())
        root_is_issue = TKOS + "StrategicIssue" in root_types_full
        if root_is_issue:
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
        else:
            dc["issue"] = None

        # P0-4（评审 B3/B4 契约）：查询上下文 schema —— query_context /
        # anchor / related_issue。anchor = 用户本次问题所问实体（root，
        # 任何类型）。
        root_types = sorted({_frag(t) for t in root_types_full})
        dc["query_context"] = {"query": pack.query}
        dc["anchor"] = {
            "view_key": list(root_unit.view_key),
            "member_id": root_unit.member_id,
            "name": name_index.get(root_unit.member_id, root_unit.member_id),
            "claim": root_unit.canonical_claim,
            "partition": root_unit.partition,
            "source_graphs": list(root_unit.source_graphs),
            "type": " | ".join(root_types) or "Unclassified",
        }

        # P0-4（评审三审契约 + 四审统一）：related_issue 必须有显式业务
        # 边证据，且与 Markdown"关联经营议题"共用同一份 proven 视图集
        # （评审四审：结构化与正文不得不一致——related_issue=null 时
        # 正文不得出现无边 Issue；proven 视图为 mandatory 永不裁剪）。
        # 视图级粒度（member_id, partition），稳定排序取首（后续升级
        # related_issues[]）。
        proven_views = proven_related_issue_views(pack, type_index)
        if proven_views:
            pv = proven_views[0]
            mid, part = pv["member_id"], pv["partition"]
            rel_m = next(
                m for m in _all_members(pack)
                if (m.id, m.partition) == (mid, part))
            dc["related_issue"] = {
                "view_key": [mid, part],
                "member_id": mid,
                "name": name_index.get(mid, rel_m.display_name or mid),
                "claim": _compile_claim(rel_m, name_index),
                "partition": part,
                "source_graphs": list(rel_m.source_graphs)
                if rel_m.source_graphs else [],
                "predicate": pv["predicate"],
                "edge_source_graph": pv["edge_source_graph"],
            }
        else:
            dc["related_issue"] = None

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

        # P0-3: 一致性硬校验——matched_root 与最终输出必须一致。
        # 任何不一致都是完整性错误（500），绝不静默降级。
        self._verify_root_integrity(pack, dc, selected, omissions)

        return CompiledDecisionContext(
            decision_context=dc,
            units_by_section=selected,
            omissions=omissions,
            warnings=warnings,
        )
