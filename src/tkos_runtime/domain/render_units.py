# src/tkos_runtime/domain/render_units.py
"""Neutral render data models — imported by both the decision-context compiler
and the renderer, to avoid import cycles. Grounding principle: structural
validation only; NL semantic preservation is not_proven (see comments)."""
from __future__ import annotations
import dataclasses
from typing import Any, Optional

from tkos_runtime.domain.models import ContextPack
from tkos_runtime.domain.query_plan import TRAVERSAL, TKOS

# Render Schema version (the response contract). Wired into the response as
# ``render_schema_version`` only once Task 5 lands the v2 schema — until then
# the live response still reports the implementation version below.
RENDER_SCHEMA_VERSION = "context-render/2.0"
# Renderer implementation version (unchanged from pre-DCC baseline).
RENDERER_VERSION = "context-renderer/p0-v1"

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

# Governance/provenance/assignment predicates that would inflate incident_edges
# of objects referenced by many source/confirmation/assignment records.
# MUST be exhaustive — no ellipsis. Add tests when extending.
NON_DECISION_INCIDENT_PREDICATES = frozenset({
    TKOS + "sourcedFrom",
    TKOS + "confirmedBy",
    TKOS + "confirmsEntity",
    TKOS + "hasResponsibleAssignment",
    TKOS + "assignmentHolder",
    TKOS + "assignmentRole",
    TKOS + "assignmentScope",
})
DECISION_INCIDENT_PREDICATES = frozenset(TRAVERSAL) - NON_DECISION_INCIDENT_PREDICATES

# Fixed section order; program reassembles — LLM may not reorder.
# anchor 首位：查询锚点（用户本次问题所问实体，任何类型 root 统一入此）；
# issue 章节 = root 之外的 StrategicIssue（关联经营议题），仅当存在时呈现。
SECTION_ORDER = (
    "anchor", "issue", "outcomes", "progress", "dependencies", "risks",
    "gaps", "decisions",
)
SECTION_TITLES = {
    "anchor": "# 查询上下文",
    "issue": "## 关联经营议题",
    "outcomes": "## 决策目标",
    "progress": "## 当前进展与已有证据",
    "dependencies": "## 共同依赖与约束",
    "risks": "## 当前最重要的风险",
    "gaps": "## 拍板前需要补齐的信息",
    "decisions": "## 决策与判断依据",
}

# role -> expected section
ROLE_TO_SECTION = {
    "issue": "issue", "outcome": "outcomes", "progress": "progress",
    "dependency": "dependencies", "capability": "dependencies",
    "risk": "risks", "evidence": "progress", "context_gap": "gaps",
    "decision": "decisions", "rationale": "decisions",
    "mission": "outcomes", "criterion": "progress", "milestone": "progress",
    "responsibility": "dependencies",
}


def assemble_sectioned_markdown(
    units_by_section: dict[str, list["RenderedFactUnit"]],
    epistemic_summary: str,
    omissions: list["RenderOmission"],
    pack: ContextPack,
) -> str:
    """Assemble sectioned units into decision-oriented Markdown.

    Single source of truth for deterministic output — used by BOTH the
    DecisionContextCompiler (mandatory floor + exact post-assembly
    reclamation) and the renderer (final content), so the compiled budget
    always matches the rendered length. Omission summary counts only.
    """
    lines: list[str] = []
    query_text = pack.query or "(无查询)"
    lines.append(f"# 决策上下文：{query_text}")
    lines.append("")

    # Epistemic summary
    lines.append(f"> {epistemic_summary}")
    lines.append("")

    for section in SECTION_ORDER:
        if section == "anchor":
            # 查询上下文区块（评审 B3 契约）：用户问题 + 本体匹配锚点
            # （root 完整三段锚点）+ 关联经营议题（issue 章节单元在此
            # 呈现；独立标题以便 section 校验器切分）。Markdown 不得把
            # 其他 StrategicIssue 表述为用户本次决策议题。
            lines.append("# 查询上下文")
            lines.append("")
            lines.append(f"用户问题：{query_text}")
            lines.append("")
            lines.append("## 本体匹配锚点")
            lines.append("")
            for u in units_by_section.get("anchor", []):
                lines.append(u.to_markdown_line())
            lines.append("")
            continue
        title = SECTION_TITLES.get(section, f"## {section}")
        lines.append(title)
        lines.append("")
        units = units_by_section.get(section, [])
        if not units:
            lines.append("（无）")
        else:
            for u in units:
                short = (section == "gaps")
                lines.append(u.to_markdown_line(short=short))
        lines.append("")

    # Omission summary — counts only, not full lists (preserves budget)
    if omissions:
        om_by_role: dict[str, int] = {}
        for o in omissions:
            role = getattr(o, "role", "unknown") if hasattr(o, "role") else "unknown"
            om_by_role[role] = om_by_role.get(role, 0) + 1
        parts = [f"{k}×{v}" for k, v in sorted(om_by_role.items())]
        lines.append(f"### 省略 {len(omissions)} 项（{', '.join(parts)}）")
        lines.append("")

    lines.append("---")
    lines.append(
        f"pack_id: `{pack.pack_id}`  |  "
        f"ontology: {pack.ontology_release_id}  |  "
        f"renderer: {RENDERER_VERSION}"
    )
    lines.append("")
    return "\n".join(lines)


@dataclasses.dataclass(frozen=True)
class RenderedFactUnit:
    """Immutable fact unit. canonical_claim is the deterministic compiler output;
    the LLM may rewrite text but anchors/section/status are reassembled by program.
    NOTE: structural validation cannot detect in-line NL business judgements
    (e.g. '该风险已可忽略') — semantic_preservation stays not_proven."""
    member_id: str
    partition: str
    source_graphs: tuple[str, ...]
    canonical_claim: str
    display_name: str = ""
    confirmation_status: Optional[str] = None
    expected_section: str = ""

    @property
    def view_key(self) -> tuple[str, str]:
        return (self.member_id, self.partition)

    def to_markdown_line(self, short: bool = False) -> str:
        main_source = self.source_graphs[0] if self.source_graphs else "unknown"
        anchor = (f"[member:{self.member_id}][partition:{self.partition}]"
                  f"[source:{main_source}]")
        if short:
            status = f" [{self.confirmation_status}]" if self.confirmation_status else ""
            return f"- {self.display_name}{status} {anchor}"
        return f"- {self.canonical_claim} {anchor}"


@dataclasses.dataclass
class DecisionContextEntry:
    view_key: tuple[str, str]
    member_id: str
    name: str
    claim: str
    partition: str
    source_graphs: list[str]
    epistemic_status: Optional[str] = None
    role: Optional[str] = None
    scope: Optional[str] = None
    related_member_ids: Optional[list[str]] = None


@dataclasses.dataclass
class RenderOmission:
    member_id: str
    partition: str
    role: str
    tier: str
    reason: str
    incident_edges: int


class RenderBudgetTooSmall(Exception):
    """Raised when max_chars < mandatory_floor (dynamic)."""
    def __init__(self, requested_max_chars: int, minimum_required_chars: int):
        self.requested_max_chars = requested_max_chars
        self.minimum_required_chars = minimum_required_chars
        super().__init__(
            f"render_budget_too_small: requested {requested_max_chars} "
            f"< minimum {minimum_required_chars}"
        )
