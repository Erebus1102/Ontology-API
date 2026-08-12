# P0-1 运行时最小只读栈 Implementation Plan (v4)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建进程内 TKOS 只读运行时，覆盖 API 1（Context Pack）与 API 3（Assertion Lineage），逐三元组保留命名图身份。

**Architecture:** 端口与适配器分层。应用层端口（`GraphPolicy`、`LineageRepository` 等）为单参 `allowed_graphs(purpose)`；`AdmissionPolicy` 是 Store 内部纯策略（接收 `registered`/`restricted`），不直接充当应用层端口。准入两段式：图策略/敏感隔离在端口；时间/确认状态在分区切片准入。

**Tech Stack:** Python ≥3.9, rdflib ≥7.1, pyshacl（仅既有测试）。无新依赖。

## Global Constraints

- 命名空间：`TKOS = "https://ontology.tokenking.ai/tkos#"`；图 IRI = `TKOS + "graph-<partition>"`。
- 分区集合**由图注册表 `tkos:graph-registry` 解析**：`allowed = purpose_allowed ∩ registered − restricted`。单纯新增未知分区不自动授权；需同时出现在用途策略与注册表中。
- **`graph-sensitive-persona` 永不进入 `allowed_graph_ids`**；其 subject IRI 进入 `restricted_node_ids`，跨端口 GraphStatement 命中 subject|object 即丢弃。
- 验收推导不在 Python 实现；Derived 空 → `reasoning_status="not_available"`；Derived 有合格成员 → `"materialized_available"`（只读物化结果）。
- BFS：双向、`max_depth=2`、`predicate_set=query_plan.TRAVERSAL`（单一来源，含 Mission 详情谓词 + `confirmsEntity`）、按 IRI 稳定排序。
- `dataset_revision`：相对**仓库 release root**（由 `dataset_path` 推导，不依赖 cwd）的 POSIX 路径，长度前缀 SHA-256。
- `ontology_release_id`=`owl:versionInfo`(2.4.0)；`policy_version="read-admission/p0-v1"`；`schema_version="context-pack/1.0-draft"`；`query_plan_version="bfs-2gram/p0-v1"`。
- 组织作用域 `enforcement="not_enforced"`。
- 所有列表稳定排序；未知 purpose 抛 `ValueError`；无匹配抛 `NoMatchError`。
- TDD，`make test-fast` 始终绿。

---

## File Structure

- `src/tkos_runtime/domain/{models,query_plan,ports,policies}.py`
- `src/tkos_runtime/adapters/{rdflib_dataset_store,gram_intent_resolver,rdflib_graph_retriever,rdflib_lineage_repository}.py`
- `src/tkos_runtime/application/{context_compiler,proof_builder,context_pack_resolver,lineage_resolver}.py`
- Modify `scripts/resolve_issue_context.py`（接入 `query_plan`）、`Makefile`、`.github/workflows/ci.yml`（删除 SWRL job）、`README.md`。
- Tests `tests/test_runtime_*.py`。

---

### Task 1: 领域模型 domain/models.py

**Files:** Create `src/tkos_runtime/domain/models.py`; Test `tests/test_runtime_models.py`
**Interfaces:** Produces 全部领域类与 `NoMatchError`。

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 跑测试确认失败** — `python3 -m pytest tests/test_runtime_models.py -v` → FAIL
- [ ] **Step 3: 实现 models.py**

```python
# src/tkos_runtime/domain/models.py
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class NoMatchError(Exception):
    """Intent 未匹配到任何对象。"""


class GraphPartition(str, Enum):
    CONFIRMED_ENTERPRISE = "graph-confirmed-enterprise"
    CANDIDATE_AND_DISPUTE = "graph-candidate-and-dispute"
    DECISION_PROVENANCE = "graph-decision-provenance"
    DERIVED_CONTEXT = "graph-derived-context"
    SENSITIVE_PERSONA = "graph-sensitive-persona"


@dataclass(frozen=True)
class GraphStatement:
    subject: str
    predicate: str
    object: str
    source_graph: str


@dataclass
class RetrievedMember:
    subject: str
    subject_by_partition: dict[str, list[GraphStatement]]
    incident_by_partition: dict[str, list[GraphStatement]]

    @property
    def source_graphs(self) -> list[str]:
        gs = {s.source_graph for sl in self.subject_by_partition.values() for s in sl}
        gs |= {s.source_graph for sl in self.incident_by_partition.values() for s in sl}
        return sorted(gs)


@dataclass
class AdmissionDecision:
    accept: bool
    partition: str
    stage: str | None = None
    reason: str | None = None


@dataclass
class Omission:
    subject: str
    partition: str
    stage: str
    reason: str


@dataclass
class ContextPackMember:
    id: str
    display_name: str
    scope: str | None
    partition: str
    statements: list[GraphStatement]
    source_graphs: list[str]
    confirmation_status: str | None
    lifecycle: str | None
    valid_from: str | None
    valid_until: str | None
    sources: list[str]
    admission: AdmissionDecision


@dataclass
class ScopeResolution:
    requested_scope: list[str]
    resolved_scope: list[str]
    enforcement: str
    reason: str


@dataclass
class IntentAssessment:
    root: str
    alternatives: list[tuple[int, str, str]]


@dataclass
class Lineage:
    assertion_id: str
    named_graph: str | None
    source_records: list[dict]
    asserted_by: str | None
    confirmation_status: str | None
    supporting: list[dict]
    challenging: list[dict]
    supersedes: list[dict]


@dataclass
class LineageProof:
    assertion_id: str
    named_graph: str | None
    source_records: list[dict]
    asserted_by: str | None
    confirmation_status: str | None
    supporting: list[dict]
    challenging: list[dict]
    supersedes: list[dict]


@dataclass
class ContextPack:
    pack_id: str
    schema_version: str
    as_of: str
    query: str
    purpose: str
    matched_root: str
    alternative_matches: list[dict]
    scope_resolution: ScopeResolution
    current_facts: list[ContextPackMember]
    candidate_context: list[ContextPackMember]
    provenance_context: list[ContextPackMember]
    proof: list[dict]
    derived_claims: list[ContextPackMember]
    reasoning_status: str
    context_gaps: list[ContextPackMember]
    conflicts: list[dict]
    omissions: list[Omission]
    contributing_graphs: list[str]
    admission_policy: str
    ontology_release_id: str
    dataset_revision: str
    policy_version: str
    query_plan_version: str
```

