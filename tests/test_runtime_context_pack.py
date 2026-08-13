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
    assert pack.ontology_release_id == "2.4.1" and len(pack.dataset_revision) == 64

def test_confirmed_current_and_expired_omission_with_fixture():
    # 探测查询用 member 精确 displayName（P1 严格规则下"增长"六路并列 → 409，
    # 探测必须唯一命中；本测试验证的是 omission 行为而非 resolver 匹配）
    pack = resolver([ROOT/"tests/v2.3-context-pack-runtime.trig"]).resolve(
        "验证增长路径的经营任务", "decision_preparation", AS_OF, [])
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
    # 同 test_confirmed_*：探测查询唯一命中 mission-growth，不触发 P1 409
    pack = resolver([ROOT/"tests/v2.3-context-pack-runtime.trig"]).resolve(
        "验证增长路径的经营任务", "decision_preparation", AS_OF, [])
    SENS = "assertion-sensitive"
    assert pack.matched_root.rsplit("#",1)[-1] != SENS
    assert all(SENS not in a["id"] for a in pack.alternative_matches)
    for b in (pack.current_facts, pack.candidate_context, pack.provenance_context, pack.derived_claims):
        for m in b:
            assert m.id != SENS
            for s in m.statements:
                assert s.subject.rsplit("#",1)[-1] != SENS and s.object.rsplit("#",1)[-1] != SENS
    assert "graph-sensitive-persona" not in pack.contributing_graphs


def test_rdf_types_roundtrip_and_default_empty():
    from tkos_runtime.api.serializer import pack_to_dict, dict_to_pack
    # resolver-built pack: candidate members carry rdf:type → rdf_types populated
    pack = resolver(sorted((ROOT/"data/instances").glob("*.trig"))).resolve(
        "是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
        "decision_preparation", AS_OF, [])
    d = pack_to_dict(pack)
    # candidate_context is non-empty for the FE issue; each member has rdf_types
    # (a list, possibly empty for members whose admitted slice had no rdf:type,
    # but the key must always be present after asdict)
    assert pack.candidate_context, "fixture pack should have candidate members"
    for m in d["candidate_context"]:
        assert "rdf_types" in m
        assert isinstance(m["rdf_types"], list)
    # at least one candidate member should have a non-empty rdf_types (the issue
    # itself is typed as StrategicIssue)
    assert any(m["rdf_types"] for m in d["candidate_context"]), (
        "expected at least one member with admitted rdf:type"
    )
    # round-trip: dict_to_pack preserves rdf_types
    rebuilt = dict_to_pack(d)
    for orig, new in zip(pack.candidate_context, rebuilt.candidate_context):
        assert new.rdf_types == orig.rdf_types
    # old/legacy pack without rdf_types still reconstructs → default []
    legacy = {"pack_id": "x", "dataset_revision": "a"*64, "ontology_release_id": "2.4.0",
              "current_facts": [{"id": "m1", "partition": "graph-confirmed-enterprise"}]}
    legacy_pack = dict_to_pack(legacy)
    assert legacy_pack.current_facts[0].rdf_types == []


def test_rdf_types_scoped_per_partition_not_cross_copied():
    """P1 regression: ContextPackMember.rdf_types carries ONLY the current view's
    OWN admitted types. Cross-view type merging is the job of type_index (Task 1),
    not the member view. A Candidate type must NOT leak into the Provenance view;
    a type asserted only in an Admission-rejected partition must enter NO accepted
    view.
    """
    from tkos_runtime.domain.models import GraphStatement, RetrievedMember, IntentAssessment, ScopeResolution
    from tkos_runtime.application.context_compiler import ContextCompiler
    RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
    SUBJ = TKOS + "risk-x"
    RISK_TYPE = TKOS + "Risk"
    SENS_TYPE = TKOS + "SensitiveNote"

    def stmt(p, o, g):
        return GraphStatement(SUBJ, p, o, g)

    # One member spanning three partitions:
    #   candidate   — typed Risk, status Candidate  → ADMITTED
    #   provenance  — no type, just a confirmsEntity edge → ADMITTED
    #   sensitive   — typed SensitiveNote            → REJECTED (partition_not_allowed)
    m = RetrievedMember(SUBJ,
        subject_by_partition={
            "graph-candidate-and-dispute": [
                stmt(RDF_TYPE, RISK_TYPE, "graph-candidate-and-dispute"),
                stmt(TKOS+"hasConfirmationStatus", TKOS+"Candidate", "graph-candidate-and-dispute"),
                stmt(TKOS+"displayName", "风险X", "graph-candidate-and-dispute"),
            ],
            "graph-decision-provenance": [
                stmt(TKOS+"confirmsEntity", TKOS+"other", "graph-decision-provenance"),
            ],
            "graph-sensitive-persona": [
                stmt(RDF_TYPE, SENS_TYPE, "graph-sensitive-persona"),
            ],
        },
        incident_by_partition={})

    pack = ContextCompiler(store=None, policy=AdmissionPolicy()).compile(
        [m], IntentAssessment(SUBJ, []),
        ScopeResolution([], [], "not_enforced", ""),
        {"ontology_release_id": "2.4.0", "dataset_revision": "x" * 64},
        AS_OF, "q", "decision_preparation",
    )

    cand = [v for v in pack.candidate_context if v.id == "risk-x"]
    prov = [v for v in pack.provenance_context if v.id == "risk-x"]
    assert cand and prov, "both candidate and provenance views should be admitted"

    # (1) Candidate view carries its OWN type only.
    assert cand[0].rdf_types == [RISK_TYPE], cand[0].rdf_types
    # (2) Provenance view has no type in its own slice → rdf_types == [].
    #     (A Candidate type must NOT be copied into the Provenance view.)
    assert prov[0].rdf_types == [], prov[0].rdf_types
    # (3) A type asserted only in an Admission-rejected partition leaks nowhere.
    assert all(SENS_TYPE not in v.rdf_types for v in (cand + prov))
    assert any(o.partition == "graph-sensitive-persona" for o in pack.omissions)
    # (4) Per-view isolation does not break downstream cross-view merging
    #     (type_index's job): unioning admitted views still recovers {Risk}.
    merged: set[str] = set()
    for v in (cand + prov):
        merged.update(v.rdf_types)
    assert merged == {RISK_TYPE}, merged
