# Decision Context Compiler v1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Decision Context Compiler layer that turns a Structured ContextPack into a decision-oriented reading view (structured `decision_context` + sectioned NL Markdown), without producing (B)-type judgements.

**Architecture:** `ContextPack → decision_context_compiler.compile() → (decision_context, units_by_section, omissions) → context_renderer.render() → {render_schema_version, rendered{content, grounding_status=structurally_validated, semantic_preservation=not_proven}, decision_context, metadata}`. A neutral `domain/render_units.py` holds all render data models to avoid import cycles. Role classification uses a cross-partition Admission-gated `type_index`. Validation is section-aware and keyed by `view_key=(member_id, partition)`.

**Tech Stack:** Python 3.9, rdflib, pydantic v2, FastAPI, pytest. (`fromisoformat` does not accept `Z` — always `.replace("Z","+00:00")`.)

**Spec:** `docs/superpowers/specs/2026-08-12-decision-context-compiler-design.md` (r4, approved). This plan folds in the three plan-level errata from the approval (marked ER1/ER2/ER3).

## Global Constraints

- **Grounding boundary:** deterministic compiler emits only (A)-type structured narrative (issue/outcome/progress/dependency/risk/gap/evidence regrouping + human-readable names). NEVER (B)-type judgements ("尚不足以承诺" etc.). `epistemic_summary` only reports computable status distribution.
- **Honesty boundary:** `grounding_status` is `structurally_validated` only (never `validated`); `semantic_preservation` is always `not_proven`. Structural validation cannot detect in-line NL business judgements — call this out in code comments.
- **Render Schema v2 migration:** response carries `render_schema_version: "context-render/2.0"`. `mode_used` enum is UNCHANGED: `deterministic | deterministic_fallback | llm_with_fallback | llm_required` (do NOT introduce `llm_polished`). Update OpenAPI/README/compat notes as part of the migration — do not "just change tests".
- **view_key primary key:** output + validation keyed by `view_key=(member_id, partition)`. Anchors are three-segment: `[member:<id>][partition:<graph>][source:<graph>]`. `member_id` may repeat across partitions; each `view_key` appears exactly once.
- **rdf_types (ER3):** `ContextPackMember.rdf_types: list[str]` is a backward-compatible OPTIONAL field — `field(default_factory=list)`. `dict_to_pack` reads missing → `[]`. `pack_to_dict` emits it. A Pack serialized before this field must still render (compat test).
- **type extraction:** two-phase, Admission-gated — `rdf_types` collected only from `accept=True` subject slices. `rdf_types` holds full class IRIs (not fragments). `rdf_types` on a view = that member's admitted types (shared across the member's views); cross-view merge happens in `type_index`.
- **RenderedFactUnit (ER2):** relocated to `domain/render_units.py` AND extended with `expected_section` field + `view_key` property. `context_renderer.py` re-exports `RenderedFactUnit` for import compatibility. The grounding *principle* is unchanged; the *structure* is extended.
- **mandatory_floor (ER1):** when the Pack contains ≥1 Outcome, `mandatory_floor` MUST include the length of at least one Outcome minimal line (else floor could pass but Outcome-non-reclaimable + max_chars fail).
- **Gap contract:** all Gaps enter `decision_context.gaps` (full); Markdown uses short format; Markdown NEVER shows "没有已知信息缺口" when gaps exist.
- **incident predicates:** `DECISION_INCIDENT_PREDICATES = frozenset(TRAVERSAL) - NON_DECISION_INCIDENT_PREDICATES`, where the exclusion set is exactly the 7 governance/provenance/assignment predicates (see Task 0). No ellipsis anywhere.
- **trace_only:** SourceRecord/Confirmation/ConfirmationEvent/RevisionEvent/RoleAssignment never independently occupy a body line (v1 no exceptions); DRI uses `responsibility` secondary role.
- **Derived:** enters `name_index` + `decision_context.derived`; NOT in Markdown narrative.
- **File isolation:** these 4 untracked files are SEPARATE work products — implementation commits MUST NOT include them: `data/instances/2026-08-12-strategy-distillation.trig`, `data/instances/2026-08-12-methodology-distillation.trig`, `data/instances/2026-08-12-business-model-fde-distillation.trig`, `docs/architecture/volcengine-deployment-design.md`. Use `git add` with explicit paths, never `git add -A`/`git add .`.
- **Acceptance commands (must pass before each task commit where relevant):**
  - `.venv/bin/python -m pytest tests/test_runtime_*.py tests/test_agent_harness.py -q`
  - `make test-fast`
- **LLM testing:** repeatable adversarial tests use a **Fake TextPolisher**; real DeepSeek is a final integration gate only and does NOT replace the Fake-polisher tests.

---

## File Structure

