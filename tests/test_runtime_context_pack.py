# tests/test_runtime_context_pack.py
from datetime import datetime
from pathlib import Path
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from tkos_runtime.adapters.gram_intent_resolver import GramIntentResolver
from tkos_runtime.adapters.rdflib_graph_retriever import RdfGraphRetriever
from tkos_runtime.application.context_compiler import ContextCompiler
from tkos_runtime.application.context_pack_resolver import ContextPackResolver
from tkos_runtime.domain.policies import AdmissionPolicy

ROOT = Path(__file__).resolve().parents[1]
SCHEMA, DATASET = ROOT/"ontology/schema/tkos-ontology.jsonld", ROOT/"ontology/datasets/tkos-runtime-dataset.trig"
AS_OF = datetime.fromisoformat("2026-08-11T23:59:59+08:00")
TKOS = "https://ontology.tokenking.ai/tkos#"
ISSUE = TKOS+"issue-product1-lighthouse-synchronous-delivery"

def resolver(paths):
    s = RdfDatasetStore(SCHEMA, DATASET, paths, release_root=ROOT)
    return ContextPackResolver(s, GramIntentResolver(s), RdfGraphRetriever(s), ContextCompiler(s, AdmissionPolicy()))

def all_stmts(pack):
    return [st for b in (pack.current_facts, pack.candidate_context, pack.provenance_context, pack.derived_claims)
            for m in b for st in m.statements]

def test_fe_issue_seven_contracts():
    pack = resolver(sorted((ROOT/"data/instances").glob("*.trig"))).resolve(
        "是否在本季度同时完成产品 1.0 上线和灯塔项目交付", "decision_preparation", AS_OF, [])
    # 1. matched_root 精确相等
    assert pack.matched_root == ISSUE
    # 2. 逐语句图身份 + 议题精确 candidate + 确认事件精确 provenance 且入 proof
    stmts = all_stmts(pack)
    assert stmts and all(s.source_graph for s in stmts)
    iss = next((m for m in pack.candidate_context if m.id == "issue-product1-lighthouse-synchronous-delivery"), None)
    assert iss and iss.source_graphs == ["graph-candidate-and-dispute"]
    assert any(m.id == "confirmation-mission-fe-m2-card" for m in pack.provenance_context)
    assert {"from":"confirmation-mission-fe-m2-card","predicate":"confirmsEntity",
            "to":"mission-fe-m2-lighthouse-context-loop"} in [{k:e[k] for k in ("from","predicate","to")} for e in pack.proof]
    # 3. current 空（confirmed 图空），候选不泄漏
    assert pack.current_facts == [] and pack.candidate_context
    assert not any(m.confirmation_status in ("Candidate","PreliminarilyConfirmed","Archived") for m in pack.current_facts)
    # 4. 每成员 source_graphs 非空 + ContextGap 子集
    for b in (pack.current_facts, pack.candidate_context, pack.provenance_context):
        for m in b: assert m.source_graphs
    assert "gap-product1-lighthouse-synchronous-delivery-facts" in {m.id for m in pack.context_gaps}
    # 5. omissions：archived gap，stage=confirmation+reason
    arch = [o for o in pack.omissions if o.subject == "gap-product1-name-scope-confirmation"]
    assert arch and arch[0].stage == "confirmation" and arch[0].reason
    # 6. scope + sensitive 不贡献
    assert pack.scope_resolution.enforcement == "not_enforced"
    assert "graph-sensitive-persona" not in pack.contributing_graphs
    # 7. 版本元数据
    assert pack.ontology_release_id == "2.4.0" and len(pack.dataset_revision) == 64

def test_confirmed_current_and_expired_omission_with_fixture():
    pack = resolver([ROOT/"tests/v2.3-context-pack-runtime.trig"]).resolve("增长", "decision_preparation", AS_OF, [])
    assert any(m.id == "mission-growth" for m in pack.current_facts)
    for m in pack.current_facts:
        assert all(s.source_graph == "graph-confirmed-enterprise" for s in m.statements)
    # candidate 边只在 candidate_context；confirmed 的 supportedByEvidence 允许留在 current
    cand = [m for m in pack.candidate_context if m.id == "mission-growth"]
    assert cand and any(s.predicate.endswith("supportedByEvidence") and s.object.endswith("evidence-candidate")
                        for m in cand for s in m.statements)
    cur = [m for m in pack.current_facts if m.id == "mission-growth"]
    assert not any(s.predicate.endswith("supportedByEvidence") and s.object.endswith("evidence-candidate")
                   for m in cur for s in m.statements)
    exp = [o for o in pack.omissions if o.subject == "evidence-expired"]
    assert exp and exp[0].stage == "valid_time" and exp[0].reason

def test_aggregate_sensitive_isolation():
    pack = resolver([ROOT/"tests/v2.3-context-pack-runtime.trig"]).resolve("增长", "decision_preparation", AS_OF, [])
    SENS = "assertion-sensitive"
    assert pack.matched_root.rsplit("#",1)[-1] != SENS
    assert all(SENS not in a["id"] for a in pack.alternative_matches)
    for b in (pack.current_facts, pack.candidate_context, pack.provenance_context, pack.derived_claims):
        for m in b:
            assert m.id != SENS
            for s in m.statements:
                assert s.subject.rsplit("#",1)[-1] != SENS and s.object.rsplit("#",1)[-1] != SENS
    assert "graph-sensitive-persona" not in pack.contributing_graphs