- [ ] **Step 4: 跑测试确认通过** — PASS
- [ ] **Step 5: 提交** — `git add ... && git commit -m "feat(runtime): 领域模型 models.py"`

---

### Task 2: 查询计划 domain/query_plan.py

**Files:** Create `src/tkos_runtime/domain/query_plan.py`; Test `tests/test_runtime_query_plan.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_runtime_query_plan.py
from tkos_runtime.domain import query_plan

def test_traversal_and_constants():
    p = set(query_plan.TRAVERSAL)
    for need in ["hasProgressSnapshot","confirmsEntity","supportedByEvidence","hasContextGap","hasCriterion","informedBy"]:
        assert ("https://ontology.tokenking.ai/tkos#"+need) in p
    assert query_plan.MAX_DEPTH == 2 and query_plan.QUERY_PLAN_VERSION == "bfs-2gram/p0-v1"
```

- [ ] **Step 2: 跑测试确认失败** — FAIL
- [ ] **Step 3: 实现 query_plan.py**

```python
# src/tkos_runtime/domain/query_plan.py
"""BFS 查询计划单一来源（Retriever 与 scripts/resolve_issue_context.py 共享）。"""
TKOS = "https://ontology.tokenking.ai/tkos#"
MAX_DEPTH = 2
QUERY_PLAN_VERSION = "bfs-2gram/p0-v1"
TRAVERSAL = [TKOS + p for p in (
    "informedBy","researchedBy","hasContextGap","hasRisk","contributesTo","belongsTo",
    "hasOutcome","hasPortfolio","inPortfolio","expects","hasResponsibleAssignment",
    "assignmentHolder","assignmentRole","assignmentScope","dependsOn","hasMilestone",
    "hasProgressSnapshot","hasCriterion","hasRationale","hasScope","hasKeyPath",
    "supportedByEvidence","sourcedFrom","confirmedBy","challengingEvidence","challengesClaim",
    "isReviewedBy","delivers","supports","isDeliveredBy","hasSuccessCriterion","contains","confirmsEntity",
)]
```

- [ ] **Step 4: 跑测试确认通过** — PASS
- [ ] **Step 5: 提交** — `git commit -m "feat(runtime): query_plan.py 单一来源"`

---

### Task 3: 准入策略 domain/policies.py（注册表交集，可配置 purpose_allowed）

**Files:** Create `src/tkos_runtime/domain/policies.py`; Test `tests/test_runtime_policies.py`
**Interfaces:** Produces `AdmissionPolicy(purpose_allowed=None)`：`allowed_graphs(purpose, registered, restricted)` 与 `decide(partition, subject_statements, as_of)`。**纯策略，注册表作为参数传入**（应用层端口由 Store 单参封装）。

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 跑测试确认失败** — FAIL
- [ ] **Step 3: 实现 policies.py**

```python
# src/tkos_runtime/domain/policies.py
from __future__ import annotations
from datetime import datetime
from tkos_runtime.domain.models import GraphStatement, AdmissionDecision

_DEFAULT_PURPOSE_ALLOWED = {
    "decision_preparation": ["graph-confirmed-enterprise","graph-decision-provenance","graph-candidate-and-dispute","graph-derived-context"],
    "mission_review": ["graph-confirmed-enterprise","graph-decision-provenance","graph-derived-context"],
}


class AdmissionPolicy:
    """纯策略。Store 以 registered/restricted 调用；不直接作应用层端口。"""
    def __init__(self, purpose_allowed: dict[str, list[str]] | None = None):
        self.purpose_allowed = purpose_allowed or _DEFAULT_PURPOSE_ALLOWED

    def allowed_graphs(self, purpose: str, registered: set[str], restricted: set[str]) -> list[str]:
        if purpose not in self.purpose_allowed:
            raise ValueError(f"unknown purpose: {purpose!r}")
        base = [g for g in self.purpose_allowed[purpose] if g in registered and g not in restricted]
        return sorted(base)

    def decide(self, partition: str, subject_statements: list[GraphStatement], as_of: datetime) -> AdmissionDecision:
        if partition in ("graph-decision-provenance", "graph-derived-context"):
            return AdmissionDecision(True, partition)
        if partition == "graph-confirmed-enterprise":
            return self._confirmed(partition, subject_statements, as_of)
        if partition == "graph-candidate-and-dispute":
            return self._candidate(partition, subject_statements, as_of)
        return AdmissionDecision(False, partition, "graph_policy", "partition_not_allowed")

    def _status(self, stmts):
        for s in stmts:
            if s.predicate.endswith("hasConfirmationStatus"):
                return s.object.rsplit("#", 1)[-1]
        return None

    def _valid(self, partition, stmts, as_of):
        vf = [s.object for s in stmts if s.predicate.endswith("validFrom")]
        vu = [s.object for s in stmts if s.predicate.endswith("validUntil")]
        if vf and any(_parse(t) > as_of for t in vf):
            return AdmissionDecision(False, partition, "valid_time", "not_yet_valid")
        if vu and all(_parse(t) < as_of for t in vu):
            return AdmissionDecision(False, partition, "valid_time", "expired")
        return None

    def _confirmed(self, partition, stmts, as_of):
        st = self._status(stmts)
        if st != "Confirmed":
            return AdmissionDecision(False, partition, "confirmation", f"status={st}")
        return self._valid(partition, stmts, as_of) or AdmissionDecision(True, partition)

    def _candidate(self, partition, stmts, as_of):
        st = self._status(stmts)
        if st == "Archived":
            return AdmissionDecision(False, partition, "confirmation", "archived")
        if st is None:
            st = "CandidateByPartition"
        if st not in {"Candidate", "PreliminarilyConfirmed", "CandidateByPartition"}:
            return AdmissionDecision(False, partition, "confirmation", f"status={st}")
        return self._valid(partition, stmts, as_of) or AdmissionDecision(True, partition)


def _parse(t: str) -> datetime:
    return datetime.fromisoformat(t.replace("Z", "+00:00"))
```