- **Create** `src/tkos_runtime/domain/render_units.py` — neutral render data models: `RenderedFactUnit` (moved+extended), `DecisionContextEntry`, `RenderOmission`, `CompiledDecisionContext`, `RenderBudgetTooSmall`, `NON_DECISION_INCIDENT_PREDICATES`, `DECISION_INCIDENT_PREDICATES`, `SECTION_ORDER`, role→section mapping.
- **Modify** `src/tkos_runtime/domain/models.py` — add `rdf_types` field to `ContextPackMember`.
- **Modify** `src/tkos_runtime/application/context_compiler.py` — two-pass Admission-gated `rdf_types` extraction.
- **Modify** `src/tkos_runtime/api/serializer.py` — `pack_to_dict` emits `rdf_types`; `dict_to_pack` reads with `[]` default.
- **Create** `src/tkos_runtime/application/decision_context_compiler.py` — `build_type_index`, `classify_role`, `build_name_index`, `humanize_claim`, `compute_incident_edges`, `allocate_budget`, `DecisionContextCompiler.compile()`.
- **Modify** `src/tkos_runtime/application/context_renderer.py` — re-export `RenderedFactUnit`; wire compiler; section-aware assembly; three-segment anchors; three-status output; `RenderBudgetTooSmall` → raise.
- **Modify** `src/tkos_runtime/api/render_models.py` — (if needed) keep `max_chars` field; response schema is built in renderer, not here.
- **Modify** `src/tkos_runtime/api/server.py` — map `RenderBudgetTooSmall` → HTTP 422 with `detail` envelope.
- **Create** `tests/test_render_units.py`.
- **Create** `tests/test_decision_context_compiler.py`.
- **Modify** `tests/test_runtime_renderer.py` — migrate to v2 schema, view-aware anchors, Fake TextPolisher section-aware adversarial tests.
- **Modify** `README.md` — Render Schema v2 compat note.

---

## Task 0: Neutral render models + `rdf_types` field (ER2, ER3)

**Files:**
- Create: `src/tkos_runtime/domain/render_units.py`
- Modify: `src/tkos_runtime/domain/models.py`
- Modify: `src/tkos_runtime/application/context_compiler.py`
- Modify: `src/tkos_runtime/api/serializer.py`
- Modify: `src/tkos_runtime/application/context_renderer.py` (re-export only)
- Test: `tests/test_render_units.py` (new), `tests/test_runtime_context_pack.py` (extend round-trip)

**Interfaces:**
- Produces: `RenderedFactUnit` (with `expected_section`, `view_key`), `RenderBudgetTooSmall`, `DECISION_INCIDENT_PREDICATES`; `ContextPackMember.rdf_types`.
- Consumes: `TRAVERSAL`, `TKOS` from `domain/query_plan.py`; `RDF_TYPE` constant pattern.

- [ ] **Step 1: Write failing test for render_units models**

`tests/test_render_units.py`:
```python
from tkos_runtime.domain.render_units import (
    RenderedFactUnit, RenderBudgetTooSmall, DECISION_INCIDENT_PREDICATES,
    NON_DECISION_INCIDENT_PREDICATES,
)
from tkos_runtime.domain.query_plan import TKOS

def test_rendered_fact_unit_view_key_derived():
    u = RenderedFactUnit(
        member_id="m1", partition="graph-candidate-and-dispute",
        source_graphs=("graph-candidate-and-dispute",),
        canonical_claim="x", expected_section="risks",
    )
    assert u.view_key == ("m1", "graph-candidate-and-dispute")

def test_incident_predicates_exclude_governance():
    excluded = {TKOS+p for p in (
        "sourcedFrom","confirmedBy","confirmsEntity","hasResponsibleAssignment",
        "assignmentHolder","assignmentRole","assignmentScope")}
    assert excluded == NON_DECISION_INCIDENT_PREDICATES
    assert excluded.isdisjoint(DECISION_INCIDENT_PREDICATES)
    assert (TKOS+"hasOutcome") in DECISION_INCIDENT_PREDICATES

def test_render_budget_exception_carries_fields():
    exc = RenderBudgetTooSmall(500, 1378)
    assert exc.requested_max_chars == 500
    assert exc.minimum_required_chars == 1378
```

- [ ] **Step 2: Run test — expect ImportError**

Run: `.venv/bin/python -m pytest tests/test_render_units.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Create `domain/render_units.py`**

```python
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
```

- [ ] **Step 4: Add `rdf_types` to `ContextPackMember`**

In `src/tkos_runtime/domain/models.py`, add `from dataclasses import dataclass, field` (field already? currently `from dataclasses import dataclass`). Change to `from dataclasses import dataclass, field`. Add as last field of `ContextPackMember`:
```python
    admission: AdmissionDecision
    rdf_types: list[str] = field(default_factory=list)
