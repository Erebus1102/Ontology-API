# tests/test_runtime_store.py
import os, tempfile
from pathlib import Path
from rdflib import Graph
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore

ROOT = Path(__file__).resolve().parents[1]
SCHEMA, DATASET = ROOT/"ontology/schema/tkos-ontology.jsonld", ROOT/"ontology/datasets/tkos-runtime-dataset.trig"

def store(paths, release_root=None):
    return RdfDatasetStore(SCHEMA, DATASET, paths, release_root=release_root or ROOT)

def test_registered_partitions_from_registry():
    s = store(sorted((ROOT/"data/instances").glob("*.trig")))
    assert "graph-confirmed-enterprise" in s.registered_partition_ids
    assert "graph-sensitive-persona" in s.registered_partition_ids

def test_allowed_uses_registry_intersection():
    s = store(sorted((ROOT/"data/instances").glob("*.trig")))
    gs = set(s.allowed_graphs("decision_preparation"))
    assert "graph-sensitive-persona" not in gs and gs <= s.registered_partition_ids

def test_registry_results_come_from_file_content(tmp_path):
    # 临时注册表只含 confirmed + sensitive
    reg = tmp_path/"reg.trig"
    reg.write_text('''@prefix tkos: <https://ontology.tokenking.ai/tkos#> .
tkos:graph-registry {
  tkos:graph-confirmed-enterprise a tkos:KnowledgeGraphPartition .
  tkos:graph-sensitive-persona a tkos:KnowledgeGraphPartition .
}''', encoding="utf-8")
    s = RdfDatasetStore(SCHEMA, reg, [], release_root=tmp_path)
    assert s.registered_partition_ids == {"graph-confirmed-enterprise", "graph-sensitive-persona"}
    assert s.allowed_graphs("decision_preparation") == ["graph-confirmed-enterprise"]

def test_restricted_node_ids_from_sensitive_fixture():
    s = store([ROOT/"tests/v2.3-context-pack-runtime.trig"])
    assert "https://ontology.tokenking.ai/tkos#assertion-sensitive" in s.restricted_node_ids

def test_port_filters_restricted_subject_or_object():
    s = store([ROOT/"tests/v2.3-context-pack-runtime.trig"])
    SENS = "https://ontology.tokenking.ai/tkos#assertion-sensitive"
    for st in s.statements_in(["graph-confirmed-enterprise","graph-candidate-and-dispute","graph-decision-provenance","graph-sensitive-persona"]):
        assert st.subject != SENS and st.object != SENS

def test_revision_invariant_under_cwd(tmp_path, monkeypatch):
    paths = sorted((ROOT/"data/instances").glob("*.trig"))
    monkeypatch.chdir(tmp_path)
    r1 = store(paths).dataset_revision
    monkeypatch.chdir(ROOT)
    r2 = store(paths).dataset_revision
    assert r1 == r2 and len(r1) == 64

def test_version_metadata():
    s = store(sorted((ROOT/"data/instances").glob("*.trig")))
    assert s.ontology_release_id == "2.4.1"

def test_default_release_root_supports_repository_instances():
    # 不传 release_root，验证默认推导（parents[2]）能处理 data/instances 下的文件
    s = RdfDatasetStore(SCHEMA, DATASET, sorted((ROOT/"data/instances").glob("*.trig")))
    assert len(s.dataset_revision) == 64

def test_object_value_and_statements_in_block_restricted_object():
    # 允许图中存在指向敏感节点的关系（fixture: mission-growth informedBy assertion-sensitive）
    s = store([ROOT/"tests/v2.3-context-pack-runtime.trig"])
    SENS = "https://ontology.tokenking.ai/tkos#assertion-sensitive"
    allowed = ["graph-confirmed-enterprise", "graph-candidate-and-dispute", "graph-decision-provenance"]
    # statements_in 已过滤
    objs = {st.object for st in s.statements_in(allowed)}
    assert SENS not in objs
    # object_value 也不得泄漏敏感节点
    mg = "https://ontology.tokenking.ai/tkos#mission-growth"
    assert s.object_value(mg, "https://ontology.tokenking.ai/tkos#informedBy", allowed) != SENS
