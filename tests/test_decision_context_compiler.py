# tests/test_decision_context_compiler.py
import pytest
from tkos_runtime.application.decision_context_compiler import (
    build_type_index, build_type_index_from_members,
    build_name_index, build_name_index_from_members_test,
    classify_role, humanize_relation_text,
    compute_incident_edges, mandatory_floor, allocate_budget,
    DecisionContextCompiler,
)
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
        policy_version="read-admission/p0-v1", query_plan_version="bfs-2gram/p0-v1",
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


def test_mandatory_floor_includes_outcome_line_when_outcome_exists():
    pack = _pack(
        current_facts=[_m("o1", "graph-confirmed-enterprise", ["Outcome"])],
        candidate_context=[_m("c1", "graph-candidate-and-dispute", ["Risk"])],
        context_gaps=[_m("g1", "graph-candidate-and-dispute", ["ContextGap"]),
                      _m("g2", "graph-candidate-and-dispute", ["ContextGap"])],
    )
    floor = mandatory_floor(pack)
    assert floor > 0
    # floor must exceed a gaps-only floor (accounts for an outcome line)
    gaps_only_pack = _pack(
        context_gaps=[_m("g1", "graph-candidate-and-dispute", ["ContextGap"]),
                      _m("g2", "graph-candidate-and-dispute", ["ContextGap"])],
    )
    gaps_only = mandatory_floor(gaps_only_pack)
    assert floor > gaps_only


def test_allocate_raises_when_below_floor():
    pack = _pack(
        current_facts=[_m("o1", "graph-confirmed-enterprise", ["Outcome"])],
        context_gaps=[_m(f"g{i}", "graph-candidate-and-dispute", ["ContextGap"])
                      for i in range(8)],
    )
    with pytest.raises(RenderBudgetTooSmall) as ei:
        allocate_budget({}, pack, max_chars=100)
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
    """Minimal pack resembling a real FE-issue resolve output."""
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