```

- [ ] **Step 5: Populate `rdf_types` in ContextCompiler (two-pass, Admission-gated)**

In `src/tkos_runtime/application/context_compiler.py`, replace the body of `compile`'s `for m in sorted(members, ...)` loop with a two-pass form. Add `RDF_TYPE` is not yet imported — reuse local. Replace the loop:
```python
        for m in sorted(members, key=lambda x: x.subject):
            parts = sorted(set(m.subject_by_partition) | set(m.incident_by_partition))
            # Pass 1: decide + collect admitted rdf:type (ER3 two-phase, Admission-gated)
            decisions: dict[str, AdmissionDecision] = {}
            member_types: set[str] = set()
            for part in parts:
                subj = m.subject_by_partition.get(part, [])
                d = self._policy.decide(part, subj, as_of)
                decisions[part] = d
                if d.accept:
                    for s in subj:
                        if s.predicate == RDF_TYPE:
                            member_types.add(s.object)
            # Pass 2: build views with full admitted type set
            for part in parts:
                d = decisions[part]
                if not d.accept:
                    omissions.append(Omission(_frag(m.subject), part, d.stage or "unknown", d.reason or ""))
                    continue
                subj = m.subject_by_partition.get(part, [])
                view = self._to_member(m, part, m.incident_by_partition.get(part, subj), subj, d, sorted(member_types))
                if part == "graph-confirmed-enterprise": current.append(view)
                elif part == "graph-candidate-and-dispute":
                    candidate.append(view)
                    if self._is_gap(subj): gaps.append(view)
                elif part == "graph-decision-provenance": provenance.append(view)
                elif part == "graph-derived-context": derived.append(view)
```
Add module constant near top: `RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"`.
Update `_to_member` signature to accept `rdf_types`:
```python
    def _to_member(self, m, part, incident, subj, decision, rdf_types) -> ContextPackMember:
```
and set `rdf_types=rdf_types,` in the returned `ContextPackMember(...)`.

- [ ] **Step 6: serializer round-trip**

In `src/tkos_runtime/api/serializer.py`:
- `pack_to_dict` already uses `dataclasses.asdict` — `rdf_types` is included automatically. No change.
- `dict_to_pack._member`: add `rdf_types=m.get("rdf_types", [])` to the `ContextPackMember(...)` call.

- [ ] **Step 7: re-export from context_renderer**

In `src/tkos_runtime/application/context_renderer.py`, replace the local `RenderedFactUnit` dataclass definition with:
```python
from tkos_runtime.domain.render_units import (
    RenderedFactUnit, RenderBudgetTooSmall, DECISION_INCIDENT_PREDICATES,
    SECTION_ORDER, SECTION_TITLES, ROLE_TO_SECTION, RENDERER_VERSION,
)
```
Remove the old local `RENDERER_VERSION` and `RenderedFactUnit` definitions. Keep `_compile_unit` returning `RenderedFactUnit` (now with `expected_section` filled later by the compiler; default "" acceptable for now). `from tkos_runtime.domain.render_models import RenderedFactUnit` re-export line is already satisfied by the import above (optional: add `__all__`).

- [ ] **Step 8: Run tests**

Run: `.venv/bin/python -m pytest tests/test_render_units.py tests/test_runtime_renderer.py tests/test_runtime_context_pack.py -q`
Expected: PASS. Add round-trip assertion to `tests/test_runtime_context_pack.py`:
```python
def test_rdf_types_roundtrip_and_default_empty():
    from tkos_runtime.api.serializer import pack_to_dict, dict_to_pack
    # existing resolver-built pack has rdf_types populated
    # (use the pack from an existing test fixture)
    d = pack_to_dict(pack)  # pack from existing test
    assert "rdf_types" in d["current_facts"][0] or d["current_facts"] == []
    # old pack without rdf_types still reconstructs
    legacy = {"pack_id":"x","dataset_revision":"a"*64,"ontology_release_id":"2.4.0",
              "current_facts":[{"id":"m1","partition":"graph-confirmed-enterprise"}]}
    rebuilt = dict_to_pack(legacy)
    assert rebuilt.current_facts[0].rdf_types == []
```
- [ ] **Step 9: Commit** — `git add src/tkos_runtime/domain/render_units.py src/tkos_runtime/domain/models.py src/tkos_runtime/application/context_compiler.py src/tkos_runtime/api/serializer.py src/tkos_runtime/application/context_renderer.py tests/test_render_units.py tests/test_runtime_context_pack.py` then commit `feat(render): neutral render_units module + rdf_types field (DCC task 0)`.

---

## Task 1: type_index + classify_role

**Files:**
- Create: `src/tkos_runtime/application/decision_context_compiler.py`
- Test: `tests/test_decision_context_compiler.py`

**Interfaces:**
- Produces: `build_type_index(pack) -> dict[str, set[str]]`, `ROLE_TABLE`, `classify_role(member_id, type_index) -> str`.
- Consumes: `ContextPackMember.rdf_types` (full IRIs).