- [ ] **Step 4: 跑测试确认通过** — PASS
- [ ] **Step 5: 提交** — `git commit -m "feat(runtime): AdmissionPolicy（注册表交集 + 可配置 purpose_allowed + effective_status）"`

---

### Task 4: RdfDatasetStore（注册表解析 + cwd 无关 revision + restricted_node_ids + 敏感隔离）

**Files:** Create `src/tkos_runtime/adapters/rdflib_dataset_store.py`; Test `tests/test_runtime_store.py`
**Interfaces:** Produces `RdfDatasetStore(schema_path, dataset_path, instance_paths, release_root=None)`：单参 `allowed_graphs(purpose)`（实现应用层 `GraphPolicy` 端口）、`registered_partition_ids`、`restricted_partition_ids`、`restricted_node_ids`、`statements_in`、`neighbors`、`member_statements`、`subject_statements`、`object_value`、`ontology_release_id`、`dataset_revision`。

- [ ] **Step 1: 写失败测试**

```python
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
    assert s.ontology_release_id == "2.4.0"

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
```

- [ ] **Step 2: 跑测试确认失败** — FAIL
- [ ] **Step 3: 实现 rdflib_dataset_store.py**

```python
# src/tkos_runtime/adapters/rdflib_dataset_store.py
from __future__ import annotations
import hashlib
from pathlib import Path, PurePosixPath
from rdflib import Dataset, Graph, URIRef, RDF
from rdflib.namespace import OWL
from tkos_runtime.domain.models import GraphStatement
from tkos_runtime.domain.policies import AdmissionPolicy

TKOS = "https://ontology.tokenking.ai/tkos#"
PARTITION_CLASS = TKOS + "KnowledgeGraphPartition"
REGISTRY = TKOS + "graph-registry"
SENSITIVE = "graph-sensitive-persona"


def _frag(u: str) -> str:
    return str(u).rsplit("#", 1)[-1]


class RdfDatasetStore:
    def __init__(self, schema_path: Path, dataset_path: Path, instance_paths: list[Path], release_root: Path | None = None):
        self._ds = Dataset()
        self._ds.parse(schema_path, format="json-ld")
        self._ds.parse(dataset_path, format="trig")
        for p in instance_paths:
            self._ds.parse(p, format="trig")
        self._policy = AdmissionPolicy()
        self.registered_partition_ids = self._read_registered()
        self.restricted_partition_ids = {SENSITIVE}
        self.restricted_node_ids = self._compute_restricted()
        self.ontology_release_id = self._version(schema_path)
        # release_root 默认上溯至仓库根（file ← datasets ← ontology ← 根，即 parents[2]）
        self._release_root = (release_root or dataset_path.resolve().parents[2])
        self.dataset_revision = self._revision(dataset_path, instance_paths)

    def _read_registered(self) -> set[str]:
        out = set()
        for s, _, _ in self._ds.graph(URIRef(REGISTRY)).triples((None, RDF.type, URIRef(PARTITION_CLASS))):
            out.add(_frag(s))
        return out

    def _compute_restricted(self) -> set[str]:
        ids = set()
        for g in self._ds.graphs():
            if _frag(g.identifier) == SENSITIVE:
                for s, _, _ in g:
                    if isinstance(s, URIRef):
                        ids.add(str(s))
        return ids

    def _version(self, schema_path: Path) -> str:
        for o in Graph().parse(schema_path, format="json-ld").objects(URIRef(TKOS), OWL.versionInfo):
            return str(o)
        return "unknown"

    def _posix_rel(self, p: Path) -> str:
        return PurePosixPath(*p.resolve().relative_to(self._release_root.resolve()).parts).as_posix()

    def _revision(self, dataset_path: Path, instance_paths: list[Path]) -> str:
        h = hashlib.sha256()
        for p in sorted([dataset_path, *instance_paths]):
            rel, data = self._posix_rel(p), p.read_bytes()
            rb, db = rel.encode(), data
            h.update(len(rb).to_bytes(8, "big")); h.update(rb)
            h.update(len(db).to_bytes(8, "big")); h.update(db)
        return h.hexdigest()

    # —— 单参 GraphPolicy 端口（应用层使用）——
    def allowed_graphs(self, purpose: str) -> list[str]:
        return self._policy.allowed_graphs(purpose, self.registered_partition_ids, self.restricted_partition_ids)

    def _uris(self, graph_ids: list[str]) -> list[str]:
        return [TKOS + f for f in graph_ids if f in self.registered_partition_ids]

    def _ok(self, s: str, o: str) -> bool:
        return s not in self.restricted_node_ids and o not in self.restricted_node_ids

    def _stmt(self, s, p, o, g) -> GraphStatement:
        return GraphStatement(str(s), str(p), str(o), _frag(g))

    def statements_in(self, graph_ids: list[str]) -> list[GraphStatement]:
        out = []
        for guid in self._uris(graph_ids):
            g = self._ds.graph(URIRef(guid))
            for s, p, o in g:
                if self._ok(str(s), str(o)):
                    out.append(self._stmt(s, p, o, guid))
        return sorted(out, key=lambda x: (x.subject, x.predicate, x.object, x.source_graph))

    def neighbors(self, node: str, predicates: list[str], graph_ids: list[str]) -> list[tuple[str, GraphStatement]]:
        n = URIRef(node)
        out = []
        for guid in self._uris(graph_ids):
            g = self._ds.graph(URIRef(guid))
            for p in [URIRef(p0) for p0 in predicates]:
                for o in g.objects(n, p):
                    if isinstance(o, URIRef) and self._ok(node, str(o)):
                        out.append((str(o), GraphStatement(str(n), str(p), str(o), _frag(guid))))
                for s in g.subjects(p, n):
                    if isinstance(s, URIRef) and self._ok(str(s), node):
                        out.append((str(s), GraphStatement(str(s), str(p), str(n), _frag(guid))))
        seen, ded = set(), []
        for nb, st in sorted(out, key=lambda x: (x[0], x[1].predicate, x[1].object, x[1].source_graph)):
            k = (nb, st.predicate, st.object, st.source_graph)
            if k not in seen:
                seen.add(k); ded.append((nb, st))
        return ded

    def member_statements(self, subject: str, graph_ids: list[str]) -> list[GraphStatement]:
        """双向 incident（BFS/proof/关系）。"""
        n = URIRef(subject)
        out = []
        for guid in self._uris(graph_ids):
            g = self._ds.graph(URIRef(guid))
            for s, p, o in g:
                if (s == n or o == n) and self._ok(str(s), str(o)):
                    out.append(self._stmt(s, p, o, guid))
        return sorted(out, key=lambda x: (x.predicate, x.subject, x.object, x.source_graph))

    def subject_statements(self, subject: str, graph_ids: list[str]) -> list[GraphStatement]:
        """仅 subject==成员（字段/准入），避免入向污染。"""
        n = URIRef(subject)
        out = []
        for guid in self._uris(graph_ids):
            g = self._ds.graph(URIRef(guid))
            for s, p, o in g:
                if s == n and self._ok(str(s), str(o)):
                    out.append(self._stmt(s, p, o, guid))
        return sorted(out, key=lambda x: (x.predicate, x.object, x.source_graph))

    def object_value(self, subject: str, predicate: str, graph_ids: list[str]) -> str | None:
        # 端口信任边界：subject 或 object 命中 restricted_node_ids 则不返回
        if subject in self.restricted_node_ids:
            return None
        n, p = URIRef(subject), URIRef(predicate)
        values = []
        for guid in self._uris(graph_ids):
            for o in self._ds.graph(URIRef(guid)).objects(n, p):
                if self._ok(subject, str(o)):
                    values.append((guid, str(o)))  # 按 (图, 对象) 稳定排序取第一个，保证可复现
        if not values:
            return None
        values.sort(key=lambda x: (_frag(x[0]), x[1]))
        return values[0][1]
```

