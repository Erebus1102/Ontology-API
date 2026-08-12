# tests/test_runtime_models.py
from tkos_runtime.domain.models import (
    GraphStatement, RetrievedMember, ContextPackMember, AdmissionDecision,
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
