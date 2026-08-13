# tests/test_runtime_intent.py
from pathlib import Path
import pytest
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from tkos_runtime.adapters.gram_intent_resolver import GramIntentResolver
from tkos_runtime.domain.models import NoMatchError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA, DATASET = ROOT/"ontology/schema/tkos-ontology.jsonld", ROOT/"ontology/datasets/tkos-runtime-dataset.trig"

def test_matches_fe_issue_exact():
    s = RdfDatasetStore(SCHEMA, DATASET, sorted((ROOT/"data/instances").glob("*.trig")), release_root=ROOT)
    ia = GramIntentResolver(s).resolve("是否在本季度同时完成产品 1.0 上线和灯塔项目交付", s.allowed_graphs("decision_preparation"))
    assert ia.root == "https://ontology.tokenking.ai/tkos#issue-product1-lighthouse-synchronous-delivery"

def test_no_match_raises_domain_error():
    s = RdfDatasetStore(SCHEMA, DATASET, sorted((ROOT/"data/instances").glob("*.trig")), release_root=ROOT)
    with pytest.raises(NoMatchError):
        GramIntentResolver(s).resolve("完全不存在的查询词xyzq", s.allowed_graphs("decision_preparation"))

def test_sensitive_not_matched_fragment_consistent():
    # 三审起查询改为"历史数据"：旧查询（一号位历史判断偏好）在 v2.3 小包
    # 中主题（判断/偏好/一号位）全文零出现，按中文剩余主题否决应 404；
    # 敏感排除的验证改由通过门禁的查询承载（evidence-expired 的
    # displayName 含"历史"）。与 test_runtime_intent_gate.py 同名用例一致。
    s = RdfDatasetStore(SCHEMA, DATASET, [ROOT/"tests/v2.3-context-pack-runtime.trig"], release_root=ROOT)
    ia = GramIntentResolver(s).resolve("历史数据", s.allowed_graphs("decision_preparation"))
    SENS = "assertion-sensitive"
    assert ia.root.rsplit("#",1)[-1] != SENS
    assert all(a[1] != SENS for a in ia.alternatives)