- [ ] **Step 4: 跑测试确认通过** — PASS
- [ ] **Step 5: 提交** — `git commit -m "feat(runtime): RdfDatasetStore 注册表解析 + cwd 无关 revision + restricted_node_ids"`

---

### Task 5: 端口 domain/ports.py

**Files:** Create `src/tkos_runtime/domain/ports.py`

- [ ] **Step 1: 实现 ports.py（应用层端口单参）**

```python
# src/tkos_runtime/domain/ports.py
from __future__ import annotations
from typing import Protocol
from tkos_runtime.domain.models import GraphStatement, RetrievedMember, IntentAssessment, Lineage


class GraphPolicy(Protocol):
    def allowed_graphs(self, purpose: str) -> list[str]: ...   # 单参（Store 实现）


class DatasetStore(GraphPolicy, Protocol):
    ontology_release_id: str
    dataset_revision: str
    registered_partition_ids: set[str]
    def statements_in(self, graph_ids: list[str]) -> list[GraphStatement]: ...
    def neighbors(self, node: str, predicates: list[str], graph_ids: list[str]) -> list[tuple[str, GraphStatement]]: ...
    def member_statements(self, subject: str, graph_ids: list[str]) -> list[GraphStatement]: ...
    def subject_statements(self, subject: str, graph_ids: list[str]) -> list[GraphStatement]: ...
    def object_value(self, subject: str, predicate: str, graph_ids: list[str]) -> str | None: ...


class IntentResolver(Protocol):
    def resolve(self, query: str, allowed_graph_ids: list[str]) -> IntentAssessment: ...


class GraphRetriever(Protocol):
    def retrieve(self, root: str, allowed_graph_ids: list[str]) -> list[RetrievedMember]: ...


class LineageRepository(Protocol):
    def fetch(self, assertion_id: str, allowed_graph_ids: list[str]) -> Lineage: ...
```

- [ ] **Step 2: 跑既有 runtime 测试确认无回归** — `python3 -m pytest tests/test_runtime_*.py -v` → PASS
- [ ] **Step 3: 提交** — `git commit -m "feat(runtime): ports.py（GraphPolicy 单参）"`

---

### Task 6: GramIntentResolver（NoMatchError）

**Files:** Create `src/tkos_runtime/adapters/gram_intent_resolver.py`; Test `tests/test_runtime_intent.py`

- [ ] **Step 1: 写失败测试**

```python
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
    s = RdfDatasetStore(SCHEMA, DATASET, [ROOT/"tests/v2.3-context-pack-runtime.trig"], release_root=ROOT)
    ia = GramIntentResolver(s).resolve("一号位历史判断偏好", s.allowed_graphs("decision_preparation"))
    SENS = "assertion-sensitive"
    assert ia.root.rsplit("#",1)[-1] != SENS
    assert all(a[1] != SENS for a in ia.alternatives)
```

- [ ] **Step 2: 跑测试确认失败** — FAIL
- [ ] **Step 3: 实现 gram_intent_resolver.py**

```python
# src/tkos_runtime/adapters/gram_intent_resolver.py
from __future__ import annotations
from tkos_runtime.domain.models import IntentAssessment, NoMatchError

DISPLAY = "https://ontology.tokenking.ai/tkos#displayName"
SCOPE = "https://ontology.tokenking.ai/tkos#scopeDescription"
OBJECT_ID = "https://ontology.tokenking.ai/tkos#objectId"


def _frag(u): return str(u).rsplit("#", 1)[-1]


class GramIntentResolver:
    def __init__(self, store):
        self._store = store

    def resolve(self, query: str, allowed_graph_ids: list[str]) -> IntentAssessment:
        text, names = self._index(allowed_graph_ids)
        q = query.lower().strip()
        grams = {q[i:i+2] for i in range(max(0, len(q)-1))}
        scored = []
        for node, hay in text.items():
            sc = (100 + len(q)) if (q and q in hay) else sum(1 for g in grams if g in hay)
            if sc > 0:
                scored.append((sc, node))
        ranked = sorted(scored, key=lambda x: (-x[0], x[1]))[:5]
        if not ranked:
            raise NoMatchError(f"未匹配到对象：{query!r}")
        return IntentAssessment(root=ranked[0][1],
            alternatives=[(sc, _frag(n), names.get(n, _frag(n))) for sc, n in ranked[1:]])

    def _index(self, graph_ids):
        text, names = {}, {}
        for s in self._store.statements_in(graph_ids):
            v = str(s.object)
            if s.predicate in (DISPLAY, SCOPE, OBJECT_ID):
                text.setdefault(s.subject, []).append(v)
            if s.predicate == DISPLAY:
                names.setdefault(s.subject, v)
        return {n: " ".join(v).lower() for n, v in text.items()}, names
```

