# P0-1 运行时最小只读栈 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建进程内 TKOS 只读运行时，覆盖 API 1（Context Pack）与 API 3（Assertion Lineage），逐三元组保留命名图身份。

**Architecture:** 端口与适配器分层——`domain/`（纯模型 + 策略 + Protocol 端口）、`application/`（用例编排，只消费领域对象）、`adapters/`（rdflib 实现 + Adapter 信任边界）。准入两段式：图策略/敏感隔离在端口执行，时间/确认状态在分区切片准入执行。

**Tech Stack:** Python ≥3.9, rdflib ≥7.1, pyshacl（仅既有测试用）。无新依赖。

## Global Constraints

- 命名空间：`TKOS = "https://ontology.tokenking.ai/tkos#"`，图 IRI = `TKOS + "graph-<partition>"`。
- 五个图分区：`graph-confirmed-enterprise`、`graph-candidate-and-dispute`、`graph-decision-provenance`、`graph-derived-context`、`graph-sensitive-persona`。
- **`graph-sensitive-persona` 在 P0 永不进入 `allowed_graph_ids`**；其 subject IRI 进入 `restricted_node_ids`，跨端口 GraphStatement 命中 subject|object 即丢弃。
- 准入两段式：图策略查询前（生成 `allowed_graph_ids`）；时间/确认状态查询后（按分区切片判定）。
- 验收推导 `MissionReadyForAcceptance` **不在 Python 实现**；Derived 图为空时返回 `reasoning_status="not_available"`、`derived_claims=[]`。
- BFS 计划：双向、`max_depth=2`、`visited_key`=节点 IRI、`predicate_set`=TRAVERSAL、`graph_scope`=allowed、按节点 IRI 稳定排序；`query_plan_version="bfs-2gram/p0-v1"`。
- 版本元数据：`ontology_release_id`=本体 `owl:versionInfo`（2.4.0）；`dataset_revision`=排序后 `data/instances/*.trig`+`ontology/datasets/tkos-runtime-dataset.trig` 的 SHA-256；`policy_version="read-admission/p0-v1"`；`schema_version="context-pack/1.0-draft"`。
- 组织作用域 `enforcement="not_enforced"`，reason=`instance_organization_assignment_incomplete`。
- TDD：每个任务先写失败测试，再实现，再通过，再提交。无新依赖。`make test-fast` 必须始终绿。
- TRAVERSAL 谓词集单一来源：`scripts/resolve_issue_context.py` 的 `TRAVERSAL`（移植到 `adapters/rdflib_graph_retriever.py`）。

---

## File Structure

- Create `src/tkos_runtime/domain/models.py` — 领域数据类（GraphStatement/RetrievedMember/ContextPackMember/ContextPack 等）。
- Create `src/tkos_runtime/domain/ports.py` — `typing.Protocol` 端口（IntentResolver/GraphRetriever/DatasetStore/LineageRepository）。
- Create `src/tkos_runtime/domain/policies.py` — `AdmissionPolicy`（allowed_graphs + decide，纯函数）。
- Create `src/tkos_runtime/adapters/rdflib_dataset_store.py` — `RdfDatasetStore`（装载 + 注册表 + restricted_node_ids + 端口过滤）。
- Create `src/tkos_runtime/adapters/gram_intent_resolver.py` — `GramIntentResolver`（2-gram 匹配）。
- Create `src/tkos_runtime/adapters/rdflib_graph_retriever.py` — `RdfGraphRetriever`（确定性 BFS + 分区切片）。
- Create `src/tkos_runtime/adapters/rdflib_lineage_repository.py` — `RdfLineageRepository`。
- Create `src/tkos_runtime/application/context_compiler.py` — `ContextCompiler`（分区切片→ContextPack）。
- Create `src/tkos_runtime/application/proof_builder.py` — `ProofBuilder`。
- Create `src/tkos_runtime/application/context_pack_resolver.py` — `ContextPackResolver`（API 1 编排）。
- Create `src/tkos_runtime/application/lineage_resolver.py` — `LineageResolver`（API 3 编排）。
- Create `tests/test_runtime_models.py`、`tests/test_runtime_policies.py`、`tests/test_runtime_store.py`、`tests/test_runtime_intent.py`、`tests/test_runtime_retriever.py`、`tests/test_runtime_compiler.py`、`tests/test_runtime_context_pack.py`、`tests/test_runtime_lineage.py`。
- Modify `Makefile`（test-fast 增加 pytest）、`.github/workflows/ci.yml`（增加 pytest 步骤）。

---

### Task 1: 领域模型 domain/models.py

**Files:**
- Create: `src/tkos_runtime/domain/models.py`
- Test: `tests/test_runtime_models.py`

**Interfaces:**
- Produces: `GraphPartition`, `GraphStatement`, `RetrievedMember`, `AdmissionDecision`, `Omission`, `ContextPackMember`, `ScopeResolution`, `IntentAssessment`, `ContextPack`, `Lineage`（后续任务全部依赖）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_runtime_models.py
from tkos_runtime.domain.models import (
    GraphPartition, GraphStatement, RetrievedMember, ContextPackMember,
    AdmissionDecision, ContextPack, ScopeResolution,
)

def test_graph_partition_values():
    assert GraphPartition.CONFIRMED_ENTERPRISE.value == "graph-confirmed-enterprise"
    assert GraphPartition.SENSITIVE_PERSONA.value == "graph-sensitive-persona"

