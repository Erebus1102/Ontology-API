# tests/test_decision_context_compiler.py
import pytest
from tkos_runtime.application.decision_context_compiler import (
    build_type_index, build_type_index_from_members,
    build_name_index, build_name_index_from_members_test,
    classify_role, humanize_relation_text,
    compute_incident_edges, mandatory_floor, allocate_budget,
    DecisionContextCompiler, _build_units_by_section,
)
from tkos_runtime.application.context_renderer import render
from tkos_runtime.domain.models import ContextPack, ContextPackMember, AdmissionDecision, ScopeResolution, GraphStatement
from tkos_runtime.domain.render_units import RenderBudgetTooSmall, RenderedFactUnit, SECTION_ORDER

TKOS = "https://ontology.tokenking.ai/tkos#"
def _m(mid, partition, types):
    return ContextPackMember(id=mid, display_name=mid, scope=None, partition=partition,
        statements=[], source_graphs=[partition], confirmation_status=None,
        lifecycle=None, valid_from=None, valid_until=None, sources=[],
        admission=AdmissionDecision(True, partition), rdf_types=[TKOS+t for t in types])

def _pack(**overrides):
    defaults = dict(
        pack_id="test", schema_version="1.0",
        as_of="2026-08-12T00:00:00+08:00", query="q",
        purpose="decision_preparation", matched_root="urn:test:root",
        alternative_matches=[], scope_resolution=ScopeResolution([], [], "not_enforced", ""),
        current_facts=[], candidate_context=[], provenance_context=[],
        proof=[], derived_claims=[], reasoning_status="not_available",
        context_gaps=[], conflicts=[], omissions=[],
        contributing_graphs=[], admission_policy="",
        ontology_release_id="2.4.0", dataset_revision="a"*64,
        policy_version="read-admission/p0-v1", query_plan_version="bfs-2gram/v3-1",
    )
    defaults.update(overrides)
    return ContextPack(**defaults)

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

def test_build_type_index_from_pack_merges_across_partitions():
    # Exercises the pack-iteration path (current_facts/candidate_context/provenance_context/
    # context_gaps/derived_claims), not the flat-list helper.
    pack = _pack(
        current_facts=[_m("e1","graph-confirmed-enterprise",["Outcome"])],
        candidate_context=[_m("e1","graph-candidate-and-dispute",["Mission"])],
        provenance_context=[_m("e1","graph-decision-provenance",[])],
        context_gaps=[_m("g1","graph-context-gap",["ContextGap"])],
        derived_claims=[_m("d1","graph-confirmed-enterprise",["ProgressSnapshot"])],
    )
    ti = build_type_index(pack)
    assert ti["e1"] == {TKOS + "Outcome", TKOS + "Mission"}
    assert classify_role("e1", ti) == "outcome"
    assert ti["g1"] == {TKOS + "ContextGap"}
    assert ti["d1"] == {TKOS + "ProgressSnapshot"}


# ── Task 3: Budget ────────────────────────────────────────────────────────

def test_incident_excludes_governance_predicates():
    stmts = [GraphStatement("s", TKOS+"hasOutcome", "urn:x", "g"),
             GraphStatement("s", TKOS+"sourcedFrom", "urn:x", "g"),
             GraphStatement("s", TKOS+"confirmedBy", "urn:x", "g"),
             GraphStatement("s", TKOS+"assignmentHolder", "urn:x", "g")]
    m = ContextPackMember(id="x", display_name="x", scope=None,
        partition="g", statements=stmts, source_graphs=["g"],
        confirmation_status=None, lifecycle=None, valid_from=None, valid_until=None,
        sources=[], admission=AdmissionDecision(True,"g"), rdf_types=[])
    # Only hasOutcome should count (3 governance predicates excluded)
    assert compute_incident_edges(m, "urn:x") == 1