- [ ] **Step 4: 跑测试确认通过** — PASS
- [ ] **Step 5: 提交** — `git commit -m "feat(runtime): GramIntentResolver（2-gram + NoMatchError）"`

---

### Task 7: RdfGraphRetriever（BFS + subject/incident 切片）

**Files:** Create `src/tkos_runtime/adapters/rdflib_graph_retriever.py`; Test `tests/test_runtime_retriever.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_runtime_retriever.py
from pathlib import Path
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from tkos_runtime.adapters.rdflib_graph_retriever import RdfGraphRetriever

ROOT = Path(__file__).resolve().parents[1]
SCHEMA, DATASET = ROOT/"ontology/schema/tkos-ontology.jsonld", ROOT/"ontology/datasets/tkos-runtime-dataset.trig"
MG = "https://ontology.tokenking.ai/tkos#mission-growth"

def test_mission_growth_dual_slice_and_subject_incident_split():
    s = RdfDatasetStore(SCHEMA, DATASET, [ROOT/"tests/v2.3-context-pack-runtime.trig"], release_root=ROOT)
    mg = {m.subject: m for m in RdfGraphRetriever(s).retrieve(MG,
        ["graph-confirmed-enterprise","graph-candidate-and-dispute","graph-decision-provenance"])}[MG]
    assert "graph-confirmed-enterprise" in mg.subject_by_partition
    assert "graph-candidate-and-dispute" in mg.incident_by_partition
    assert any(st.predicate.endswith("supportedByEvidence") for st in mg.incident_by_partition["graph-candidate-and-dispute"])
    assert not any(st.predicate.endswith("hasConfirmationStatus")
                   for st in mg.subject_by_partition.get("graph-candidate-and-dispute", []))
```

- [ ] **Step 2: 跑测试确认失败** — FAIL
- [ ] **Step 3: 实现 rdflib_graph_retriever.py**

```python
# src/tkos_runtime/adapters/rdflib_graph_retriever.py
from __future__ import annotations
from collections import deque
from tkos_runtime.domain import query_plan
from tkos_runtime.domain.models import RetrievedMember, GraphStatement


def _by_partition(stmts):
    out: dict[str, list[GraphStatement]] = {}
    for s in stmts:
        out.setdefault(s.source_graph, []).append(s)
    return out


class RdfGraphRetriever:
    def __init__(self, store):
        self._store = store

    def retrieve(self, root: str, allowed_graph_ids: list[str]) -> list[RetrievedMember]:
        visited = {root}
        q = deque([(root, 0)])
        while q:
            node, depth = q.popleft()
            if depth >= query_plan.MAX_DEPTH:
                continue
            for nb, _st in self._store.neighbors(node, query_plan.TRAVERSAL, allowed_graph_ids):
                if nb not in visited:
                    visited.add(nb)
                    q.append((nb, depth + 1))
        members = []
        for node in sorted(visited):
            inc = _by_partition(self._store.member_statements(node, allowed_graph_ids))
            subj = _by_partition(self._store.subject_statements(node, allowed_graph_ids))
            members.append(RetrievedMember(node, subj, inc))
        return members
```

- [ ] **Step 4: 跑测试确认通过** — PASS
- [ ] **Step 5: 提交** — `git commit -m "feat(runtime): RdfGraphRetriever BFS + subject/incident 切片"`

---

### Task 8: ContextCompiler（subject_statements 提字段 + 真实边 + derived 物化 + type-only gap）

**Files:** Create `src/tkos_runtime/application/context_compiler.py`; Test `tests/test_runtime_compiler.py`

- [ ] **Step 1: 写失败测试（含 derived 物化 + type-only gap）**

```python
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
```

- [ ] **Step 2: 跑测试确认失败** — FAIL
- [ ] **Step 3: 实现 context_compiler.py**

