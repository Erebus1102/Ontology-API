# tests/test_decision_context_compiler.py
from tkos_runtime.application.decision_context_compiler import build_type_index, build_type_index_from_members, build_name_index, build_name_index_from_members_test, classify_role, humanize_relation_text
from tkos_runtime.domain.models import ContextPack, ContextPackMember, AdmissionDecision, ScopeResolution

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