- [ ] **Step 1: Failing test**
```python
# tests/test_decision_context_compiler.py
from tkos_runtime.application.decision_context_compiler import build_type_index, classify_role
from tkos_runtime.domain.models import ContextPackMember, AdmissionDecision

TKOS = "https://ontology.tokenking.ai/tkos#"
def _m(mid, partition, types):
    return ContextPackMember(id=mid, display_name=mid, scope=None, partition=partition,
        statements=[], source_graphs=[partition], confirmation_status=None,
        lifecycle=None, valid_from=None, valid_until=None, sources=[],
        admission=AdmissionDecision(True, partition), rdf_types=[TKOS+t for t in types])

def test_type_index_merges_across_views_and_classifies():
    pack_members = [_m("m1","graph-candidate-and-dispute",["Mission"]),
                    _m("m1","graph-decision-provenance",[])]  # prov view has no own type
    type_index = build_type_index_from_members(pack_members)
    assert type_index["m1"] == {TKOS+"Mission"}
    assert classify_role("m1", type_index) == "mission"

def test_provenance_view_inherits_role_without_own_type():
    # Candidate view carries type; Provenance view (empty rdf_types) still classifies via index
    members = [_m("x","graph-candidate-and-dispute",["Risk"]),
               _m("x","graph-decision-provenance",[])]
    ti = build_type_index_from_members(members)
    assert classify_role("x", ti) == "risk"

def test_rejected_slice_type_does_not_leak():
    # (Admission already filtered before pack build; here just confirm index only sees admitted)
    ti = build_type_index_from_members([_m("y","graph-confirmed-enterprise",["Outcome"])])
    assert classify_role("y", ti) == "outcome"

def test_other_when_no_match():
    ti = build_type_index_from_members([_m("z","graph-confirmed-enterprise",["LifecycleStatus"])])
    assert classify_role("z", ti) == "other"
```
(Helper `build_type_index_from_members(members)` is the test-facing alias of `build_type_index`; the production `build_type_index(pack)` iterates pack.current_facts+candidate_context+provenance_context+context_gaps+derived_claims.)

- [ ] **Step 2: Run — expect ImportError.**

- [ ] **Step 3: Implement**
```python
# src/tkos_runtime/application/decision_context_compiler.py
from __future__ import annotations
from typing import Any
from tkos_runtime.domain.models import ContextPack
from tkos_runtime.domain.render_units import RenderedFactUnit

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
```

- [ ] **Step 4: Run tests — PASS.**
- [ ] **Step 5: Commit** — `feat(dcc): type_index + classify_role (task 1)`.

---

## Task 2: build_name_index + humanize_claim

**Files:**
- Modify: `src/tkos_runtime/application/decision_context_compiler.py`
- Test: `tests/test_decision_context_compiler.py`

**Interfaces:**
- Produces: `build_name_index(pack) -> dict[str,str]`, `humanize_relation_text(claim, name_index) -> str`, `_real_display_name(member) -> str|None`.

- [ ] **Step 1: Failing test**
```python
from tkos_runtime.application.decision_context_compiler import build_name_index, humanize_relation_text

def _m2(mid, display, scope=None):
    return ContextPackMember(id=mid, display_name=display, scope=scope,
        partition="graph-candidate-and-dispute", statements=[], source_graphs=[],
        confirmation_status=None, lifecycle=None, valid_from=None, valid_until=None,
        sources=[], admission=AdmissionDecision(True,"graph-candidate-and-dispute"), rdf_types=[])

def test_name_index_priority_real_display_over_scope_over_fragment():
    # display_name == fragment => not real => fall to scope
    m = _m2("mission-fe-m2", "mission-fe-m2", scope="灯塔 Context 闭环")
    idx = build_name_index_from_members_test([m])
    assert idx["mission-fe-m2"] == "灯塔 Context 闭环"

def test_humanize_replaces_fragment_with_name():
    name_index = {"dependency-x": "共同交付依赖"}
    claim = "依赖：dependency-x；其余不变"
    assert humanize_relation_text(claim, name_index) == "依赖：共同交付依赖；其余不变"

def test_literal_object_unchanged():
    assert humanize_relation_text("范围：用户增长", {}) == "范围：用户增长"
```
(`build_name_index_from_members_test` = test alias; production `build_name_index(pack)` includes derived and applies cross-view priority.)

- [ ] **Step 2: Run — expect AttributeError.**

- [ ] **Step 3: Implement**
```python
PARTITION_PRIORITY = {"graph-confirmed-enterprise":0,"graph-candidate-and-dispute":1,
                      "graph-decision-provenance":2,"graph-derived-context":3}

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
```
Add test-alias `build_name_index_from_members_test(members)` that wraps the same logic over a bare list.