```python
# src/tkos_runtime/application/context_compiler.py
from __future__ import annotations
from datetime import datetime
from tkos_runtime.domain.models import (RetrievedMember, ContextPackMember, ContextPack,
    IntentAssessment, ScopeResolution, Omission)
from tkos_runtime.domain.policies import AdmissionPolicy

TKOS = "https://ontology.tokenking.ai/tkos#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
DISPLAY, SCOPE_DESC, SOURCED = TKOS+"displayName", TKOS+"scopeDescription", TKOS+"sourcedFrom"
STATUS, LIFE, VF, VU = TKOS+"hasConfirmationStatus", TKOS+"hasStatus", TKOS+"validFrom", TKOS+"validUntil"
PROOF_PREDS = ("confirmsEntity","supportedClaim","challengesClaim","supersedes",
               "confirmedBy","supportingEvidence","challengingEvidence")


def _frag(u): return str(u).rsplit("#", 1)[-1]


class ContextCompiler:
    def __init__(self, store, policy: AdmissionPolicy):
        self._store, self._policy = store, policy

    def compile(self, members, intent: IntentAssessment, scope: ScopeResolution, metadata: dict,
                as_of: datetime, query: str, purpose: str) -> ContextPack:
        current, candidate, provenance, derived, gaps, omissions = [], [], [], [], [], []
        for m in sorted(members, key=lambda x: x.subject):
            for part in sorted(set(m.subject_by_partition) | set(m.incident_by_partition)):
                subj = m.subject_by_partition.get(part, [])
                decision = self._policy.decide(part, subj, as_of)
                if not decision.accept:
                    omissions.append(Omission(_frag(m.subject), part, decision.stage or "unknown", decision.reason or ""))
                    continue
                view = self._to_member(m, part, m.incident_by_partition.get(part, subj), subj, decision)
                if part == "graph-confirmed-enterprise": current.append(view)
                elif part == "graph-candidate-and-dispute":
                    candidate.append(view)
                    if self._is_gap(subj): gaps.append(view)
                elif part == "graph-decision-provenance": provenance.append(view)
                elif part == "graph-derived-context": derived.append(view)
        reasoning = "materialized_available" if derived else "not_available"
        contributing = sorted({s.source_graph for b in (current, candidate, provenance, derived) for mem in b for s in mem.statements})
        return ContextPack(
            pack_id=f"context-pack-{purpose}", schema_version="context-pack/1.0-draft", as_of=as_of.isoformat(),
            query=query, purpose=purpose, matched_root=intent.root,
            alternative_matches=[{"score":s,"id":i,"name":n} for s,i,n in intent.alternatives],
            scope_resolution=scope, current_facts=current, candidate_context=candidate,
            provenance_context=provenance, proof=self._proof(provenance),
            derived_claims=derived, reasoning_status=reasoning, context_gaps=gaps, conflicts=[],
            omissions=sorted(omissions, key=lambda o:(o.partition,o.subject,o.stage)),
            contributing_graphs=contributing,
            admission_policy=f"purpose={purpose}; read-admission/p0-v1",
            ontology_release_id=metadata["ontology_release_id"], dataset_revision=metadata["dataset_revision"],
            policy_version="read-admission/p0-v1", query_plan_version="bfs-2gram/p0-v1")

    def _is_gap(self, subj_stmts) -> bool:
        # 仅认 rdf:type ContextGap（名称前缀不承担分类）
        return any(s.predicate == RDF_TYPE and s.object.endswith("#ContextGap") for s in subj_stmts)

    def _to_member(self, m, part, incident, subj, decision) -> ContextPackMember:
        def val(pred):
            return next((s.object for s in subj if s.predicate == pred), None)
        scope_v = val(SCOPE_DESC)
        return ContextPackMember(
            id=_frag(m.subject),
            display_name=(val(DISPLAY) or _frag(m.subject)),
            scope=(scope_v if scope_v else None),
            partition=part,
            statements=sorted(incident, key=lambda x:(x.predicate, x.subject, x.object, x.source_graph)),
            source_graphs=sorted({s.source_graph for s in incident}),
            confirmation_status=(_frag(val(STATUS)) if val(STATUS) else None),
            lifecycle=(_frag(val(LIFE)) if val(LIFE) else None),
            valid_from=val(VF), valid_until=val(VU),
            sources=sorted({_frag(s.object) for s in subj if s.predicate == SOURCED}),
            admission=decision)

    def _proof(self, provenance) -> list[dict]:
        # 用真实 subject/object，避免 m.id 篡改方向；按四元组去重排序
        edges = {}
        for mem in provenance:
            for s in mem.statements:
                if any(s.predicate.endswith(p) for p in PROOF_PREDS):
                    key = (s.subject, s.predicate, s.object, s.source_graph)
                    edges.setdefault(key, {"from": _frag(s.subject), "predicate": _frag(s.predicate),
                                            "to": _frag(s.object), "source_graph": s.source_graph})
        return [edges[k] for k in sorted(edges)]
```

- [ ] **Step 4: 跑测试确认通过** — PASS
- [ ] **Step 5: 提交** — `git commit -m "feat(runtime): ContextCompiler（subject_statements 提字段 + 真实边 + derived 物化 + type-only gap）"`

---

### Task 9: ContextPackResolver + 端到端 7 契约

**Files:** Create `src/tkos_runtime/application/context_pack_resolver.py`; Test `tests/test_runtime_context_pack.py`

- [ ] **Step 1: 写端到端失败测试（精确 7 契约）**

```python
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
```

- [ ] **Step 2: 跑测试确认失败** — FAIL
- [ ] **Step 3: 实现 context_pack_resolver.py**

```python
# src/tkos_runtime/application/context_pack_resolver.py
from __future__ import annotations
from datetime import datetime
from tkos_runtime.domain.models import ScopeResolution


class ContextPackResolver:
    def __init__(self, store, intent, retriever, compiler):
        self._store, self._intent, self._retriever, self._compiler = store, intent, retriever, compiler

    def resolve(self, query: str, purpose: str, as_of: datetime, organization_scope: list[str]):
        allowed = self._store.allowed_graphs(purpose)
        assessment = self._intent.resolve(query, allowed)
        members = self._retriever.retrieve(assessment.root, allowed)
        scope = ScopeResolution(list(organization_scope), list(organization_scope),
                                "not_enforced", "instance_organization_assignment_incomplete")
        meta = {"ontology_release_id": self._store.ontology_release_id,
                "dataset_revision": self._store.dataset_revision}
        return self._compiler.compile(members, assessment, scope, meta, as_of, query, purpose)
```

- [ ] **Step 4: 跑测试确认通过** — `python3 -m pytest tests/test_runtime_context_pack.py -v` → PASS（数据细节偏差调实现不放松断言）
- [ ] **Step 5: 提交** — `git commit -m "feat(runtime): ContextPackResolver + 端到端 7 契约 + 聚合敏感隔离"`

---

### Task 10: API 3 Lineage（LineageProof，注入 Store 为 GraphPolicy，无 as_of，多图归属报错）

**Files:** Create `adapters/rdflib_lineage_repository.py`、`application/proof_builder.py`、`application/lineage_resolver.py`; Test `tests/test_runtime_lineage.py`
**Interfaces:** `LineageResolver(repo, graph_policy, builder)`；`graph_policy` 为单参 `GraphPolicy`（**注入 Store**，非 AdmissionPolicy）；`resolve(assertion_id, purpose) -> LineageProof`（**无 as_of**）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_runtime_lineage.py
from pathlib import Path
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from tkos_runtime.adapters.rdflib_lineage_repository import RdfLineageRepository
from tkos_runtime.application.lineage_resolver import LineageResolver
from tkos_runtime.application.proof_builder import ProofBuilder
from tkos_runtime.domain.models import LineageProof

