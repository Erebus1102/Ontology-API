# tests/test_runtime_compiler.py
from datetime import datetime
from tkos_runtime.domain.models import GraphStatement, RetrievedMember, IntentAssessment, ScopeResolution
from tkos_runtime.domain.policies import AdmissionPolicy
from tkos_runtime.application.context_compiler import ContextCompiler

AS_OF = datetime.fromisoformat("2026-08-11T00:00:00+00:00")
TKOS = "https://ontology.tokenking.ai/tkos#"
def stmt(s,p,o,g): return GraphStatement(s,p,o,g)
MG = TKOS+"mission-growth"

def dual_member():
    return RetrievedMember(MG,
        subject_by_partition={"graph-confirmed-enterprise":[
            stmt(MG,TKOS+"hasConfirmationStatus","Confirmed","graph-confirmed-enterprise"),
            stmt(MG,TKOS+"validFrom","2026-08-01T00:00:00+00:00","graph-confirmed-enterprise"),
            stmt(MG,TKOS+"displayName","增长任务","graph-confirmed-enterprise"),
            stmt(MG,TKOS+"scopeDescription","边界","graph-confirmed-enterprise")]},
        incident_by_partition={"graph-confirmed-enterprise":[
            stmt(MG,TKOS+"hasConfirmationStatus","Confirmed","graph-confirmed-enterprise"),
            stmt(MG,TKOS+"supportedByEvidence",TKOS+"evidence-current","graph-confirmed-enterprise")],
            "graph-candidate-and-dispute":[
            stmt(MG,TKOS+"supportedByEvidence",TKOS+"evidence-candidate","graph-candidate-and-dispute")]})

def scope(): return ScopeResolution([],[],"not_enforced","instance_organization_assignment_incomplete")
def meta(): return {"ontology_release_id":"2.4.0","dataset_revision":"x"*64}
def compiler(): return ContextCompiler(store=None, policy=AdmissionPolicy())

def test_candidate_edge_only_in_candidate_context():
    pack = compiler().compile([dual_member()], IntentAssessment(MG,[]), scope(), meta(), AS_OF, "q", "decision_preparation")
    cur = [m for m in pack.current_facts if m.id == "mission-growth"]
    cand = [m for m in pack.candidate_context if m.id == "mission-growth"]
    assert cur and all(s.source_graph == "graph-confirmed-enterprise" for m in cur for s in m.statements)
    # 隔离对象是 candidate 边，而非所有 supportedByEvidence（confirmed 图本就有 evidence-current）
    assert not any(s.predicate.endswith("supportedByEvidence") and s.object.endswith("evidence-candidate")
                   for m in cur for s in m.statements)
    assert cand and any(s.predicate.endswith("supportedByEvidence") and s.object.endswith("evidence-candidate")
                        for m in cand for s in m.statements)

def test_derived_empty_vs_materialized():
    c = compiler()
    assert c.compile([], IntentAssessment(MG,[]), scope(), meta(), AS_OF, "q", "p").reasoning_status == "not_available"
    dm = RetrievedMember(TKOS+"derived-x",
        subject_by_partition={"graph-derived-context":[stmt(TKOS+"derived-x",TKOS+"displayName","d","graph-derived-context")]},
        incident_by_partition={"graph-derived-context":[stmt(TKOS+"derived-x",TKOS+"displayName","d","graph-derived-context")]})
    pack = c.compile([dm], IntentAssessment(MG,[]), scope(), meta(), AS_OF, "q", "p")
    assert pack.reasoning_status == "materialized_available" and pack.derived_claims

def test_gap_type_only_not_prefix():
    c = compiler()
    RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    typed = RetrievedMember(TKOS+"weird-id",
        subject_by_partition={"graph-candidate-and-dispute":[stmt(TKOS+"weird-id",RDF_TYPE,TKOS+"ContextGap","graph-candidate-and-dispute")]},
        incident_by_partition={"graph-candidate-and-dispute":[stmt(TKOS+"weird-id",RDF_TYPE,TKOS+"ContextGap","graph-candidate-and-dispute")]})
    pack = c.compile([typed], IntentAssessment(MG,[]), scope(), meta(), AS_OF, "q", "decision_preparation")
    assert any(m.id == "weird-id" for m in pack.context_gaps)
    prefix_only = RetrievedMember(TKOS+"gap-fake",
        subject_by_partition={"graph-candidate-and-dispute":[stmt(TKOS+"gap-fake",TKOS+"displayName","no type","graph-candidate-and-dispute")]},
        incident_by_partition={"graph-candidate-and-dispute":[stmt(TKOS+"gap-fake",TKOS+"displayName","no type","graph-candidate-and-dispute")]})
    pack2 = c.compile([prefix_only], IntentAssessment(MG,[]), scope(), meta(), AS_OF, "q", "decision_preparation")
    assert not any(m.id == "gap-fake" for m in pack2.context_gaps)
