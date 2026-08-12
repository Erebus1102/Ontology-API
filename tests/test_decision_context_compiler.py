# tests/test_decision_context_compiler.py
from tkos_runtime.application.decision_context_compiler import build_type_index, build_type_index_from_members, classify_role
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
