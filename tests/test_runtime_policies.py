# tests/test_runtime_policies.py
from datetime import datetime
import pytest
from tkos_runtime.domain.models import GraphStatement
from tkos_runtime.domain.policies import AdmissionPolicy

AS_OF = datetime.fromisoformat("2026-08-11T00:00:00+00:00")
REG = {"graph-confirmed-enterprise","graph-candidate-and-dispute","graph-decision-provenance","graph-derived-context","graph-sensitive-persona"}
def stmt(s,p,o,g): return GraphStatement(s,p,o,g)

def test_allowed_is_purpose_intersect_registered_minus_restricted():
    pol = AdmissionPolicy()
    gs = set(pol.allowed_graphs("decision_preparation", REG, {"graph-sensitive-persona"}))
    assert gs == {"graph-confirmed-enterprise","graph-candidate-and-dispute","graph-decision-provenance","graph-derived-context"}

def test_removing_candidate_from_registry_removes_it():
    pol = AdmissionPolicy()
    gs = set(pol.allowed_graphs("decision_preparation", REG - {"graph-candidate-and-dispute"}, set()))
    assert "graph-candidate-and-dispute" not in gs

def test_new_unknown_partition_not_auto_authorized():
    pol = AdmissionPolicy()
    gs = set(pol.allowed_graphs("decision_preparation", REG | {"graph-new-x"}, set()))
    assert "graph-new-x" not in gs  # purpose_allowed 不含它

def test_new_partition_authorized_only_when_in_both_purpose_and_registry():
    pol = AdmissionPolicy(purpose_allowed={"decision_preparation": ["graph-confirmed-enterprise","graph-new-x"]})
    gs = set(pol.allowed_graphs("decision_preparation", REG | {"graph-new-x"}, set()))
    assert "graph-new-x" in gs

def test_unknown_purpose_raises():
    with pytest.raises(ValueError):
        AdmissionPolicy().allowed_graphs("typo", REG, set())

def test_confirmed_requires_confirmed_and_valid():
    d = AdmissionPolicy().decide("graph-confirmed-enterprise", [
        stmt("x","https://ontology.tokenking.ai/tkos#hasConfirmationStatus","Confirmed","graph-confirmed-enterprise"),
        stmt("x","https://ontology.tokenking.ai/tkos#validFrom","2026-08-01T00:00:00+00:00","graph-confirmed-enterprise")], AS_OF)
    assert d.accept

def test_candidate_relation_only_effective_status():
    d = AdmissionPolicy().decide("graph-candidate-and-dispute", [
        stmt("m","https://ontology.tokenking.ai/tkos#supportedByEvidence","ec","graph-candidate-and-dispute")], AS_OF)
    assert d.accept

def test_candidate_archived_omitted_with_stage_reason():
    d = AdmissionPolicy().decide("graph-candidate-and-dispute", [
        stmt("x","https://ontology.tokenking.ai/tkos#hasConfirmationStatus","Archived","graph-candidate-and-dispute")], AS_OF)
    assert not d.accept and d.stage == "confirmation" and d.reason

def test_expired_valid_time():
    d = AdmissionPolicy().decide("graph-confirmed-enterprise", [
        stmt("x","https://ontology.tokenking.ai/tkos#hasConfirmationStatus","Confirmed","graph-confirmed-enterprise"),
        stmt("x","https://ontology.tokenking.ai/tkos#validFrom","2026-07-01T00:00:00+00:00","graph-confirmed-enterprise"),
        stmt("x","https://ontology.tokenking.ai/tkos#validUntil","2026-08-01T00:00:00+00:00","graph-confirmed-enterprise")], AS_OF)
    assert not d.accept and d.stage == "valid_time"

def test_provenance_no_status_required():
    assert AdmissionPolicy().decide("graph-decision-provenance", [], AS_OF).accept