For `humanize_relation_text`, replace any token in the claim that exactly matches a `name_index` key (a fragment like `dependency-x`) with its name. Implement with a regex over `\b[a-zA-Z0-9-]+\b`-ish id tokens:
```python
import re
_ID_TOKEN = re.compile(r"(?<![\w])([a-z][a-z0-9-]*[a-z0-9])(?![\w])")
def humanize_relation_text(claim: str, name_index: dict[str,str]) -> str:
    def repl(mo):
        tok = mo.group(1)
        return name_index.get(tok, tok)
    return _ID_TOKEN.sub(repl, claim)
```
(Note: object literals like "用户增长" are CJK and won't match the ASCII id token regex — unchanged, as required.)

- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** — `feat(dcc): name_index + humanize (task 2)`.

---

## Task 3: Budget — mandatory_floor + 422 + two-pass + Gap short format + incident_edges (ER1)

**Files:**
- Modify: `src/tkos_runtime/application/decision_context_compiler.py`
- Test: `tests/test_decision_context_compiler.py`

**Interfaces:**
- Produces: `compute_incident_edges(member) -> int`, `mandatory_floor(pack, ...) -> int`, `allocate_budget(units_by_section, pack, max_chars) -> (selected, omissions)`; raises `RenderBudgetTooSmall`.

- [ ] **Step 1: Failing test**
```python
import pytest
from tkos_runtime.application.decision_context_compiler import compute_incident_edges, mandatory_floor, allocate_budget
from tkos_runtime.domain.render_units import RenderBudgetTooSmall

def test_incident_excludes_governance_predicates():
    from tkos_runtime.domain.models import GraphStatement
    from tkos_runtime.domain.query_plan import TKOS
    stmts = [GraphStatement("s", TKOS+"hasOutcome", "urn:x", "g"),
             GraphStatement("s", TKOS+"sourcedFrom", "urn:x", "g"),
             GraphStatement("s", TKOS+"confirmedBy", "urn:x", "g"),
             GraphStatement("s", TKOS+"assignmentHolder", "urn:x", "g")]
    # member whose object IRI is urn:x; count business incident only (1)
    m = ContextPackMember(id="x", display_name="x", scope=None,
        partition="g", statements=stmts, source_graphs=["g"],
        confirmation_status=None, lifecycle=None, valid_from=None, valid_until=None,
        sources=[], admission=AdmissionDecision(True,"g"), rdf_types=[])
    assert compute_incident_edges(m, "urn:x") == 1

def test_budget_too_small_raises():
    pack = _pack_with_outcome_and_gaps(n_gaps=8)
    with pytest.raises(RenderBudgetTooSmall) as ei:
        mandatory_floor(pack)  # compute floor
    # floor itself doesn't raise; allocate_budget(pack, max_chars=100) does
```
Refine: `mandatory_floor` returns int (does not raise); `allocate_budget(..., max_chars)` raises `RenderBudgetTooSmall` when `max_chars < mandatory_floor(...)`.

Corrected test:
```python
def test_mandatory_floor_includes_outcome_line_when_outcome_exists():
    pack = _pack_with_outcome_and_gaps(n_gaps=2)
    floor = mandatory_floor(pack)
    assert floor > 0
    # floor must exceed header+gaps-only floor (i.e. accounts for an outcome line)
    gaps_only = mandatory_floor(_pack_with_gaps_only(n_gaps=2))
    assert floor > gaps_only

def test_allocate_raises_when_below_floor():
    pack = _pack_with_outcome_and_gaps(n_gaps=8)
    with pytest.raises(RenderBudgetTooSmall) as ei:
        allocate_budget(pack, max_chars=100)
    assert ei.value.minimum_required_chars > 100
    assert ei.value.requested_max_chars == 100
```
(`_pack_with_outcome_and_gaps` / `_pack_with_gaps_only` are test builders using existing helpers.)

- [ ] **Step 2: Run — expect failures.**

- [ ] **Step 3: Implement**
```python
from tkos_runtime.domain.render_units import (
    RenderOmission, RenderBudgetTooSmall, DECISION_INCIDENT_PREDICATES,
)

def compute_incident_edges(member, full_iri: str) -> int:
    seen = set()
    for s in member.statements:
        if s.object == full_iri and s.predicate in DECISION_INCIDENT_PREDICATES:
            seen.add((s.subject, s.predicate))
    return len(seen)

# slot ratios of usable_budget
SLOT_RATIO = {"issue":0.10,"outcomes":0.25,"risks":0.25,"gaps":0.25,"evidence":0.10,"secondary":0.05}

def _gap_short_len(name: str) -> int:
    # "- <name> [Candidate] [member:..][partition:..][source:..]" approx
    return len(name) + 60

def mandatory_floor(pack) -> int:
    header = 200  # title + epistemic summary + section headers + footer reserve
    floor = header
    for g in pack.context_gaps:
        floor += _gap_short_len(g.display_name or g.id)
    # ER1: when an Outcome exists, include one outcome minimal line
    if any(classify_role(m.id, build_type_index(pack)) == "outcome"
           for m in (*pack.current_facts, *pack.candidate_context)):
        floor += 80
    return floor

def allocate_budget(pack, max_chars: int):
    floor = mandatory_floor(pack)
    if max_chars < floor:
        raise RenderBudgetTooSmall(max_chars, floor)
    # Returns (selected: dict[section,list[unit]], omissions: list[RenderOmission])
    # Two-pass precise assembly:
    #   pass 1: greedily fill slots by tier then incident_edges; record omissions
    #   pass 2: recompute fixed_text len, reclaim from lowest priority if over
    # Non-reclaimable: root issue, each gap short format, (>=1 outcome if any).
    ...  # full body per spec §6.2-6.4; see implementation notes below
```
Implementation notes for `allocate_budget` body (must be filled, no placeholder in actual plan execution):
1. Build `units_by_section` from compile (Task 4) — but budget is called by compile. To avoid a chicken-egg, `allocate_budget` takes the already-compiled `units_by_section: dict[str, list[RenderedFactUnit]]` plus `pack`. Adjust signature: `allocate_budget(units_by_section, pack, max_chars)`.
2. Compute `fixed_text` length by rendering the empty scaffold (all section titles + footer + epistemic summary).
3. `usable = max_chars - fixed_text`.
4. For each section in SECTION_ORDER, `slot = usable * SLOT_RATIO[section]` (map outcome/progress→outcomes slot, risk/dependency→risks slot, evidence→evidence, gaps→gaps, secondary→secondary, issue→issue).
5. Order each section's units by `(role_tier, -incident_edges, member_id)`. Greedy-add full lines until slot exhausted; gaps always added in SHORT format first (non-reclaimable). Overflow → `RenderOmission(reason="max_chars_exceeded")`.
6. Borrowing: if gaps slot overflows, consume unused evidence→risks→outcomes budget; guarantee every gap short format.
7. Pass 2: assemble final text length; if `> max_chars`, reclaim optional (lowest tier) units, never root issue / gaps short / first outcome (if outcomes exist).

- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** — `feat(dcc): budget floor + 422 + two-pass (task 3)`.

---

## Task 4: DecisionContextCompiler.compile — assemble decision_context + sectioned units

**Files:**
- Modify: `src/tkos_runtime/application/decision_context_compiler.py`
- Test: `tests/test_decision_context_compiler.py`

**Interfaces:**
- Produces: `DecisionContextCompiler.compile(pack, max_chars) -> CompiledDecisionContext` with `.decision_context: dict`, `.units_by_section: dict[str, list[RenderedFactUnit]]`, `.omissions: list[RenderOmission]`, `.warnings: list[str]`.
- Consumes: Tasks 1-3.

- [ ] **Step 1: Failing test**
```python
from tkos_runtime.application.decision_context_compiler import DecisionContextCompiler

def test_compile_produces_sections_and_decision_context():
    pack = _fe_like_pack()  # has issue, outcome, risk, 2 gaps, a confirmation(trace_only)
    out = DecisionContextCompiler().compile(pack, max_chars=4000)
    assert set(out.units_by_section).issubset(set(SECTION_ORDER)) | {"issue"}
    assert out.decision_context["compiler_version"] == "decision-context/v1"
    # all gaps present in decision_context.gaps
    assert len(out.decision_context["gaps"]) == len(pack.context_gaps)
    # trace_only not in any section's units
    all_units = [u for sec in out.units_by_section.values() for u in sec]
    assert all(u.expected_section for u in all_units)
    # issue entry is full member
    assert out.decision_context["issue"]["member_id"]
```

- [ ] **Step 2: Run — fail.**

- [ ] **Step 3: Implement** `DecisionContextCompiler.compile`:
1. `type_index = build_type_index(pack)`; `name_index = build_name_index(pack)` (capture warnings).
2. For each member view (current+candidate+provenance+gap), `role = classify_role(member.id, type_index)`; `section = ROLE_TO_SECTION.get(role)`. trace_only roles → not placed in units (recorded as omission only unless `responsibility`). `other` → secondary bucket or omission.
3. Build `RenderedFactUnit` per placed view: `canonical_claim = humanize_relation_text(_compile_claim(member, name_index), name_index)`; `expected_section = section`; partition/source_graphs from member.
4. `units_by_section[section].append(unit)`.
5. `selected, omissions = allocate_budget(units_by_section, pack, max_chars)`.
6. Build `decision_context` dict: issue (full entry from matched_root member or first issue-role), outcomes/progress/dependencies/risks/evidence/gaps/decisions arrays of `DecisionContextEntry`-as-dict (each with `view_key`, `member_id`, `name`, `claim`, `partition`, `source_graphs`, `epistemic_status`), `secondary` (with role), `derived` (from derived_claims), `render_omissions`, `warnings`.
7. epistemic_summary counts by view (Gap is Candidate subset): `"候选视图 N 项（其中信息缺口 M 项），溯源视图 K 项。..."` — generated from counts, no (B)-type phrasing.

- [ ] **Step 4: Run — PASS.**
- [ ] **Step 5: Commit** — `feat(dcc): compile() assembles decision_context + sections (task 4)`.

---

## Task 5: render() wiring — section template, view-aware anchors, three-status, Render Schema v2

**Files:**
- Modify: `src/tkos_runtime/application/context_renderer.py`
- Modify: `tests/test_runtime_renderer.py`

**Interfaces:**
- Produces: updated `render(pack, ..., pack_origin=...) -> dict` returning `render_schema_version`, three-status `rendered`, `decision_context`, `metadata`.
- Consumes: `DecisionContextCompiler`, `RenderBudgetTooSmall`.

- [ ] **Step 1: Update existing renderer tests to v2 schema** (these will fail until impl). In `tests/test_runtime_renderer.py`:
  - Replace assertions `grounding_status == "validated"` → `== "structurally_validated"`.
  - Replace `== "unverified_input"` checks → assert `metadata.pack_origin == "client_supplied"` instead.
  - Assert `render_schema_version == "context-render/2.0"` and `semantic_preservation == "not_proven"` in the deterministic-mode test.
  - Anchor assertions: update `[member:m1]` → `[member:m1][partition:...][source:...]` where relevant.
  - Add: `assert result["decision_context"]["compiler_version"] == "decision-context/v1"`.

- [ ] **Step 2: Run — expect failures (schema mismatch).**

- [ ] **Step 3: Rewrite `render()`**
```python
def render(pack, *, mode="deterministic", format="markdown", max_chars=12000,
           language="zh-CN", polisher=None, pack_origin="server_resolved") -> dict:
    compiled = DecisionContextCompiler().compile(pack, max_chars=max_chars)  # may raise RenderBudgetTooSmall
    content = _assemble_sectioned_markdown(compiled, pack)
    warnings = list(compiled.warnings)
    mode_used = mode
    grounding = "structurally_validated"
    if mode in ("llm_with_fallback", "llm_required"):
        if polisher is None:
            if mode == "llm_required":
                raise ValueError("LLM mode requires a TextPolisher instance.")
            warnings.append("LLM mode requires a TextPolisher instance; using deterministic renderer.")
            mode_used = "deterministic_fallback"
        else:
            try:
                polished = polisher.polish(content, language)
                valid, vw = _validate_llm_output(compiled, polished, deterministic_text=content)
                warnings.extend(vw)
                if valid:
                    content = polished
                elif mode == "llm_required":
                    raise ValueError(f"LLM output validation failed: {'; '.join(vw)}")
                else:
                    warnings.append("LLM output failed validation; using deterministic renderer.")
                    mode_used = "deterministic_fallback"
            except Exception as exc:
                if mode == "llm_required":
                    raise
                warnings.append(f"LLM unavailable ({exc}); using deterministic renderer.")
                mode_used = "deterministic_fallback"
    return {
        "render_schema_version": RENDERER_VERSION,  # context-render/2.0
        "rendered": {
            "format": format, "content": content,
            "grounding_status": grounding,
            "semantic_preservation": "not_proven",
            "rendering_status": "completed",
            "mode_requested": mode, "mode_used": mode_used,
            "warnings": warnings,
        },
        "decision_context": compiled.decision_context,
        "metadata": {
            "context_pack_id": pack.pack_id,
            "dataset_revision": pack.dataset_revision,
            "ontology_release_id": pack.ontology_release_id,
            "renderer_version": RENDERER_VERSION,
            "pack_origin": pack_origin,
        },
    }
```
`_assemble_sectioned_markdown(compiled, pack)` renders title+issue anchor+epistemic_summary+each section (using `unit.to_markdown_line(short=(section=="gaps"))`)+omission count lines+footer.

- [ ] **Step 4: Run renderer tests — PASS.**
- [ ] **Step 5: Commit** — `feat(render): wire DCC, view-aware anchors, Render Schema v2 (task 5)`.

---

## Task 6: Section-aware validator (eight checks, view_key primary key)

**Files:**
- Modify: `src/tkos_runtime/application/context_renderer.py`
- Test: `tests/test_runtime_renderer.py` (Fake TextPolisher adversarial tests)

**Interfaces:**
- Produces: `_validate_llm_output(compiled, polished, deterministic_text) -> (bool, list[str])` keyed by view_key.

- [ ] **Step 1: Failing adversarial tests with a Fake TextPolisher**
```python
class _FakePolisher:
    def __init__(self, transform): self.transform = transform
    def polish(self, text, language): return self.transform(text)

def test_llm_moves_risk_into_outcomes_section_falls_back():
    # fake polisher swaps two section bodies
    ... assert mode_used == "deterministic_fallback"

def test_llm_keeps_structure_passes():
    ... assert mode_used == "llm_with_fallback"  # (mode requested) and content == polished

def test_llm_drops_member_falls_back(): ...
def test_llm_adds_phantom_member_falls_back(): ...
def test_llm_changes_partition_anchor_falls_back(): ...
```
Also: `test_inline_nl_judgement_is_not_detected_but_marked_not_proven` — a fake polisher that appends "公司应暂停灯塔项目" to a line; assert validation PASSES (structural) but `semantic_preservation == "not_proven"` (documents the boundary).

- [ ] **Step 2: Run — expect failures.**

- [ ] **Step 3: Implement section-aware validation**
```python
def _split_sections(polished: str) -> dict[str, str]:
    # split by SECTION_TITLES headers into {section: body_text}
    ...

def _validate_llm_output(compiled, polished, deterministic_text=""):
    warnings = []
    selected = {u.view_key: u for sec in compiled.units_by_section.values() for u in sec}
    sections = _split_sections(polished)
    # 5. section set + order unchanged
    if list(sections.keys()) != [s for s in SECTION_ORDER if s in sections]:
        warnings.append("section set/order changed")
    for vk, unit in selected.items():
        # locate which section body contains this member anchor
        anchor_member = f"[member:{unit.member_id}]"
        anchor_partition = f"[partition:{unit.partition}]"
        found_section = next((s for s,b in sections.items() if anchor_member in b), None)
        # 1. exact once per view_key
        occurrences = sum(1 for b in sections.values() if anchor_member in b and anchor_partition in b)
        if occurrences != 1:
            warnings.append(f"view_key {vk} appears {occurrences} times (expected 1)")
        # 2. in expected section
        if found_section != unit.expected_section:
            warnings.append(f"view_key {vk} in section {found_section}, expected {unit.expected_section}")
        # 3. partition anchor preserved
        if anchor_partition not in sections.get(found_section, ""):
            warnings.append(f"partition anchor changed for {vk}")
    # 6/7. phantom / missing handled by occurrences check above
    # 8. numbers/URIs baseline = full deterministic text (unchanged from current impl)
    ...  # reuse existing _extract_numbers/_extract_uris vs deterministic_text
    # 4. status tags preserved
    ...
    return (len(warnings) == 0), warnings
```

- [ ] **Step 4: Run — PASS (incl. inline-NL test documenting not_proven boundary).**
- [ ] **Step 5: Commit** — `feat(render): section-aware view_key validator (task 6)`.

---

## Task 7: Server 422 mapping + README v2 note + full e2e

**Files:**
- Modify: `src/tkos_runtime/api/server.py`
- Modify: `README.md`
- Modify: `tests/test_runtime_renderer.py` (e2e assertions)
- Test: real-FE-issue deterministic + Fake-polisher e2e.

- [ ] **Step 1: Wire RenderBudgetTooSmall in server.py**
```python
from tkos_runtime.domain.render_units import RenderBudgetTooSmall
# in resolve_and_render:
        except RenderBudgetTooSmall as exc:
            raise HTTPException(status_code=422, detail={
                "code": "render_budget_too_small",
                "requested_max_chars": exc.requested_max_chars,
                "minimum_required_chars": exc.minimum_required_chars,
            }) from exc
```

- [ ] **Step 2: 422 envelope test**
```python
def test_render_budget_too_small_422_envelope():
    client = TestClient(create_app())
    resp = client.post("/v1/context-packs:render", json={
        "resolve_request": {...FE issue...},
        "render_options": {"mode":"deterministic","max_chars":100}})
    assert resp.status_code == 422
    d = resp.json()["detail"]
    assert d["code"] == "render_budget_too_small"
    assert d["requested_max_chars"] == 100
    assert d["minimum_required_chars"] > 100
```

- [ ] **Step 3: Real-FE e2e — all 18 spec §12 assertions** as a single test (or parametrized) using the resolver + deterministic + a Fake-polisher that returns content unchanged (passes) and one that swaps sections (falls back). Assert: root issue in body with three-segment anchor; an Outcome present; all 8 gaps in decision_context.gaps; no "没有已知信息缺口"; risk-product1-lighthouse-resource-conflict present; no independent SourceRecord/Confirmation/RoleAssignment body line; len(content) <= max_chars; omissions only in render_omissions; markdown only slot counts; section-swap → fallback; same-id Candidate/Provenance views keep partition/source/status and each view_key once; deterministic vs Fake-polisher selected view_key set/count/section identical; epistemic_summary has no (B)-type phrases; grounding_status==structurally_validated; semantic_preservation==not_proven; mode_used never llm_polished; incident_edges governance-excluded.

- [ ] **Step 4: README v2 compat note** — add a short section: "Render Schema v2 (context-render/2.0): grounding_status now structurally_validated (was validated/unverified_input; input trust now in metadata.pack_origin); semantic_preservation added (always not_proven); mode_used enum unchanged." Update any example response.

- [ ] **Step 5: Run full acceptance**
```
.venv/bin/python -m pytest tests/test_runtime_*.py tests/test_agent_harness.py -q
make test-fast
```
Expected: all green.

- [ ] **Step 6: Commit** — `feat(render): server 422 mapping + README v2 + e2e (task 7)`.

---

## Notes for the executor

- `git add` explicit paths only — never `-A`/`.` (4 isolated files must stay out).
- Python 3.9: `fromisoformat` needs `.replace("Z","+00:00")`; `dict[str,str]` annotations OK because `from __future__ import annotations` is present in all touched modules.
- The `_compile_claim(member, name_index)` helper (Task 4) is the existing `_compile_unit` claim logic moved into the compiler and humanized — reuse `_PREDICATE_LABELS` (move it to the compiler or import).
- If `allocate_budget` two-pass proves ambiguous during execution, the acceptance gate (len(content) <= max_chars, all gaps present, no "no gaps" string) is the source of truth — satisfy the gate.