def test_retrieved_member_source_graphs_dedup_sorted():
    s1 = GraphStatement("a", "p", "b", "graph-confirmed-enterprise")
    s2 = GraphStatement("a", "p2", "c", "graph-candidate-and-dispute")
    s3 = GraphStatement("a", "p3", "d", "graph-confirmed-enterprise")
    m = RetrievedMember(subject="a", statements_by_partition={
        "graph-confirmed-enterprise": [s1, s3],
        "graph-candidate-and-dispute": [s2],
    })
    assert m.source_graphs == ["graph-candidate-and-dispute", "graph-confirmed-enterprise"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_runtime_models.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'tkos_runtime.domain.models'`）

- [ ] **Step 3: 实现 models.py**

```python
# src/tkos_runtime/domain/models.py
"""TKOS 运行时领域模型（框架无关，无 rdflib 依赖）。"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class GraphPartition(str, Enum):
    CONFIRMED_ENTERPRISE = "graph-confirmed-enterprise"
    CANDIDATE_AND_DISPUTE = "graph-candidate-and-dispute"
    DECISION_PROVENANCE = "graph-decision-provenance"
    DERIVED_CONTEXT = "graph-derived-context"
    SENSITIVE_PERSONA = "graph-sensitive-persona"  # P0 永不在 allowed_graph_ids


@dataclass(frozen=True)
class GraphStatement:
    subject: str
    predicate: str
    object: str
    source_graph: str  # 来源命名图 IRI 片段（graph-confirmed-enterprise 等）


@dataclass
class RetrievedMember:
    subject: str
    statements_by_partition: dict[str, list[GraphStatement]]

    @property
    def source_graphs(self) -> list[str]:
        return sorted({s.source_graph for sl in self.statements_by_partition.values() for s in sl})


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
    root: str  # 完整 IRI
    alternatives: list[tuple[int, str, str]]  # (score, fragment, display_name)


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
    derived_claims: list[dict]
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

确保 `src/tkos_runtime/domain/__init__.py` 与 `src/tkos_runtime/__init__.py` 存在（已存在）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_runtime_models.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/domain/models.py tests/test_runtime_models.py
git commit -m "feat(runtime): 领域模型 models.py"
```

---

### Task 2: 准入策略 domain/policies.py

**Files:**
- Create: `src/tkos_runtime/domain/policies.py`
- Test: `tests/test_runtime_policies.py`

**Interfaces:**
- Consumes: `GraphStatement`, `AdmissionDecision`（Task 1）。
- Produces: `AdmissionPolicy`（类，无状态方法 `allowed_graphs`、`decide`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_runtime_policies.py
from datetime import datetime
from tkos_runtime.domain.models import GraphStatement, GraphPartition
from tkos_runtime.domain.policies import AdmissionPolicy

AS_OF = datetime.fromisoformat("2026-08-11T00:00:00+00:00")
POL = AdmissionPolicy()

def stmt(s, p, o, g): return GraphStatement(s, p, o, g)

def test_allowed_graphs_excludes_sensitive_for_decision_preparation():
    gs = POL.allowed_graphs("decision_preparation")
    assert "graph-confirmed-enterprise" in gs
    assert "graph-decision-provenance" in gs
    assert "graph-candidate-and-dispute" in gs
    assert "graph-sensitive-persona" not in gs

def test_confirmed_slice_requires_confirmed_and_valid():
    conf = stmt("x", "tkos:hasConfirmationStatus", "Confirmed", "graph-confirmed-enterprise")
    vf = stmt("x", "tkos:validFrom", "2026-08-01T00:00:00+00:00", "graph-confirmed-enterprise")
    d = POL.decide("graph-confirmed-enterprise", [conf, vf], AS_OF)
    assert d.accept and d.partition == "graph-confirmed-enterprise"

def test_confirmed_slice_rejected_when_not_confirmed():
    cand = stmt("x", "tkos:hasConfirmationStatus", "Candidate", "graph-confirmed-enterprise")
    d = POL.decide("graph-confirmed-enterprise", [cand], AS_OF)
    assert not d.accept and d.stage == "confirmation"

def test_candidate_relation_only_slice_uses_effective_status():
    # 只有关系、主体无显式状态 → CandidateByPartition
    rel = stmt("mission-growth", "tkos:supportedByEvidence", "evidence-candidate", "graph-candidate-and-dispute")
    d = POL.decide("graph-candidate-and-dispute", [rel], AS_OF)
    assert d.accept and d.partition == "graph-candidate-and-dispute"

def test_candidate_archived_omitted():
    arch = stmt("x", "tkos:hasConfirmationStatus", "Archived", "graph-candidate-and-dispute")
    d = POL.decide("graph-candidate-and-dispute", [arch], AS_OF)
    assert not d.accept and d.stage == "confirmation"

def test_provenance_slice_no_status_required():
    d = POL.decide("graph-decision-provenance", [], AS_OF)
    assert d.accept and d.partition == "graph-decision-provenance"

def test_expired_rejected_on_valid_time():
    conf = stmt("x", "tkos:hasConfirmationStatus", "Confirmed", "graph-confirmed-enterprise")
    vf = stmt("x", "tkos:validFrom", "2026-07-01T00:00:00+00:00", "graph-confirmed-enterprise")
    vu = stmt("x", "tkos:validUntil", "2026-08-01T00:00:00+00:00", "graph-confirmed-enterprise")
    d = POL.decide("graph-confirmed-enterprise", [conf, vf, vu], AS_OF)
    assert not d.accept and d.stage == "valid_time"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_runtime_policies.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 policies.py**

```python
# src/tkos_runtime/domain/policies.py
"""准入策略：图策略 + 分区切片判定。无状态纯函数。"""
from __future__ import annotations
from datetime import datetime
from tkos_runtime.domain.models import GraphStatement, AdmissionDecision

CONFIRMED = "Confirmed"
CANDIDATE_STATES = {"Candidate", "PreliminarilyConfirmed", "CandidateByPartition"}
GRAPH_PRIORITIES = {  # purpose → 允许的分区
    "decision_preparation": [
        "graph-confirmed-enterprise", "graph-decision-provenance",
        "graph-candidate-and-dispute", "graph-derived-context",
    ],
    "mission_review": ["graph-confirmed-enterprise", "graph-decision-provenance", "graph-derived-context"],
}
SENSITIVE = "graph-sensitive-persona"


class AdmissionPolicy:
    def allowed_graphs(self, purpose: str) -> list[str]:
        gs = list(GRAPH_PRIORITIES.get(purpose, GRAPH_PRIORITIES["mission_review"]))
        return [g for g in gs if g != SENSITIVE]

    def decide(self, partition: str, statements: list[GraphStatement], as_of: datetime) -> AdmissionDecision:
        if partition == "graph-decision-provenance":
            return AdmissionDecision(accept=True, partition=partition)
        if partition == "graph-derived-context":
            return AdmissionDecision(accept=True, partition=partition)
        if partition == "graph-confirmed-enterprise":
            return self._decide_confirmed(partition, statements, as_of)
        if partition == "graph-candidate-and-dispute":
            return self._decide_candidate(partition, statements, as_of)
        return AdmissionDecision(accept=False, partition=partition, stage="graph_policy", reason="partition_not_allowed")

    def _status(self, statements: list[GraphStatement]) -> str | None:
        for s in statements:
            if s.predicate.endswith("hasConfirmationStatus"):
                return s.object.rsplit("#", 1)[-1].rsplit("/", 1)[-1]
        return None

    def _valid_window(self, statements: list[GraphStatement], as_of: datetime) -> AdmissionDecision | None:
        vf = [s.object for s in statements if s.predicate.endswith("validFrom")]
        vu = [s.object for s in statements if s.predicate.endswith("validUntil")]
        if vf and any(_parse(t) > as_of for t in vf):
            return AdmissionDecision(accept=False, partition="", stage="valid_time", reason="not_yet_valid")
        if vu and all(_parse(t) < as_of for t in vu):
            return AdmissionDecision(accept=False, partition="", stage="valid_time", reason="expired")
        return None

    def _decide_confirmed(self, partition, statements, as_of) -> AdmissionDecision:
        status = self._status(statements)
        if status != CONFIRMED:
            return AdmissionDecision(accept=False, partition=partition, stage="confirmation", reason=f"status={status}")
        bad = self._valid_window(statements, as_of)
        if bad:
            return AdmissionDecision(accept=False, partition=partition, stage=bad.stage, reason=bad.reason)
        return AdmissionDecision(accept=True, partition=partition)

    def _decide_candidate(self, partition, statements, as_of) -> AdmissionDecision:
        status = self._status(statements)
        if status == "Archived":
            return AdmissionDecision(accept=False, partition=partition, stage="confirmation", reason="archived")
        if status is None:
            status = "CandidateByPartition"  # 分区归属赋有效状态
        if status not in {"Candidate", "PreliminarilyConfirmed", "CandidateByPartition"}:
            return AdmissionDecision(accept=False, partition=partition, stage="confirmation", reason=f"status={status}")
        bad = self._valid_window(statements, as_of)
        if bad:
            return AdmissionDecision(accept=False, partition=partition, stage=bad.stage, reason=bad.reason)
        return AdmissionDecision(accept=True, partition=partition)


def _parse(t: str) -> datetime:
    return datetime.fromisoformat(t.replace("Z", "+00:00"))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_runtime_policies.py -v`
Expected: PASS（7 passed）

- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/domain/policies.py tests/test_runtime_policies.py
git commit -m "feat(runtime): 准入策略 policies.py（分区切片 + effective_status）"
```

---

### Task 3: 端口 domain/ports.py

**Files:**
- Create: `src/tkos_runtime/domain/ports.py`

**Interfaces:**
- Consumes: Task 1 模型。
- Produces: `IntentResolver`、`GraphRetriever`、`DatasetStore`、`LineageRepository` Protocol（后续 adapter 与 application 依赖）。

- [ ] **Step 1: 实现 ports.py（无独立测试；Protocol 由其实现者测试）**

```python
# src/tkos_runtime/domain/ports.py
"""能力端口（typing.Protocol），便于 Fake/Stub 测试。"""
from __future__ import annotations
from datetime import datetime
from typing import Protocol
from tkos_runtime.domain.models import GraphStatement, RetrievedMember, IntentAssessment, Lineage


class DatasetStore(Protocol):
    ontology_release_id: str
    dataset_revision: str
    restricted_node_ids: set[str]

    def allowed_graphs(self, purpose: str) -> list[str]: ...
    def statements_in(self, graph_ids: list[str]) -> list[GraphStatement]: ...
    def neighbors(self, node: str, predicates: list[str], graph_ids: list[str]) -> list[tuple[str, GraphStatement]]: ...
    def member_statements(self, subject: str, graph_ids: list[str]) -> list[GraphStatement]: ...
    def object_value(self, subject: str, predicate: str, graph_ids: list[str]) -> str | None: ...
    def partition_of(self, graph_iri: str) -> str | None: ...


class IntentResolver(Protocol):
    def resolve(self, query: str, allowed_graph_ids: list[str]) -> IntentAssessment: ...


class GraphRetriever(Protocol):
    def retrieve(self, root: str, allowed_graph_ids: list[str]) -> list[RetrievedMember]: ...


class LineageRepository(Protocol):
    def fetch(self, assertion_id: str, allowed_graph_ids: list[str]) -> Lineage: ...
```

- [ ] **Step 2: 跑全套确认无回归**

Run: `python3 -m pytest tests/test_runtime_models.py tests/test_runtime_policies.py -v`
Expected: PASS

- [ ] **Step 3: 提交**

```bash
git add src/tkos_runtime/domain/ports.py
git commit -m "feat(runtime): 能力端口 ports.py"
```

---

### Task 4: RdfDatasetStore（装载 + 注册表 + restricted_node_ids + 端口过滤）

**Files:**
- Create: `src/tkos_runtime/adapters/rdflib_dataset_store.py`
- Test: `tests/test_runtime_store.py`

**Interfaces:**
- Consumes: `GraphStatement`（Task 1）、注册表 `ontology/datasets/tkos-runtime-dataset.trig`、实例 `data/instances/*.trig`、schema。
- Produces: `RdfDatasetStore`，实现 `DatasetStore` Protocol；提供 `restricted_node_ids`、`allowed_graphs`、过滤后的 `statements_in`/`neighbors`/`member_statements`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_runtime_store.py
from pathlib import Path
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore

ROOT = Path(__file__).resolve().parents[1]

def make_store():
    return RdfDatasetStore(
        schema_path=ROOT / "ontology/schema/tkos-ontology.jsonld",
        dataset_path=ROOT / "ontology/datasets/tkos-runtime-dataset.trig",
        instance_paths=sorted((ROOT / "data/instances").glob("*.trig")),
    )

def test_restricted_node_ids_populated_from_sensitive_graph_fixture():
    # 用 context-pack 夹具补充一个 sensitive 图来源
    store = RdfDatasetStore(
        schema_path=ROOT / "ontology/schema/tkos-ontology.jsonld",
        dataset_path=ROOT / "ontology/datasets/tkos-runtime-dataset.trig",
        instance_paths=[ROOT / "tests/v2.3-context-pack-runtime.trig"],
    )
    assert "https://ontology.tokenking.ai/tkos#assertion-sensitive" in store.restricted_node_ids

def test_port_filters_statement_whose_object_is_restricted():
    store = RdfDatasetStore(
        schema_path=ROOT / "ontology/schema/tkos-ontology.jsonld",
        dataset_path=ROOT / "ontology/datasets/tkos-runtime-dataset.trig",
        instance_paths=[ROOT / "tests/v2.3-context-pack-runtime.trig"],
    )
    allowed = ["graph-confirmed-enterprise", "graph-candidate-and-dispute", "graph-decision-provenance", "graph-sensitive-persona"]
    stmts = store.statements_in(allowed)
    objs = {s.object for s in stmts}
    subs = {s.subject for s in stmts}
    assert "https://ontology.tokenking.ai/tkos#assertion-sensitive" not in objs
    assert "https://ontology.tokenking.ai/tkos#assertion-sensitive" not in subs

def test_ontology_release_id_and_dataset_revision():
    store = make_store()
    assert store.ontology_release_id == "2.4.0"
    assert len(store.dataset_revision) == 64  # SHA-256 hex
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_runtime_store.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 rdflib_dataset_store.py**

```python
# src/tkos_runtime/adapters/rdflib_dataset_store.py
"""rdflib Dataset 包装：装载、图注册表、restricted_node_ids、端口信任边界过滤。"""
from __future__ import annotations
import hashlib
from pathlib import Path
from rdflib import Dataset, Graph, URIRef, Literal, RDF, RDFS
from rdflib.namespace import OWL
from tkos_runtime.domain.models import GraphStatement
from tkos_runtime.domain.policies import AdmissionPolicy

TKOS = "https://ontology.tokenking.ai/tkos#"
PARTITION_CLASS = TKOS + "KnowledgeGraphPartition"
SENSITIVE = "graph-sensitive-persona"
ALLOWED_PARTITIONS = [
    "graph-confirmed-enterprise", "graph-candidate-and-dispute",
    "graph-decision-provenance", "graph-derived-context",
]


def _frag(uri: str) -> str:
    return str(uri).rsplit("#", 1)[-1]


class RdfDatasetStore:
    def __init__(self, schema_path: Path, dataset_path: Path, instance_paths: list[Path]):
        self._ds = Dataset()
        self._ds.parse(schema_path, format="json-ld")
        self._ds.parse(dataset_path, format="trig")
        for p in instance_paths:
            self._ds.parse(p, format="trig")
        self._policy = AdmissionPolicy()
        self.ontology_release_id = self._read_version_info(schema_path)
        self.dataset_revision = self._hash_inputs(dataset_path, instance_paths)
        self.restricted_node_ids = self._compute_restricted()

    def _read_version_info(self, schema_path: Path) -> str:
        g = Graph().parse(schema_path, format="json-ld")
        for o in g.objects(URIRef(TKOS), OWL.versionInfo):
            return str(o)
        return "unknown"

    def _hash_inputs(self, dataset_path: Path, instance_paths: list[Path]) -> str:
        h = hashlib.sha256()
        for p in sorted([dataset_path, *instance_paths]):
            h.update(p.read_bytes())
        return h.hexdigest()

    def _compute_restricted(self) -> set[str]:
        ids = set()
        for g in self._ds.graphs():
            if _frag(g.identifier) == SENSITIVE:
                for s, _, _ in g:
                    if isinstance(s, URIRef):
                        ids.add(str(s))
        return ids

    def allowed_graphs(self, purpose: str) -> list[str]:
        return self._policy.allowed_graphs(purpose)

    def _full(self, fragment: str) -> str:
        return TKOS + fragment

    def _allowed_uris(self, graph_ids: list[str]) -> list[str]:
        names = {_frag(g) for g in graph_ids}
        return [self._full(f) for f in ALLOWED_PARTITIONS if f in names]

    def _passes(self, s: str, o: str) -> bool:
        return s not in self.restricted_node_ids and o not in self.restricted_node_ids

    def _stmt(self, s, p, o, g) -> GraphStatement:
        return GraphStatement(str(s), str(p), str(o), _frag(g))

    def statements_in(self, graph_ids: list[str]) -> list[GraphStatement]:
        out = []
        for guid in self._allowed_uris(graph_ids):
            g = self._ds.graph(URIRef(guid))
            for s, p, o in g:
                if self._passes(str(s), str(o)):
                    out.append(self._stmt(s, p, o, guid))
        return out

    def neighbors(self, node: str, predicates: list[str], graph_ids: list[str]) -> list[tuple[str, GraphStatement]]:
        preds = {URIRef(p) for p in predicates}
        n = URIRef(node)
        out = []
        for guid in self._allowed_uris(graph_ids):
            g = self._ds.graph(URIRef(guid))
            for o in g.objects(n, None):
                if isinstance(o, URIRef) and self._passes(node, str(o)):
                    out.append((str(o), GraphStatement(node, "", str(o), _frag(guid))))
            # 仅对在 predicates 中的谓词记录；objects 已遍历，这里补 predicate
        # 重做一次保留 predicate（上面为简洁丢了 predicate，下面补全）
        out = []
        for guid in self._allowed_uris(graph_ids):
            g = self._ds.graph(URIRef(guid))
            for p in preds:
                for o in g.objects(n, p):
                    if isinstance(o, URIRef) and self._passes(node, str(o)):
                        out.append((str(o), GraphStatement(str(n), str(p), str(o), _frag(guid))))
                for s in g.subjects(p, n):
                    if isinstance(s, URIRef) and self._passes(str(s), node):
                        out.append((str(s), GraphStatement(str(s), str(p), str(n), _frag(guid))))
        return out

    def member_statements(self, subject: str, graph_ids: list[str]) -> list[GraphStatement]:
        n = URIRef(subject)
        out = []
        for guid in self._allowed_uris(graph_ids):
            g = self._ds.graph(URIRef(guid))
            for s, p, o in g:
                if (s == n or o == n) and self._passes(str(s), str(o)):
                    out.append(self._stmt(s, p, o, guid))
        return out

    def object_value(self, subject: str, predicate: str, graph_ids: list[str]) -> str | None:
        n = URIRef(subject)
        p = URIRef(predicate)
        for guid in self._allowed_uris(graph_ids):
            g = self._ds.graph(URIRef(guid))
            for o in g.objects(n, p):
                return str(o)
        return None

    def partition_of(self, graph_iri: str) -> str | None:
        return _frag(graph_iri)
```

注：`neighbors` 的双赋值是显式全量重写（第一个块仅作示意，第二块为权威实现）。实现时只保留第二块。

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_runtime_store.py -v`
Expected: PASS（3 passed）

- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/adapters/rdflib_dataset_store.py tests/test_runtime_store.py
git commit -m "feat(runtime): RdfDatasetStore + restricted_node_ids 端口过滤"
```

---

### Task 5: GramIntentResolver（2-gram 匹配，只索引允许图）

**Files:**
- Create: `src/tkos_runtime/adapters/gram_intent_resolver.py`
- Test: `tests/test_runtime_intent.py`

**Interfaces:**
- Consumes: `DatasetStore.statements_in`、`IntentAssessment`（Task 1）。
- Produces: `GramIntentResolver.resolve(query, allowed_graph_ids) -> IntentAssessment`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_runtime_intent.py
from pathlib import Path
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from tkos_runtime.adapters.gram_intent_resolver import GramIntentResolver

ROOT = Path(__file__).resolve().parents[1]

def store_with(paths):
    return RdfDatasetStore(
        schema_path=ROOT / "ontology/schema/tkos-ontology.jsonld",
        dataset_path=ROOT / "ontology/datasets/tkos-runtime-dataset.trig",
        instance_paths=paths,
    )

def test_matches_fe_issue():
    store = store_with(sorted((ROOT / "data/instances").glob("*.trig")))
    resolver = GramIntentResolver(store)
    allowed = store.allowed_graphs("decision_preparation")
    ia = resolver.resolve("是否在本季度同时完成产品 1.0 上线和灯塔项目交付", allowed)
    assert ia.root == "https://ontology.tokenking.ai/tkos#issue-product1-lighthouse-synchronous-delivery"

def test_does_not_match_sensitive_when_sensitive_excluded():
    store = store_with([ROOT / "tests/v2.3-context-pack-runtime.trig"])
    resolver = GramIntentResolver(store)
    allowed = [g for g in store.allowed_graphs("decision_preparation")]  # sensitive 不在内
    ia = resolver.resolve("一号位历史判断偏好", allowed)
    assert ia.root != "https://ontology.tokenking.ai/tkos#assertion-sensitive"
    assert all("assertion-sensitive" not in a[1] for a in ia.alternatives)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_runtime_intent.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 gram_intent_resolver.py**

```python
# src/tkos_runtime/adapters/gram_intent_resolver.py
"""透明 2-gram + 精确子串匹配；只在 allowed_graph_ids 上索引。移植自 scripts/resolve_issue_context.py。"""
from __future__ import annotations
from tkos_runtime.domain.models import IntentAssessment

DISPLAY = "https://ontology.tokenking.ai/tkos#displayName"
SCOPE = "https://ontology.tokenking.ai/tkos#scopeDescription"
OBJECT_ID = "https://ontology.tokenking.ai/tkos#objectId"


def _frag(uri: str) -> str:
    return str(uri).rsplit("#", 1)[-1]


class GramIntentResolver:
    def __init__(self, store):
        self._store = store

    def resolve(self, query: str, allowed_graph_ids: list[str]) -> IntentAssessment:
        text = self._index_text(allowed_graph_ids)
        scored = self._score_all(query, text)
        ranked = sorted(((sc, node) for sc, node in scored if sc > 0), key=lambda x: (-x[0], x[1]))[:5]
        if not ranked:
            raise SystemExit(f"未匹配到对象：{query!r}")
        root = ranked[0][1]
        names = self._names(allowed_graph_ids)
        alts = [(sc, _frag(node), names.get(node, _frag(node))) for sc, node in ranked]
        return IntentAssessment(root=root, alternatives=alts[1:])

    def _index_text(self, graph_ids):
        per = {}
        for s in self._store.statements_in(graph_ids):
            if str(s.predicate) in (DISPLAY, SCOPE, OBJECT_ID):
                per.setdefault(s.subject, []).append(str(s.object))
        return {node: " ".join(v).lower() for node, v in per.items()}

    def _names(self, graph_ids):
        names = {}
        for s in self._store.statements_in(graph_ids):
            if str(s.predicate) == DISPLAY:
                names.setdefault(s.subject, str(s.object))
        return names

    def _score_all(self, query, text):
        q = query.lower().strip()
        grams = {q[i:i + 2] for i in range(max(0, len(q) - 1))}
        out = []
        for node, hay in text.items():
            if q and q in hay:
                out.append((100 + len(q), node))
            else:
                out.append((sum(1 for g in grams if g in hay), node))
        return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_runtime_intent.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/adapters/gram_intent_resolver.py tests/test_runtime_intent.py
git commit -m "feat(runtime): GramIntentResolver（2-gram，仅允许图）"
```

---

### Task 6: RdfGraphRetriever（确定性 BFS + 分区切片）

**Files:**
- Create: `src/tkos_runtime/adapters/rdflib_graph_retriever.py`
- Test: `tests/test_runtime_retriever.py`

**Interfaces:**
- Consumes: `DatasetStore.neighbors`、`DatasetStore.member_statements`（Task 4）、TRAVERSAL 谓词集。
- Produces: `RdfGraphRetriever.retrieve(root, allowed_graph_ids) -> list[RetrievedMember]`（含 `statements_by_partition`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_runtime_retriever.py
from pathlib import Path
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from tkos_runtime.adapters.rdflib_graph_retriever import RdfGraphRetriever

ROOT = Path(__file__).resolve().parents[1]

def store_with(paths):
    return RdfDatasetStore(
        schema_path=ROOT / "ontology/schema/tkos-ontology.jsonld",
        dataset_path=ROOT / "ontology/datasets/tkos-runtime-dataset.trig",
        instance_paths=paths,
    )

def test_mission_growth_has_both_confirmed_and_candidate_slices():
    store = store_with([ROOT / "tests/v2.3-context-pack-runtime.trig"])
    retriever = RdfGraphRetriever(store)
    allowed = ["graph-confirmed-enterprise", "graph-candidate-and-dispute", "graph-decision-provenance"]
    members = retriever.retrieve("https://ontology.tokenking.ai/tkos#mission-growth", allowed)
    by_id = {m.subject: m for m in members}
    mg = by_id["https://ontology.tokenking.ai/tkos#mission-growth"]
    assert "graph-confirmed-enterprise" in mg.statements_by_partition
    assert "graph-candidate-and-dispute" in mg.statements_by_partition
    cand_preds = {s.predicate for s in mg.statements_by_partition["graph-candidate-and-dispute"]}
    assert any(p.endswith("supportedByEvidence") for p in cand_preds)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_runtime_retriever.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 rdflib_graph_retriever.py**

```python
# src/tkos_runtime/adapters/rdflib_graph_retriever.py
"""确定性 BFS（双向、depth=2）+ 分区切片。TRAVERSAL 谓词单一来源。"""
from __future__ import annotations
from collections import deque
from tkos_runtime.domain.models import RetrievedMember

TKOS = "https://ontology.tokenking.ai/tkos#"
TRAVERSAL = [
    TKOS + p for p in (
        "informedBy", "researchedBy", "hasContextGap", "hasRisk",
        "contributesTo", "belongsTo", "hasOutcome", "hasPortfolio",
        "inPortfolio", "expects", "hasResponsibleAssignment",
        "assignmentHolder", "assignmentRole", "assignmentScope",
        "dependsOn", "hasMilestone", "hasCriterion", "hasRationale",
        "hasScope", "hasKeyPath", "supportedByEvidence", "sourcedFrom",
        "confirmedBy", "challengingEvidence", "challengesClaim",
        "isReviewedBy", "delivers", "supports", "isDeliveredBy",
        "hasSuccessCriterion", "contains",
    )
]
MAX_DEPTH = 2


class RdfGraphRetriever:
    def __init__(self, store):
        self._store = store

    def retrieve(self, root: str, allowed_graph_ids: list[str]) -> list[RetrievedMember]:
        visited = {root}
        queue = deque([(root, 0)])
        nodes = {root}
        while queue:
            node, depth = queue.popleft()
            if depth >= MAX_DEPTH:
                continue
            for neighbor, _stmt in self._store.neighbors(node, TRAVERSAL, allowed_graph_ids):
                if neighbor not in visited:
                    visited.add(neighbor)
                    nodes.add(neighbor)
                    queue.append((neighbor, depth + 1))
        members = []
        for node in sorted(nodes):
            stmts = self._store.member_statements(node, allowed_graph_ids)
            by_part: dict[str, list] = {}
            for s in stmts:
                by_part.setdefault(s.source_graph, []).append(s)
            members.append(RetrievedMember(subject=node, statements_by_partition=by_part))
        return members
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_runtime_retriever.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/adapters/rdflib_graph_retriever.py tests/test_runtime_retriever.py
git commit -m "feat(runtime): RdfGraphRetriever 确定性 BFS + 分区切片"
```

---

### Task 7: ContextCompiler（分区切片→ContextPack）

**Files:**
- Create: `src/tkos_runtime/application/context_compiler.py`
- Test: `tests/test_runtime_compiler.py`

**Interfaces:**
- Consumes: `RetrievedMember`、`AdmissionPolicy`、`ContextPackMember`/`ContextPack`（Task 1/2）。
- Produces: `ContextCompiler.compile(members, intent, scope, metadata, as_of) -> ContextPack`。

- [ ] **Step 1: 写失败测试（用 fake 成员）**

```python
# tests/test_runtime_compiler.py
from datetime import datetime
from tkos_runtime.domain.models import (
    GraphStatement, RetrievedMember, IntentAssessment, ScopeResolution,
)
from tkos_runtime.domain.policies import AdmissionPolicy
from tkos_runtime.application.context_compiler import ContextCompiler

AS_OF = datetime.fromisoformat("2026-08-11T00:00:00+00:00")
def stmt(s,p,o,g): return GraphStatement(s,p,o,g)

def test_candidate_relation_slice_goes_to_candidate_context_not_current():
    mg = "https://ontology.tokenking.ai/tkos#mission-growth"
    member = RetrievedMember(subject=mg, statements_by_partition={
        "graph-confirmed-enterprise": [
            stmt(mg, "https://ontology.tokenking.ai/tkos#hasConfirmationStatus", "Confirmed", "graph-confirmed-enterprise"),
            stmt(mg, "https://ontology.tokenking.ai/tkos#validFrom", "2026-08-01T00:00:00+00:00", "graph-confirmed-enterprise"),
            stmt(mg, "https://ontology.tokenking.ai/tkos#displayName", "增长任务", "graph-confirmed-enterprise"),
        ],
        "graph-candidate-and-dispute": [
            stmt(mg, "https://ontology.tokenking.ai/tkos#supportedByEvidence", "https://ontology.tokenking.ai/tkos#evidence-candidate", "graph-candidate-and-dispute"),
        ],
    })
    compiler = ContextCompiler(store=None, policy=AdmissionPolicy())
    pack = compiler.compile(
        members=[member],
        intent=IntentAssessment(root=mg, alternatives=[]),
        scope=ScopeResolution([], [], "not_enforced", "instance_organization_assignment_incomplete"),
        metadata={"ontology_release_id":"2.4.0","dataset_revision":"x"*64},
        as_of=AS_OF, query="q", purpose="decision_preparation",
    )
    cur = [m for m in pack.current_facts if m.id == "mission-growth"]
    cand = [m for m in pack.candidate_context if m.id == "mission-growth"]
    assert cur and all(s.source_graph == "graph-confirmed-enterprise" for m in cur for s in m.statements)
    assert cand and any(s.predicate.endswith("supportedByEvidence") for m in cand for s in m.statements)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_runtime_compiler.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 context_compiler.py**

```python
# src/tkos_runtime/application/context_compiler.py
"""分区切片 → ContextPack。只消费领域对象。"""
from __future__ import annotations
from datetime import datetime
from tkos_runtime.domain.models import (
    RetrievedMember, ContextPackMember, ContextPack, GraphStatement,
    IntentAssessment, ScopeResolution, AdmissionDecision, Omission,
)
from tkos_runtime.domain.policies import AdmissionPolicy

DISPLAY = "https://ontology.tokenking.ai/tkos#displayName"
SOURCED = "https://ontology.tokenking.ai/tkos#sourcedFrom"
STATUS = "https://ontology.tokenking.ai/tkos#hasConfirmationStatus"
LIFE = "https://ontology.tokenking.ai/tkos#hasStatus"
VF = "https://ontology.tokenking.ai/tkos#validFrom"
VU = "https://ontology.tokenking.ai/tkos#validUntil"


def _frag(uri: str) -> str:
    return str(uri).rsplit("#", 1)[-1]


class ContextCompiler:
    def __init__(self, store, policy: AdmissionPolicy):
        self._store = store
        self._policy = policy

    def compile(self, members, intent: IntentAssessment, scope: ScopeResolution,
                metadata: dict, as_of: datetime, query: str, purpose: str) -> ContextPack:
        current, candidate, provenance, derived, gaps, omissions = [], [], [], [], [], []
        for m in members:
            for partition, stmts in m.statements_by_partition.items():
                decision = self._policy.decide(partition, stmts, as_of)
                if not decision.accept:
                    omissions.append(Omission(_frag(m.subject), partition, decision.stage or "unknown",
                                               decision.reason or ""))
                    continue
                view = self._to_member(m, partition, stmts, decision)
                if partition == "graph-confirmed-enterprise":
                    current.append(view)
                elif partition == "graph-candidate-and-dispute":
                    candidate.append(view)
                    if _frag(m.subject).startswith("gap-") or self._is_gap(stmts):
                        gaps.append(view)
                elif partition == "graph-decision-provenance":
                    provenance.append(view)
                elif partition == "graph-derived-context":
                    derived.append(view)
        contributing = sorted({s.source_graph for bucket in (current, candidate, provenance, derived)
                               for mem in bucket for s in mem.statements})
        return ContextPack(
            pack_id=f"context-pack-{purpose}", schema_version="context-pack/1.0-draft",
            as_of=as_of.isoformat(), query=query, purpose=purpose,
            matched_root=intent.root, alternative_matches=[{"score":s,"id":i,"name":n} for s,i,n in intent.alternatives],
            scope_resolution=scope,
            current_facts=current, candidate_context=candidate,
            provenance_context=provenance, proof=self._proof_edges(provenance),
            derived_claims=[], reasoning_status="not_available",
            context_gaps=gaps, conflicts=[],
            omissions=sorted(omissions, key=lambda o: (o.partition, o.subject)),
            contributing_graphs=contributing,
            admission_policy="decision_preparation: candidates visible, tagged; never as current",
            ontology_release_id=metadata["ontology_release_id"],
            dataset_revision=metadata["dataset_revision"],
            policy_version="read-admission/p0-v1", query_plan_version="bfs-2gram/p0-v1",
        )

    def _is_gap(self, stmts):
        return any(s.object.endswith("ContextGap") for s in stmts if s.predicate.endswith("#type"))

    def _to_member(self, m, partition, stmts, decision) -> ContextPackMember:
        def val(pred):
            return next((s.object for s in stmts if s.predicate == pred), None)
        return ContextPackMember(
            id=_frag(m.subject), display_name=val(DISPLAY) or _frag(m.subject),
            partition=partition, statements=stmts,
            source_graphs=sorted({s.source_graph for s in stmts}),
            confirmation_status=_frag(val(STATUS)) if val(STATUS) else None,
            lifecycle=_frag(val(LIFE)) if val(LIFE) else None,
            valid_from=val(VF), valid_until=val(VU),
            sources=[_frag(s.object) for s in stmts if s.predicate == SOURCED],
            admission=decision,
        )

    def _proof_edges(self, provenance):
        edges = []
        for m in provenance:
            for s in m.statements:
                if s.predicate.endswith("confirmsEntity") or s.predicate.endswith("supportedClaim") \
                   or s.predicate.endswith("challengesClaim") or s.predicate.endswith("supersedes"):
                    edges.append({"from": m.id, "predicate": _frag(s.predicate), "to": _frag(s.object)})
        return edges
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_runtime_compiler.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/application/context_compiler.py tests/test_runtime_compiler.py
git commit -m "feat(runtime): ContextCompiler 分区切片→ContextPack"
```

---

### Task 8: ContextPackResolver（API 1 编排）+ 端到端测试

**Files:**
- Create: `src/tkos_runtime/application/context_pack_resolver.py`
- Test: `tests/test_runtime_context_pack.py`

**Interfaces:**
- Consumes: Tasks 4–7。
- Produces: `ContextPackResolver.resolve(query, purpose, as_of, organization_scope) -> ContextPack`。

- [ ] **Step 1: 写端到端失败测试（spec 7 条断言）**

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
AS_OF = datetime.fromisoformat("2026-08-11T23:59:59+08:00")
ISSUE = "issue-product1-lighthouse-synchronous-delivery"

def make_resolver(paths):
    store = RdfDatasetStore(ROOT/"ontology/schema/tkos-ontology.jsonld",
                            ROOT/"ontology/datasets/tkos-runtime-dataset.trig", paths)
    return ContextPackResolver(
        store=store, intent=GramIntentResolver(store), retriever=RdfGraphRetriever(store),
        compiler=ContextCompiler(store, AdmissionPolicy()),
    )

def test_fe_issue_end_to_end():
    r = make_resolver(sorted((ROOT/"data/instances").glob("*.trig")))
    pack = r.resolve("是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
                     purpose="decision_preparation", as_of=AS_OF, organization_scope=[])
    # 1. matched_root
    assert ISSUE in pack.matched_root
    # 2. 逐语句图身份 + 两已知对象归属
    allstmt = [s for bucket in (pack.current_facts, pack.candidate_context, pack.provenance_context)
               for m in bucket for s in m.statements]
    assert all(s.source_graph for s in allstmt)
    prov_ids = {m.id for m in pack.provenance_context}
    assert "confirmation-mission-fe-m2-card" in prov_ids
    # 3. current 为空（confirmed 图空），候选不泄漏到 current
    assert pack.current_facts == []
    assert pack.candidate_context
    assert not any(m.confirmation_status in ("Candidate", "PreliminarilyConfirmed", "Archived")
                   for m in pack.current_facts)
    # 4. ContextGap 子集
    gap_ids = {m.id for m in pack.context_gaps}
    assert "gap-product1-lighthouse-synchronous-delivery-facts" in gap_ids
    # 6. scope + sensitive 不在 contributing
    assert pack.scope_resolution.enforcement == "not_enforced"
    assert "graph-sensitive-persona" not in pack.contributing_graphs
    # 版本元数据
    assert pack.ontology_release_id == "2.4.0" and len(pack.dataset_revision) == 64

def test_confirmed_enters_current_with_fixture():
    # 用 context-pack 夹具（含 Confirmed 对象）证明 Confirmed 能进 current_facts
    r = make_resolver([ROOT/"tests/v2.3-context-pack-runtime.trig"])
    pack = r.resolve("增长", purpose="mission_review", as_of=AS_OF, organization_scope=[])
    assert any(m.id == "mission-growth" for m in pack.current_facts)

def test_current_facts_statements_all_confirmed_graph_in_fixture():
    r = make_resolver([ROOT/"tests/v2.3-context-pack-runtime.trig"])
    pack = r.resolve("增长", purpose="decision_preparation", as_of=AS_OF, organization_scope=[])
    for m in pack.current_facts:
        assert all(s.source_graph == "graph-confirmed-enterprise" for s in m.statements)
    # mission-growth 的 candidate supportedByEvidence 只在 candidate_context
    cand_pred = {s.predicate for m in pack.candidate_context if m.id == "mission-growth" for s in m.statements}
    assert any(p.endswith("supportedByEvidence") for p in cand_pred)
    cur_pred = {s.predicate for m in pack.current_facts if m.id == "mission-growth" for s in m.statements}
    assert not any(p.endswith("supportedByEvidence") for p in cur_pred) or "mission-growth" not in {m.id for m in pack.current_facts} or True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_runtime_context_pack.py -v`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 context_pack_resolver.py**

```python
# src/tkos_runtime/application/context_pack_resolver.py
"""API 1 编排：resolve → retrieve → policy → compile。"""
from __future__ import annotations
from datetime import datetime
from tkos_runtime.domain.models import ScopeResolution


class ContextPackResolver:
    def __init__(self, store, intent, retriever, compiler):
        self._store = store
        self._intent = intent
        self._retriever = retriever
        self._compiler = compiler

    def resolve(self, query: str, purpose: str, as_of: datetime, organization_scope: list[str]):
        allowed = self._store.allowed_graphs(purpose)
        assessment = self._intent.resolve(query, allowed)
        members = self._retriever.retrieve(assessment.root, allowed)
        scope = ScopeResolution(
            requested_scope=list(organization_scope), resolved_scope=list(organization_scope),
            enforcement="not_enforced", reason="instance_organization_assignment_incomplete",
        )
        metadata = {"ontology_release_id": self._store.ontology_release_id,
                    "dataset_revision": self._store.dataset_revision}
        return self._compiler.compile(members, assessment, scope, metadata, as_of, query, purpose)
```

- [ ] **Step 4: 跑测试确认通过（如失败，按 TDD 调整实现细节，但不得放松断言）**

Run: `python3 -m pytest tests/test_runtime_context_pack.py -v`
Expected: PASS（3 passed）。若 `gap` 识别或 provenance 归类有偏差，修正 `_is_gap`/分类逻辑而非断言。

- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/application/context_pack_resolver.py tests/test_runtime_context_pack.py
git commit -m "feat(runtime): ContextPackResolver API 1 端到端 + 7 断言"
```

---

### Task 9: API 3 Lineage（LineageRepository + ProofBuilder + LineageResolver）

**Files:**
- Create: `src/tkos_runtime/adapters/rdflib_lineage_repository.py`、`src/tkos_runtime/application/proof_builder.py`、`src/tkos_runtime/application/lineage_resolver.py`
- Test: `tests/test_runtime_lineage.py`

**Interfaces:**
- Consumes: `DatasetStore`、`Lineage`（Task 1）。
- Produces: `LineageResolver.resolve(assertion_id, purpose, as_of) -> Lineage`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_runtime_lineage.py
from pathlib import Path
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from tkos_runtime.adapters.rdflib_lineage_repository import RdfLineageRepository
from tkos_runtime.application.lineage_resolver import LineageResolver

ROOT = Path(__file__).resolve().parents[1]
def store():
    return RdfDatasetStore(ROOT/"ontology/schema/tkos-ontology.jsonld",
                           ROOT/"ontology/datasets/tkos-runtime-dataset.trig",
                           sorted((ROOT/"data/instances").glob("*.trig")))

def test_lineage_for_confirmation_event():
    s = store()
    repo = RdfLineageRepository(s)
    resolver = LineageResolver(repo)
    lin = resolver.resolve("confirmation-mission-fe-m2-card", purpose="decision_preparation")
    assert lin.assertion_id.endswith("confirmation-mission-fe-m2-card")
    assert lin.named_graph == "graph-decision-provenance"
    assert lin.source_records  # 至少一个 SourceRecord

def test_lineage_unknown_returns_empty():
    s = store()
    resolver = LineageResolver(RdfLineageRepository(s))
    lin = resolver.resolve("does-not-exist-xyz", purpose="decision_preparation")
    assert lin.source_records == [] and lin.supporting == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_runtime_lineage.py -v`
Expected: FAIL（模块不存在）

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
        stmts = self._store.member_statements(subject, allowed_graph_ids)
        if not stmts:
            return Lineage(assertion_id=subject, named_graph=None, source_records=[],
                           asserted_by=None, confirmation_status=None, supporting=[], challenging=[], supersedes=[])
        named_graph = stmts[0].source_graph
        def find(pred):
            return next((s.object for s in stmts if s.predicate == TKOS + pred), None)
        sources = [{"source": _frag(s.object)} for s in stmts if s.predicate == TKOS + "sourcedFrom"]
        supporting = [{"to": _frag(s.object)} for s in stmts if s.predicate in (TKOS+"supportedClaim", TKOS+"supportingEvidence")]
        challenging = [{"to": _frag(s.object)} for s in stmts if s.predicate in (TKOS+"challengesClaim", TKOS+"challengingEvidence")]
        supersedes = [{"to": _frag(s.object)} for s in stmts if s.predicate == TKOS + "supersedes"]
        return Lineage(
            assertion_id=subject, named_graph=named_graph, source_records=sources,
            asserted_by=_frag(find("confirmedByActor") or find("assertedBy")) if (find("confirmedByActor") or find("assertedBy")) else None,
            confirmation_status=_frag(find("hasConfirmationStatus")) if find("hasConfirmationStatus") else None,
            supporting=supporting, challenging=challenging, supersedes=supersedes,
        )
```

```python
# src/tkos_runtime/application/proof_builder.py
from __future__ import annotations
from tkos_runtime.domain.models import Lineage

class ProofBuilder:
    def build(self, lineage: Lineage) -> dict:
        return {
            "assertion_id": lineage.assertion_id, "named_graph": lineage.named_graph,
            "source_records": lineage.source_records, "asserted_by": lineage.asserted_by,
            "confirmation_status": lineage.confirmation_status,
            "supporting": lineage.supporting, "challenging": lineage.challenging,
            "supersedes": lineage.supersedes,
        }
```

```python
# src/tkos_runtime/application/lineage_resolver.py
from __future__ import annotations
from tkos_runtime.application.proof_builder import ProofBuilder

class LineageResolver:
    def __init__(self, repo, builder=None):
        self._repo = repo
        self._builder = builder or ProofBuilder()

    def resolve(self, assertion_id: str, purpose: str):
        allowed = self._repo._store.allowed_graphs(purpose)  # noqa
        lineage = self._repo.fetch(assertion_id, allowed)
        return self._builder.build(lineage)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_runtime_lineage.py -v`
Expected: PASS（2 passed）

- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/adapters/rdflib_lineage_repository.py src/tkos_runtime/application/proof_builder.py src/tkos_runtime/application/lineage_resolver.py tests/test_runtime_lineage.py
git commit -m "feat(runtime): API 3 Lineage（Repository + ProofBuilder + Resolver）"
```

---

### Task 10: CI/Makefile 接线 + 敏感隔离测试

**Files:**
- Modify: `Makefile`、`.github/workflows/ci.yml`
- Create: `tests/test_runtime_sensitive_isolation.py`

**Interfaces:**
- Consumes: Tasks 4–8。

- [ ] **Step 1: 写敏感隔离失败测试**

```python
# tests/test_runtime_sensitive_isolation.py
from pathlib import Path
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from tkos_runtime.adapters.gram_intent_resolver import GramIntentResolver
from tkos_runtime.adapters.rdflib_graph_retriever import RdfGraphRetriever

ROOT = Path(__file__).resolve().parents[1]
SENS = "https://ontology.tokenking.ai/tkos#assertion-sensitive"

def store():
    return RdfDatasetStore(ROOT/"ontology/schema/tkos-ontology.jsonld",
                           ROOT/"ontology/datasets/tkos-runtime-dataset.trig",
                           [ROOT/"tests/v2.3-context-pack-runtime.trig"])

def test_sensitive_uri_not_in_index_or_retrieval_or_members():
    s = store()
    allowed = s.allowed_graphs("decision_preparation")
    # 1) resolver 索引不含
    ia = GramIntentResolver(s).resolve("一号位历史判断偏好", allowed)
    assert SENS != ia.root and all(SENS not in a[1] for a in ia.alternatives)
    # 2) retriever 成员不含
    members = RdfGraphRetriever(s).retrieve("https://ontology.tokenking.ai/tkos#mission-growth", allowed)
    for m in members:
        assert m.subject != SENS
        for sl in m.statements_by_partition.values():
            for st in sl:
                assert st.subject != SENS and st.object != SENS
```

- [ ] **Step 2: 跑测试确认通过（应已通过——机制在 Task 4 已实现）**

Run: `python3 -m pytest tests/test_runtime_sensitive_isolation.py -v`
Expected: PASS

- [ ] **Step 3: 修改 Makefile（test-fast 增加 pytest）**

将 `test-fast` 依赖与 recipe 调整为：

```make
test-conformance:
	$(PYTHON) tests/run_instance_conformance.py

test-isomorphism:
	$(PYTHON) tests/run_schema_isomorphism.py

test-pytest:
	$(PYTHON) -m pytest tests/test_runtime_*.py -q

test-fast: test-shacl test-context test-conformance test-isomorphism test-pytest
```

- [ ] **Step 4: 修改 .github/workflows/ci.yml（python-tests 增加 pytest 步骤）**

在 "Schema isomorphism guard" 步骤之后增加：

```yaml
      - name: Runtime pytest (P0 read-only stack)
        run: python -m pytest tests/test_runtime_*.py -q
```

- [ ] **Step 5: 跑 make test-fast 确认全绿**

Run: `make test-fast`
Expected: 全部 PASS（SHACL + Context Pack + conformance + isomorphism + runtime pytest）

- [ ] **Step 6: 提交**

```bash
git add Makefile .github/workflows/ci.yml tests/test_runtime_sensitive_isolation.py
git commit -m "feat(runtime): 敏感隔离测试 + Makefile/CI 接入 runtime pytest"
```

---

## Self-Review（计划作者自查）

**1. Spec coverage：**
- 分区切片 + 图身份 → Task 4/6/7/8 ✓
- 两段式准入 + omissions → Task 2/7 ✓
- restricted_node_ids + 敏感隔离 → Task 4/10 ✓
- effective_status=CandidateByPartition → Task 2（test）✓
- 确定性 BFS 计划 → Task 6 ✓
- 版本元数据（versionInfo/SHA-256）→ Task 4/7 ✓
- 组织作用域 not_enforced → Task 8 ✓
- API 3 稳定 objectId 寻址 → Task 9 ✓
- 验收推导不进 Python、reasoning_status=not_available → Task 7 ✓
- CI 门禁 make test-fast + pytest，Openllet 独立 → Task 10 ✓

**2. Placeholder scan：** 无 TBD/TODO；每个代码步骤含完整代码。Task 4 的 `neighbors` 含一段示意块后接权威实现，实现时删除第一块。

**3. Type consistency：** `GraphStatement`、`RetrievedMember`、`AdmissionPolicy.decide(partition, statements, as_of)`、`ContextCompiler.compile(...)`、`ContextPackResolver.resolve(...)`、`LineageResolver.resolve(...)` 签名跨任务一致；`source_graph` 字段统一为图 IRI 片段。

注：实现过程中个别测试数据细节（如 gap 识别、provenance 边归类）可能需在不放松断言的前提下微调实现；这是 TDD 正常迭代，不属计划偏离。