def _units_from_pack(pack):
    """Build units_by_section exactly as DecisionContextCompiler.compile does."""
    return _build_units_by_section(
        pack, build_type_index(pack), build_name_index(pack)[0],
    )


def test_mandatory_floor_includes_outcome_line_when_outcome_exists():
    pack = _pack(
        current_facts=[_m("o1", "graph-confirmed-enterprise", ["Outcome"])],
        candidate_context=[_m("c1", "graph-candidate-and-dispute", ["Risk"])],
        context_gaps=[_m("g1", "graph-candidate-and-dispute", ["ContextGap"]),
                      _m("g2", "graph-candidate-and-dispute", ["ContextGap"])],
    )
    floor = mandatory_floor(pack, _units_from_pack(pack))
    assert floor > 0
    # floor must exceed a gaps-only floor (accounts for an outcome line)
    gaps_only_pack = _pack(
        context_gaps=[_m("g1", "graph-candidate-and-dispute", ["ContextGap"]),
                      _m("g2", "graph-candidate-and-dispute", ["ContextGap"])],
    )
    gaps_only = mandatory_floor(gaps_only_pack, _units_from_pack(gaps_only_pack))
    assert floor > gaps_only


def test_allocate_raises_when_below_floor():
    pack = _pack(
        current_facts=[_m("o1", "graph-confirmed-enterprise", ["Outcome"])],
        context_gaps=[_m(f"g{i}", "graph-candidate-and-dispute", ["ContextGap"])
                      for i in range(8)],
    )
    with pytest.raises(RenderBudgetTooSmall) as ei:
        allocate_budget(_units_from_pack(pack), pack, max_chars=100,
                        type_index=build_type_index(pack))
    assert ei.value.minimum_required_chars > 100
    assert ei.value.requested_max_chars == 100


def test_allocate_budget_gaps_always_included():
    """Gaps are non-reclaimable — always included even if budget is tight."""
    pack = _pack(
        context_gaps=[_m("g1", "graph-candidate-and-dispute", ["ContextGap"])],
    )
    type_index = build_type_index(pack)
    unit = RenderedFactUnit(
        member_id="g1", partition="graph-candidate-and-dispute",
        source_graphs=("graph-candidate-and-dispute",),
        canonical_claim="缺口1", display_name="缺口1",
        expected_section="gaps",
    )
    units = {"gaps": [unit]}
    selected, omissions = allocate_budget(units, pack, max_chars=12000, type_index=type_index)
    assert len(selected.get("gaps", [])) == 1
    assert len(omissions) == 0


# ── Task 4: DecisionContextCompiler.compile ────────────────────────────────

def _fe_like_pack():
    """Minimal pack resembling a real FE-issue resolve output.

    P0: matched_root 必须指向 pack 内的真实成员（幽灵 root 现在是
    ContextRootMissingError，不再静默 fallback）。"""
    return _pack(
        current_facts=[
            _m("outcome-1", "graph-confirmed-enterprise", ["Outcome"]),
        ],
        candidate_context=[
            _m("risk-1", "graph-candidate-and-dispute", ["Risk"]),
            _m("issue-fe", "graph-candidate-and-dispute", ["StrategicIssue"]),
        ],
        provenance_context=[
            _m("src-1", "graph-decision-provenance", ["SourceRecord"]),
        ],
        context_gaps=[
            _m("gap-1", "graph-candidate-and-dispute", ["ContextGap"]),
            _m("gap-2", "graph-candidate-and-dispute", ["ContextGap"]),
        ],
        matched_root=TKOS + "issue-fe",
    )


