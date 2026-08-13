# tests/test_runtime_models.py
from tkos_runtime.domain.models import (
    AmbiguousMatchError, ContextPack, GraphStatement, RetrievedMember,
    ContextPackMember, AdmissionDecision, IntentAssessment, IntentFacets,
    LineageProof, NoMatchError,
)

def test_retrieved_member_subject_and_incident_split():
    subj = GraphStatement("a","tkos:hasConfirmationStatus","Confirmed","graph-confirmed-enterprise")
    inc = GraphStatement("b","tkos:assignmentScope","a","graph-confirmed-enterprise")
    m = RetrievedMember("a", {"graph-confirmed-enterprise":[subj]}, {"graph-confirmed-enterprise":[subj,inc]})
    assert m.source_graphs == ["graph-confirmed-enterprise"]

def test_context_pack_member_has_scope():
    mem = ContextPackMember(id="x", display_name="x", scope="边界", partition="graph-confirmed-enterprise",
        statements=[], source_graphs=["graph-confirmed-enterprise"], confirmation_status="Confirmed",
        lifecycle=None, valid_from=None, valid_until=None, sources=[], admission=AdmissionDecision(True,"graph-confirmed-enterprise"))
    assert mem.scope == "边界"

def test_no_match_error_is_exception():
    assert issubclass(NoMatchError, Exception)


# ── P1：IntentFacets / candidates / AmbiguousMatchError ─────────────────

def test_no_match_error_candidates_default_empty():
    err = NoMatchError("知识库未覆盖")
    assert err.candidates == []


def test_ambiguous_match_error_carries_candidates():
    cands = [(11, "a-node", "A Node"), (11, "b-node", "B Node")]
    err = AmbiguousMatchError("歧义", candidates=cands)
    assert err.candidates == cands
    assert err.candidates is not cands  # 防御拷贝


def test_intent_assessment_positional_backcompat():
    """位置构造（root, alternatives）不破坏——新字段有默认值。"""
    ia = IntentAssessment("urn:root", [(1, "x", "X")])
    assert ia.root == "urn:root"
    assert ia.intent_facets is None


def test_intent_facets_dataclass_fields():
    f = IntentFacets(entity="灯塔", requested_role="risk", operation="list")
    assert f.entity == "灯塔"
    assert f.requested_role == "risk"
    assert f.operation == "list"


def test_context_pack_intent_facets_default_none():
    """ContextPack 末尾新增字段——既有全关键字构造安全。"""
    pack = ContextPack(
        pack_id="p", schema_version="1.0", as_of="t", query="q",
        purpose="decision_preparation", matched_root="urn:r",
        alternative_matches=[], scope_resolution=None, current_facts=[],
        candidate_context=[], provenance_context=[], proof=[],
        derived_claims=[], reasoning_status="not_available",
        context_gaps=[], conflicts=[], omissions=[],
        contributing_graphs=[], admission_policy="",
        ontology_release_id="2.4.0", dataset_revision="a" * 64,
        policy_version="v", query_plan_version="v",
    )
    assert pack.intent_facets is None