ROOT = Path(__file__).resolve().parents[1]
SCHEMA, DATASET = ROOT/"ontology/schema/tkos-ontology.jsonld", ROOT/"ontology/datasets/tkos-runtime-dataset.trig"
AID = "assertion-product1-mvp-output-week-2026-08-11"

def make():
    s = RdfDatasetStore(SCHEMA, DATASET, sorted((ROOT/"data/instances").glob("*.trig")), release_root=ROOT)
    # 注入 Store 作为单参 GraphPolicy（不是 AdmissionPolicy）
    return LineageResolver(RdfLineageRepository(s), s, ProofBuilder())

def test_lineage_for_stable_id_assertion():
    lp = make().resolve(AID, "decision_preparation")
    assert isinstance(lp, LineageProof)
    assert lp.assertion_id.endswith(AID)
    assert lp.named_graph == "graph-decision-provenance"
    assert lp.source_records and "external_source_identifier" in lp.source_records[0]
    assert lp.asserted_by == "person-liurenhao"
    assert lp.confirmation_status == "Candidate"
    assert lp.supporting == [] and lp.challenging == [] and lp.supersedes == []

def test_lineage_unknown_empty():
    lp = make().resolve("does-not-exist-xyz", "decision_preparation")
    assert lp.source_records == [] and lp.asserted_by is None and lp.named_graph is None

def test_lineage_multi_graph_raises(tmp_path):
    # 自包含 store：同一断言出现在两个事实图 → fetch 必须报错
    import pytest
    (tmp_path/"onto.jsonld").write_text(
        '{"@context":{"owl":"http://www.w3.org/2002/07/owl#","tkos":"https://ontology.tokenking.ai/tkos#"},'
        '"@graph":[{"@id":"https://ontology.tokenking.ai/tkos#","@type":"owl:Ontology","owl:versionInfo":"test"}]}',
        encoding="utf-8")
    (tmp_path/"reg.trig").write_text(
        '@prefix tkos: <https://ontology.tokenking.ai/tkos#> .\n'
        'tkos:graph-registry {\n'
        '  tkos:graph-confirmed-enterprise a tkos:KnowledgeGraphPartition .\n'
        '  tkos:graph-decision-provenance a tkos:KnowledgeGraphPartition .\n'
        '}\n', encoding="utf-8")
    (tmp_path/"multi.trig").write_text(
        '@prefix tkos: <https://ontology.tokenking.ai/tkos#> .\n'
        'tkos:graph-confirmed-enterprise { tkos:assert-x a tkos:AttributedAssertion ; tkos:objectId "assert-x" . }\n'
        'tkos:graph-decision-provenance { tkos:assert-x a tkos:AttributedAssertion ; tkos:objectId "assert-x" . }\n',
        encoding="utf-8")
    s = RdfDatasetStore(tmp_path/"onto.jsonld", tmp_path/"reg.trig", [tmp_path/"multi.trig"], release_root=tmp_path)
    with pytest.raises(ValueError):
        RdfLineageRepository(s).fetch("assert-x", s.allowed_graphs("decision_preparation"))
```

- [ ] **Step 2: 跑测试确认失败** — FAIL
- [ ] **Step 3: 实现三文件**

```python
# src/tkos_runtime/adapters/rdflib_lineage_repository.py
from __future__ import annotations
from tkos_runtime.domain.models import Lineage

TKOS = "https://ontology.tokenking.ai/tkos#"


def _frag(u): return str(u).rsplit("#", 1)[-1]


class RdfLineageRepository:
    def __init__(self, store):
        self._store = store

    def fetch(self, assertion_id: str, allowed_graph_ids: list[str]) -> Lineage:
        subject = assertion_id if assertion_id.startswith("http") else TKOS + assertion_id
        subj = self._store.subject_statements(subject, allowed_graph_ids)
        if not subj:
            return Lineage(subject, None, [], None, None, [], [], [])
        graphs = sorted({s.source_graph for s in subj})
        if len(graphs) > 1:
            raise ValueError(f"assertion {assertion_id} 跨多图 {graphs}；P0 要求单一事实分区")
        def find(pred):
            return next((s.object for s in subj if s.predicate == TKOS + pred), None)
        sources = []
        for s in subj:
            if s.predicate == TKOS + "sourcedFrom":
                ext = self._store.object_value(s.object, TKOS+"externalSourceIdentifier", allowed_graph_ids)
                rec = self._store.object_value(s.object, TKOS+"recordedAt", allowed_graph_ids)
                sources.append({"source": _frag(s.object), "external_source_identifier": ext, "recorded_at": rec})
        ab = find("assertedBy") or find("confirmedByActor")
        return Lineage(
            assertion_id=subject, named_graph=graphs[0], source_records=sources,
            asserted_by=(_frag(ab) if ab else None),
            confirmation_status=(_frag(find("hasConfirmationStatus")) if find("hasConfirmationStatus") else None),
            supporting=[{"to": _frag(s.object)} for s in subj if s.predicate in (TKOS+"supportedClaim", TKOS+"supportingEvidence")],
            challenging=[{"to": _frag(s.object)} for s in subj if s.predicate in (TKOS+"challengesClaim", TKOS+"challengingEvidence")],
            supersedes=[{"to": _frag(s.object)} for s in subj if s.predicate == TKOS+"supersedes"])
```

```python
# src/tkos_runtime/application/proof_builder.py
from __future__ import annotations
from tkos_runtime.domain.models import Lineage, LineageProof


class ProofBuilder:
    def build(self, lineage: Lineage) -> LineageProof:
        return LineageProof(
            assertion_id=lineage.assertion_id, named_graph=lineage.named_graph,
            source_records=lineage.source_records, asserted_by=lineage.asserted_by,
            confirmation_status=lineage.confirmation_status,
            supporting=lineage.supporting, challenging=lineage.challenging, supersedes=lineage.supersedes)