def test_compile_produces_sections_and_decision_context():
    pack = _fe_like_pack()
    out = DecisionContextCompiler().compile(pack, max_chars=4000)
    # sections are subset of SECTION_ORDER + "issue" is already in SECTION_ORDER
    assert set(out.units_by_section).issubset(set(SECTION_ORDER))
    assert out.decision_context["compiler_version"] == "decision-context/v1"
    # all gaps present in decision_context.gaps
    assert len(out.decision_context["gaps"]) == len(pack.context_gaps)
    # issue entry present
    assert out.decision_context["issue"]["member_id"]
    # trace_only (SourceRecord) not in any section's units
    all_units = [u for sec in out.units_by_section.values() for u in sec]
    assert all(u.expected_section for u in all_units)
    source_record_units = [u for u in all_units if u.member_id == "src-1"]
    assert len(source_record_units) == 0  # trace_only excluded


def test_compile_epistemic_summary_no_b_type_phrases():
    pack = _fe_like_pack()
    out = DecisionContextCompiler().compile(pack, max_chars=4000)
    summary = out.decision_context["epistemic_summary"]
    # No (B)-type judgement phrases
    for banned in ("尚不", "最可能", "建议", "应该", "推荐"):
        assert banned not in summary, f"found banned phrase '{banned}' in: {summary}"


# ── Review round: mandatory views + exact budget (P1-1 / P1-2) ──────────────

def _root_pack(**overrides):
    """Pack with a real matched_root issue + gap + outcome + distractors."""
    defaults = dict(
        current_facts=[_m("outcome-1", "graph-confirmed-enterprise", ["Outcome"])],
        candidate_context=[
            _m("issue-root", "graph-candidate-and-dispute", ["StrategicIssue"]),
            _m("risk-1", "graph-candidate-and-dispute", ["Risk"]),
            _m("mission-x", "graph-candidate-and-dispute", ["Mission"]),
        ],
        context_gaps=[_m("gap-1", "graph-candidate-and-dispute", ["ContextGap"])],
        matched_root=TKOS + "issue-root",
    )
    defaults.update(overrides)
    return _pack(**defaults)


def test_mandatory_only_when_budget_equals_floor():
    """max_chars == mandatory_floor: only root issue + gaps + one outcome
    survive; every other unit is omitted; rendered content <= max_chars."""
    pack = _root_pack()
    units = _units_from_pack(pack)
    floor = mandatory_floor(pack, units)
    out = DecisionContextCompiler().compile(pack, max_chars=floor)
    # root issue present with full fields (never {} under budget)
    assert out.decision_context["issue"]["member_id"] == "issue-root"
    # all gaps present
    assert len(out.decision_context["gaps"]) == 1
    # at least one outcome survives
    assert "outcome-1" in {g["member_id"] for g in out.decision_context["outcomes"]}
    # everything else omitted (and listed in render_omissions)
    omitted = {o.member_id for o in out.omissions}
    assert {"risk-1", "mission-x"} <= omitted
    # hard budget: rendered content never exceeds max_chars
    content = render(pack, mode="deterministic", max_chars=floor)["rendered"]["content"]
    assert len(content) <= floor


def test_root_and_outcome_never_omitted_in_first_pass():
    """Regression (reviewer repro): tight budget must never drop the root
    issue or the outcome in the first (slot) pass."""
    pack = _root_pack(candidate_context=[
        _m("issue-root", "graph-candidate-and-dispute", ["StrategicIssue"]),
        _m("risk-1", "graph-candidate-and-dispute", ["Risk"]),
        _m("risk-2", "graph-candidate-and-dispute", ["Risk"]),
        _m("risk-3", "graph-candidate-and-dispute", ["Risk"]),
        _m("risk-4", "graph-candidate-and-dispute", ["Risk"]),
    ])
    floor = mandatory_floor(pack, _units_from_pack(pack))
    out = DecisionContextCompiler().compile(pack, max_chars=floor)
    assert out.decision_context["issue"]["member_id"] == "issue-root"
    assert out.decision_context["issue"]["matched_root"] == TKOS + "issue-root"
    assert len(out.decision_context["outcomes"]) >= 1
    # a budget below the floor is rejected up front (422 upstream)
    with pytest.raises(RenderBudgetTooSmall):
        DecisionContextCompiler().compile(pack, max_chars=floor - 1)


