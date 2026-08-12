# src/tkos_runtime/domain/render_units.py
"""Neutral render data models — imported by both the decision-context compiler
and the renderer, to avoid import cycles. Grounding principle: structural
validation only; NL semantic preservation is not_proven (see comments)."""
from __future__ import annotations
import dataclasses
from typing import Any, Optional

from tkos_runtime.domain.query_plan import TRAVERSAL, TKOS

RENDERER_VERSION = "context-render/2.0"

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
SECTION_ORDER = (
    "issue", "outcomes", "progress", "dependencies", "risks",
    "gaps", "decisions",
)
SECTION_TITLES = {
    "issue": "# 决策议题",
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