```

```python
# src/tkos_runtime/application/lineage_resolver.py
from __future__ import annotations
from tkos_runtime.domain.models import LineageProof
from tkos_runtime.domain.ports import GraphPolicy, LineageRepository
from tkos_runtime.application.proof_builder import ProofBuilder


class LineageResolver:
    def __init__(self, repo: LineageRepository, graph_policy: GraphPolicy, builder: ProofBuilder):
        self._repo, self._policy, self._builder = repo, graph_policy, builder

    def resolve(self, assertion_id: str, purpose: str) -> LineageProof:   # 无 as_of（完整历史追溯）
        allowed = self._policy.allowed_graphs(purpose)   # 单参 GraphPolicy（Store），不读 repo._store
        return self._builder.build(self._repo.fetch(assertion_id, allowed))
```

- [ ] **Step 4: 跑测试确认通过** — PASS
- [ ] **Step 5: 提交** — `git commit -m "feat(runtime): API 3 Lineage（LineageProof + Store 为 GraphPolicy + 多图归属报错）"`

---

### Task 11: 旧脚本接入 + CI/Makefile（删 SWRL job）

**Files:** Modify `scripts/resolve_issue_context.py`、`Makefile`、`.github/workflows/ci.yml`、`README.md`

- [ ] **Step 1: scripts/resolve_issue_context.py 接入单一来源**

文件顶部新增 `from tkos_runtime.domain import query_plan`，将 `TRAVERSAL = { TKOS.informedBy, ... }` 整块替换为：

```python
TRAVERSAL = {URIRef(p) for p in query_plan.TRAVERSAL}
```

验证：`python3 scripts/resolve_issue_context.py --query '是否在本季度同时完成产品 1.0 上线和灯塔项目交付'`（`URIRef` 已在脚本顶部导入）。

- [ ] **Step 2: Makefile 接入 pytest**

将 `test-pytest` 加入 `.PHONY`，并更新 `test-fast`（五个纯 Python 套件：SHACL、Context Pack、conformance、isomorphism、runtime pytest）：

```make
.PHONY: ... test-pytest
...
test-pytest:
	$(PYTHON) -m pytest tests/test_runtime_*.py -q

test-fast: test-shacl test-context test-conformance test-isomorphism test-pytest
```

- [ ] **Step 3: ci.yml 删除必然失败的 SWRL job**

删除整个 `swrl-openllet:` job（干净 clone 无 `openllet/`，该 job 必然失败；`continue-on-error` 仅是掩饰）。保留 `python-tests` job，并在其后追加：

```yaml
      - name: Runtime pytest (P0 read-only stack)
        run: python -m pytest tests/test_runtime_*.py -q
```

- [ ] **Step 4: README.md 更新「本地验证」与 CI 说明**

将原"GitHub Actions 在推送与 PR 时自动运行纯 Python 套件（必过门禁），SWRL 套件作为信息性 job"改为：纯 Python 套件（含 runtime pytest）为必过门禁；Openllet SWRL 回归（`make test-swrl` / `tests/run_v2_3_swrl_openllet.py`）为**具备 Openllet 环境时的独立发布门禁，不在 CI**（`openllet/` 被 `.gitignore` 排除）。同时把 `make test-fast` 的描述更新为"五个纯 Python 套件"。

- [ ] **Step 5: 跑 make test-fast 确认全绿** — `make test-fast` → 全 PASS
- [ ] **Step 6: 提交**

```bash
git add scripts/resolve_issue_context.py Makefile .github/workflows/ci.yml README.md
git commit -m "chore(runtime): 旧脚本接入 query_plan + CI 删 SWRL job + Makefile/README pytest"
```

---

## Self-Review（v4 自查）

**1. Spec/评审覆盖：** P1.1 LineageResolver 注入 Store 单参 GraphPolicy（test 用 `s` 非 AdmissionPolicy）✓；P1.2 注册表交集（删 Candidate→删除；未知分区不自动授权；双更才进；临时 TriG 测试）✓；P1.3 candidate 边隔离（confirmed 的 supportedByEvidence 允许留 current，仅隔离 evidence-candidate）✓；P1.4 proof 用真实 subject/object + 四元组去重排序 + 精确边断言 ✓；P1.5 release_root 推导 + POSIX 相对路径 + 双 cwd 一致测试 ✓。**v4 新增 P1：** release_root 默认 `parents[2]`（修正 parent.parent 的少上溯，含默认推导测试）✓；`object_value` 加 `_ok` 信任边界 + 稳定排序取第一个（含端口级 restricted-object 测试，与 statements_in 同测）✓；README.md 纳入 Task 11 的 Files 与提交范围 ✓。拍板：TRAVERSAL 扩展集保留 ✓；_is_gap 仅认 type（含两条独立测试）✓；omission 锚点不变 ✓；CI 删 SWRL job ✓。P2：LineageResolver 无 as_of ✓；admission_policy 随 purpose ✓；Lineage 多图归属报错 + **独立负向测试** ✓；无重复 Task 标题（11 个唯一）✓；gap 测试 `if False else` 已清理为 `RDF_TYPE` ✓；Makefile `.PHONY` 含 test-pytest + 注释更新 ✓；`object_value` 多值稳定排序 ✓；聚合敏感隔离测试（Task 9）✓。

**2. Placeholder scan：** 无 TBD/TODO；Task 11 各步给出具体命令与代码。

**3. Type consistency：** `RetrievedMember(subject_by_partition, incident_by_partition)` 一致；`AdmissionPolicy.allowed_graphs(purpose, registered, restricted)`（3 参）与 Store 单参封装一致；`GraphPolicy.allowed_graphs(purpose)`（单参）由 Store 实现，LineageResolver 注入 Store ✓；`ContextPackMember.scope` 一致；`LineageProof` 一致；proof edge 含 `source_graph` 一致。

**实现期注意：** 端到端断言的数据依赖（archived gap 在 omissions、过期 evidence 在 omissions、确认事件精确边）均经只读计算验证可达；若个别字段偏差，调实现不放松断言。