def test_long_root_issue_claim_survives_at_floor():
    """Boundary: long root-issue claim — floor accounts for the real line."""
    long_name = "根议题" + "长" * 400
    pack = _root_pack(candidate_context=[
        ContextPackMember(id="issue-root", display_name=long_name, scope=None,
            partition="graph-candidate-and-dispute", statements=[],
            source_graphs=["graph-candidate-and-dispute"],
            confirmation_status=None, lifecycle=None, valid_from=None, valid_until=None,
            sources=[], admission=AdmissionDecision(True, "graph-candidate-and-dispute"),
            rdf_types=[TKOS + "StrategicIssue"]),
        _m("risk-1", "graph-candidate-and-dispute", ["Risk"]),
    ])
    units = _units_from_pack(pack)
    floor = mandatory_floor(pack, units)
    with pytest.raises(RenderBudgetTooSmall):
        allocate_budget(units, pack, max_chars=floor - 1,
                        type_index=build_type_index(pack))
    out = DecisionContextCompiler().compile(pack, max_chars=floor)
    assert out.decision_context["issue"]["member_id"] == "issue-root"
    content = render(pack, mode="deterministic", max_chars=floor)["rendered"]["content"]
    assert len(content) <= floor
    assert long_name in content


def test_long_gap_id_survives_at_floor():
    """Boundary: long gap id — floor uses the real short-format line
    (complete three-part anchors), not an approximation."""
    long_gap = "gap-" + "x" * 300
    pack = _root_pack(context_gaps=[
        ContextPackMember(id=long_gap, display_name="长缺口", scope=None,
            partition="graph-candidate-and-dispute", statements=[],
            source_graphs=["graph-candidate-and-dispute"],
            confirmation_status=None, lifecycle=None, valid_from=None, valid_until=None,
            sources=[], admission=AdmissionDecision(True, "graph-candidate-and-dispute"),
            rdf_types=[TKOS + "ContextGap"]),
    ])
    units = _units_from_pack(pack)
    floor = mandatory_floor(pack, units)
    # old approximation reported floor=262 while real content was 1246 —
    # the exact floor must reject a budget below the real requirement
    with pytest.raises(RenderBudgetTooSmall):
        allocate_budget(units, pack, max_chars=floor - 1,
                        type_index=build_type_index(pack))
    out = DecisionContextCompiler().compile(pack, max_chars=floor)
    assert [g["member_id"] for g in out.decision_context["gaps"]] == [long_gap]
    content = render(pack, mode="deterministic", max_chars=floor)["rendered"]["content"]
    assert len(content) <= floor
    assert long_gap in content


def test_long_outcome_survives_at_floor():
    """Boundary: long outcome claim — mandatory outcome fits the budget."""
    long_claim = "成果" + "长" * 400
    pack = _root_pack(current_facts=[
        ContextPackMember(id="outcome-1", display_name=long_claim, scope=None,
            partition="graph-confirmed-enterprise", statements=[],
            source_graphs=["graph-confirmed-enterprise"],
            confirmation_status=None, lifecycle=None, valid_from=None, valid_until=None,
            sources=[], admission=AdmissionDecision(True, "graph-confirmed-enterprise"),
            rdf_types=[TKOS + "Outcome"]),
    ])
    units = _units_from_pack(pack)
    floor = mandatory_floor(pack, units)
    with pytest.raises(RenderBudgetTooSmall):
        allocate_budget(units, pack, max_chars=floor - 1,
                        type_index=build_type_index(pack))
    out = DecisionContextCompiler().compile(pack, max_chars=floor)
    assert "outcome-1" in {g["member_id"] for g in out.decision_context["outcomes"]}
    content = render(pack, mode="deterministic", max_chars=floor)["rendered"]["content"]
    assert len(content) <= floor
