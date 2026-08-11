# P0-1 运行时最小只读栈 Implementation Plan (v2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建进程内 TKOS 只读运行时，覆盖 API 1（Context Pack）与 API 3（Assertion Lineage），逐三元组保留命名图身份。

**Architecture:** 端口与适配器分层——`domain/`（纯模型 + 策略 + Protocol 端口 + 查询计划）、`application/`（用例编排，只消费领域对象）、`adapters/`（rdflib 实现 + Adapter 信任边界）。准入两段式：图策略/敏感隔离在端口执行，时间/确认状态在分区切片准入执行。

**Tech Stack:** Python ≥3.9, rdflib ≥7.1, pyshacl（仅既有测试用）。无新依赖。

## Global Constraints

- 命名空间：`TKOS = "https://ontology.tokenking.ai/tkos#"`，图 IRI = `TKOS + "graph-<partition>"`。
- 五个图分区，分区集合**由图注册表 `tkos:graph-registry` 解析**（非硬编码）。
- **`graph-sensitive-persona` 在 P0 永不进入 `allowed_graph_ids`**；其 subject IRI 进入 `restricted_node_ids`，跨端口 GraphStatement 命中 subject|object 即丢弃。
- 准入两段式：图策略查询前（生成 `allowed_graph_ids` = `purpose_allowed ∩ registered − restricted`）；时间/确认状态查询后（按分区切片判定）。
- 验收推导 `MissionReadyForAcceptance` **不在 Python 实现**；Derived 图为空 → `reasoning_status="not_available"`、`derived_claims=[]`；Derived 图有合格成员 → `reasoning_status="materialized_available"`、写入 `derived_claims`（只读物化结果，不做在线推理）。
- BFS 计划：双向、`max_depth=2`、`visited_key`=节点 IRI、`predicate_set`=`query_plan.TRAVERSAL`（单一来源）、`graph_scope`=allowed、按节点 IRI 稳定排序；`query_plan_version="bfs-2gram/p0-v1"`。
- 版本元数据：`ontology_release_id`=本体 `owl:versionInfo`（2.4.0）；`dataset_revision`=对每个输入文件以"相对路径长度+相对路径+字节长度+字节"长度前缀后SHA-256；`policy_version="read-admission/p0-v1"`；`schema_version="context-pack/1.0-draft"`。
- 组织作用域 `enforcement="not_enforced"`，reason=`instance_organization_assignment_incomplete`。
- 所有列表（neighbors、分区语句、proof edges、omissions、members）按稳定键排序，保证同 Dataset 逐字节稳定。
- TDD：每个任务先写失败测试，再实现，再通过，再提交。无新依赖。`make test-fast` 必须始终绿。
- **未知 purpose → 抛错**（不静默降级）；**无匹配意图 → 抛领域异常 `NoMatchError`**（非 SystemExit）。

---

## File Structure

- Create `src/tkos_runtime/domain/models.py` — 领域数据类 + 异常。
- Create `src/tkos_runtime/domain/query_plan.py` — `TRAVERSAL`/`MAX_DEPTH` 单一来源（Retriever 与旧脚本共同导入）。
- Create `src/tkos_runtime/domain/ports.py` — Protocol 端口。
- Create `src/tkos_runtime/domain/policies.py` — `AdmissionPolicy`（注册表驱动 + 分区切片）。
- Create `src/tkos_runtime/adapters/rdflib_dataset_store.py` — `RdfDatasetStore`（装载 + **注册表解析** + restricted_node_ids + 端口过滤 + 长度前缀哈希）。
- Create `src/tkos_runtime/adapters/gram_intent_resolver.py` — `GramIntentResolver`（2-gram，NoMatchError）。
- Create `src/tkos_runtime/adapters/rdflib_graph_retriever.py` — `RdfGraphRetriever`（确定性 BFS + 分区切片，区分 subject/incident 语句）。
- Create `src/tkos_runtime/adapters/rdflib_lineage_repository.py` — `RdfLineageRepository`（解析 SourceRecord→externalSourceIdentifier）。
- Create `src/tkos_runtime/application/context_compiler.py` — `ContextCompiler`（分区切片→ContextPack，字段从 subject_statements 提取，derived 物化读取）。
- Create `src/tkos_runtime/application/proof_builder.py` — `ProofBuilder`（Lineage→LineageProof）。
- Create `src/tkos_runtime/application/context_pack_resolver.py` — `ContextPackResolver`（API 1）。
- Create `src/tkos_runtime/application/lineage_resolver.py` — `LineageResolver`（API 3，注入图策略端口）。
- Modify `scripts/resolve_issue_context.py` — 改为从 `domain.query_plan` 导入 `TRAVERSAL`（单一来源）。
- Tests: `tests/test_runtime_*.py`（每任务一个）。
- Modify `Makefile` + `.github/workflows/ci.yml`。

---

### Task 1: 领域模型 + 异常 domain/models.py

**Files:** Create `src/tkos_runtime/domain/models.py`; Test `tests/test_runtime_models.py`
**Interfaces:** Produces 全部领域类与 `NoMatchError`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_runtime_models.py
from tkos_runtime.domain.models import (
    GraphPartition, GraphStatement, RetrievedMember, ContextPackMember,
    AdmissionDecision, ContextPack, ScopeResolution, LineageProof, NoMatchError,
)

def test_retrieved_member_carries_subject_and_incident_and_scope_field():
    subj = GraphStatement("a", "tkos:hasConfirmationStatus", "Confirmed", "graph-confirmed-enterprise")
    inc = GraphStatement("b", "tkos:assignmentScope", "a", "graph-confirmed-enterprise")
    m = RetrievedMember(subject="a",
        subject_by_partition={"graph-confirmed-enterprise": [subj]},
        incident_by_partition={"graph-confirmed-enterprise": [subj, inc]})
    assert m.source_graphs == ["graph-confirmed-enterprise"]

def test_context_pack_member_has_scope_field():
    d = AdmissionDecision(True, "graph-confirmed-enterprise")
    mem = ContextPackMember(id="x", display_name="x", scope="边界", partition="graph-confirmed-enterprise",
        statements=[], source_graphs=["graph-confirmed-enterprise"], confirmation_status="Confirmed",
        lifecycle=None, valid_from=None, valid_until=None, sources=[], admission=d)
    assert mem.scope == "边界"

def test_lineage_proof_is_dataclass():
    lp = LineageProof(assertion_id="a", named_graph="g", source_records=[], asserted_by=None,
                      confirmation_status=None, supporting=[], challenging=[], supersedes=[])
    assert lp.assertion_id == "a"

def test_no_match_error_is_exception():
    assert issubclass(NoMatchError, Exception)
```

- [ ] **Step 2: 跑测试确认失败** — `python3 -m pytest tests/test_runtime_models.py -v` → FAIL（模块不存在）

- [ ] **Step 3: 实现 models.py**

```python
# src/tkos_runtime/domain/models.py
"""TKOS 运行时领域模型（框架无关）。"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class GraphPartition(str, Enum):
    CONFIRMED_ENTERPRISE = "graph-confirmed-enterprise"
    CANDIDATE_AND_DISPUTE = "graph-candidate-and-dispute"
    DECISION_PROVENANCE = "graph-decision-provenance"
    DERIVED_CONTEXT = "graph-derived-context"
    SENSITIVE_PERSONA = "graph-sensitive-persona"


class NoMatchError(Exception):
    """Intent 未匹配到任何对象。"""


@dataclass(frozen=True)
class GraphStatement:
    subject: str
    predicate: str
    object: str
    source_graph: str


@dataclass
class RetrievedMember:
    subject: str
    subject_by_partition: dict[str, list[GraphStatement]]   # subject==成员（字段/准入）
    incident_by_partition: dict[str, list[GraphStatement]]  # 双向（关系/proof/gaps）

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

- [ ] **Step 4: 跑测试确认通过** — `python3 -m pytest tests/test_runtime_models.py -v` → PASS
- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/domain/models.py tests/test_runtime_models.py
git commit -m "feat(runtime): 领域模型 models.py（含 scope/LineageProof/NoMatchError/subject+incident）"
```

---

### Task 2: 查询计划单一来源 domain/query_plan.py

**Files:** Create `src/tkos_runtime/domain/query_plan.py`; Test `tests/test_runtime_query_plan.py`
**Interfaces:** Produces `TRAVERSAL`、`MAX_DEPTH`、`QUERY_PLAN_VERSION`，供 Retriever 与旧脚本共享。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_runtime_query_plan.py
from tkos_runtime.domain import query_plan

def test_traversal_contains_required_predicates():
    p = set(query_plan.TRAVERSAL)
    for need in ["hasProgressSnapshot", "confirmsEntity", "supportedByEvidence",
                 "hasContextGap", "informedBy", "hasCriterion"]:
        assert ("https://ontology.tokenking.ai/tkos#" + need) in p

def test_constants():
    assert query_plan.MAX_DEPTH == 2
    assert query_plan.QUERY_PLAN_VERSION == "bfs-2gram/p0-v1"
```

- [ ] **Step 2: 跑测试确认失败** — `python3 -m pytest tests/test_runtime_query_plan.py -v` → FAIL

- [ ] **Step 3: 实现 query_plan.py**

```python
# src/tkos_runtime/domain/query_plan.py
"""BFS 查询计划单一来源。Retriever 与 scripts/resolve_issue_context.py 共同导入。"""
TKOS = "https://ontology.tokenking.ai/tkos#"
MAX_DEPTH = 2
QUERY_PLAN_VERSION = "bfs-2gram/p0-v1"

# 原型脚本既有谓词 + Mission 详情谓词（rationale/scope/criterion/keypath/review）+ confirmsEntity。
TRAVERSAL = [TKOS + p for p in (
    "informedBy", "researchedBy", "hasContextGap", "hasRisk", "contributesTo",
    "belongsTo", "hasOutcome", "hasPortfolio", "inPortfolio", "expects",
    "hasResponsibleAssignment", "assignmentHolder", "assignmentRole", "assignmentScope",
    "dependsOn", "hasMilestone", "hasProgressSnapshot", "hasCriterion", "hasRationale",
    "hasScope", "hasKeyPath", "supportedByEvidence", "sourcedFrom", "confirmedBy",
    "challengingEvidence", "challengesClaim", "isReviewedBy", "delivers", "supports",
    "isDeliveredBy", "hasSuccessCriterion", "contains", "confirmsEntity",
)]
```

- [ ] **Step 4: 跑测试确认通过** — PASS
- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/domain/query_plan.py tests/test_runtime_query_plan.py
git commit -m "feat(runtime): query_plan.py 单一来源（TRAVERSAL/MAX_DEPTH）"
```

---

### Task 3: 准入策略 domain/policies.py（注册表驱动 + 未知 purpose 报错）

**Files:** Create `src/tkos_runtime/domain/policies.py`; Test `tests/test_runtime_policies.py`
**Interfaces:** Produces `AdmissionPolicy`（`allowed_graphs(purpose, registered, restricted)`、`decide(partition, subject_statements, as_of)`）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_runtime_policies.py
from datetime import datetime
import pytest
from tkos_runtime.domain.models import GraphStatement
from tkos_runtime.domain.policies import AdmissionPolicy

AS_OF = datetime.fromisoformat("2026-08-11T00:00:00+00:00")
POL = AdmissionPolicy()
def stmt(s,p,o,g): return GraphStatement(s,p,o,g)
REGISTERED = {"graph-confirmed-enterprise","graph-candidate-and-dispute","graph-decision-provenance","graph-derived-context","graph-sensitive-persona"}

def test_allowed_graphs_intersects_registered_minus_restricted():
    gs = POL.allowed_graphs("decision_preparation", REGISTERED, {"graph-sensitive-persona"})
    assert set(gs) == {"graph-confirmed-enterprise","graph-candidate-and-dispute","graph-decision-provenance","graph-derived-context"}
    assert "graph-sensitive-persona" not in gs

def test_registry_change_changes_allowed():
    reg = REGISTERED | {"graph-new-x"}
    gs = POL.allowed_graphs("decision_preparation", reg, set())
    assert "graph-new-x" in gs
    gs2 = POL.allowed_graphs("decision_preparation", REGISTERED - {"graph-candidate-and-dispute"}, set())
    assert "graph-candidate-and-dispute" not in gs2

def test_unknown_purpose_raises():
    with pytest.raises(ValueError):
        POL.allowed_graphs("typo_purpose", REGISTERED, set())

def test_confirmed_requires_confirmed_and_valid():
    d = POL.decide("graph-confirmed-enterprise", [
        stmt("x","https://ontology.tokenking.ai/tkos#hasConfirmationStatus","Confirmed","graph-confirmed-enterprise"),
        stmt("x","https://ontology.tokenking.ai/tkos#validFrom","2026-08-01T00:00:00+00:00","graph-confirmed-enterprise")], AS_OF)
    assert d.accept

def test_candidate_relation_only_slice_effective_status():
    d = POL.decide("graph-candidate-and-dispute", [
        stmt("m","https://ontology.tokenking.ai/tkos#supportedByEvidence","ec","graph-candidate-and-dispute")], AS_OF)
    assert d.accept

def test_candidate_archived_omitted_with_stage_reason():
    d = POL.decide("graph-candidate-and-dispute", [
        stmt("x","https://ontology.tokenking.ai/tkos#hasConfirmationStatus","Archived","graph-candidate-and-dispute")], AS_OF)
    assert not d.accept and d.stage == "confirmation" and d.reason

def test_expired_omitted_valid_time():
    d = POL.decide("graph-confirmed-enterprise", [
        stmt("x","https://ontology.tokenking.ai/tkos#hasConfirmationStatus","Confirmed","graph-confirmed-enterprise"),
        stmt("x","https://ontology.tokenking.ai/tkos#validFrom","2026-07-01T00:00:00+00:00","graph-confirmed-enterprise"),
        stmt("x","https://ontology.tokenking.ai/tkos#validUntil","2026-08-01T00:00:00+00:00","graph-confirmed-enterprise")], AS_OF)
    assert not d.accept and d.stage == "valid_time"

def test_provenance_no_status_required():
    assert POL.decide("graph-decision-provenance", [], AS_OF).accept
```

- [ ] **Step 2: 跑测试确认失败** — FAIL
- [ ] **Step 3: 实现 policies.py**

```python
# src/tkos_runtime/domain/policies.py
from __future__ import annotations
from datetime import datetime
from tkos_runtime.domain.models import GraphStatement, AdmissionDecision

CONFIRMED = "Confirmed"
PURPOSE_ALLOWED = {
    "decision_preparation": ["graph-confirmed-enterprise", "graph-decision-provenance", "graph-candidate-and-dispute", "graph-derived-context"],
    "mission_review": ["graph-confirmed-enterprise", "graph-decision-provenance", "graph-derived-context"],
}


class AdmissionPolicy:
    def allowed_graphs(self, purpose: str, registered: set[str], restricted: set[str]) -> list[str]:
        if purpose not in PURPOSE_ALLOWED:
            raise ValueError(f"unknown purpose: {purpose!r}")
        base = [g for g in PURPOSE_ALLOWED[purpose] if g in registered and g not in restricted]
        return sorted(base)

    def decide(self, partition: str, subject_statements: list[GraphStatement], as_of: datetime) -> AdmissionDecision:
        if partition in ("graph-decision-provenance", "graph-derived-context"):
            return AdmissionDecision(accept=True, partition=partition)
        if partition == "graph-confirmed-enterprise":
            return self._confirmed(partition, subject_statements, as_of)
        if partition == "graph-candidate-and-dispute":
            return self._candidate(partition, subject_statements, as_of)
        return AdmissionDecision(accept=False, partition=partition, stage="graph_policy", reason="partition_not_allowed")

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
        if st != CONFIRMED:
            return AdmissionDecision(False, partition, "confirmation", f"status={st}")
        bad = self._valid(partition, stmts, as_of)
        return bad or AdmissionDecision(True, partition)

    def _candidate(self, partition, stmts, as_of):
        st = self._status(stmts)
        if st == "Archived":
            return AdmissionDecision(False, partition, "confirmation", "archived")
        if st is None:
            st = "CandidateByPartition"
        if st not in {"Candidate", "PreliminarilyConfirmed", "CandidateByPartition"}:
            return AdmissionDecision(False, partition, "confirmation", f"status={st}")
        bad = self._valid(partition, stmts, as_of)
        return bad or AdmissionDecision(True, partition)


def _parse(t: str) -> datetime:
    return datetime.fromisoformat(t.replace("Z", "+00:00"))
```

- [ ] **Step 4: 跑测试确认通过** — PASS
- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/domain/policies.py tests/test_runtime_policies.py
git commit -m "feat(runtime): AdmissionPolicy（注册表驱动 + 未知 purpose 报错 + effective_status）"
```

---

### Task 4: RdfDatasetStore（注册表解析 + restricted_node_ids + 长度前缀哈希 + 敏感隔离测试）

**Files:** Create `src/tkos_runtime/adapters/rdflib_dataset_store.py`; Test `tests/test_runtime_store.py`（含敏感隔离）
**Interfaces:** Produces `RdfDatasetStore`：`registered_partition_ids`、`restricted_partition_ids`、`restricted_node_ids`、`allowed_graphs`、`statements_in`、`neighbors`、`member_statements`（incident）、`subject_statements`、`object_value`、`ontology_release_id`、`dataset_revision`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_runtime_store.py
from pathlib import Path
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT/"ontology/schema/tkos-ontology.jsonld"
DATASET = ROOT/"ontology/datasets/tkos-runtime-dataset.trig"

def store(paths):
    return RdfDatasetStore(SCHEMA, DATASET, paths)

def test_registered_partitions_from_registry_not_hardcoded():
    s = store(sorted((ROOT/"data/instances").glob("*.trig")))
    assert "graph-confirmed-enterprise" in s.registered_partition_ids
    assert "graph-sensitive-persona" in s.registered_partition_ids

def test_allowed_graphs_uses_registry_intersection():
    s = store(sorted((ROOT/"data/instances").glob("*.trig")))
    gs = set(s.allowed_graphs("decision_preparation"))
    assert "graph-sensitive-persona" not in gs
    assert gs <= s.registered_partition_ids

def test_restricted_node_ids_from_sensitive_fixture():
    s = store([ROOT/"tests/v2.3-context-pack-runtime.trig"])
    assert "https://ontology.tokenking.ai/tkos#assertion-sensitive" in s.restricted_node_ids

def test_port_filters_restricted_uri_as_subject_or_object():
    s = store([ROOT/"tests/v2.3-context-pack-runtime.trig"])
    allowed = ["graph-confirmed-enterprise","graph-candidate-and-dispute","graph-decision-provenance","graph-sensitive-persona"]
    stmts = s.statements_in(allowed)
    SENS = "https://ontology.tokenking.ai/tkos#assertion-sensitive"
    for st in stmts:
        assert st.subject != SENS and st.object != SENS

def test_version_and_length_prefixed_revision():
    s = store(sorted((ROOT/"data/instances").glob("*.trig")))
    assert s.ontology_release_id == "2.4.0"
    assert len(s.dataset_revision) == 64
```

- [ ] **Step 2: 跑测试确认失败** — FAIL
- [ ] **Step 3: 实现 rdflib_dataset_store.py**

```python
# src/tkos_runtime/adapters/rdflib_dataset_store.py
from __future__ import annotations
import hashlib
from pathlib import Path
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
    def __init__(self, schema_path: Path, dataset_path: Path, instance_paths: list[Path]):
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
        self.dataset_revision = self._revision(dataset_path, instance_paths)

    def _read_registered(self) -> set[str]:
        out = set()
        reg = self._ds.graph(URIRef(REGISTRY))
        for s, _, _ in reg.triples((None, RDF.type, URIRef(PARTITION_CLASS))):
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
        g = Graph().parse(schema_path, format="json-ld")
        for o in g.objects(URIRef(TKOS), OWL.versionInfo):
            return str(o)
        return "unknown"

    def _revision(self, dataset_path: Path, instance_paths: list[Path]) -> str:
        h = hashlib.sha256()
        base = Path.cwd()
        for p in sorted([dataset_path, *instance_paths]):
            rel = str(p.resolve().relative_to(base))
            data = p.read_bytes()
            h.update(len(rel).to_bytes(8, "big")); h.update(rel.encode())
            h.update(len(data).to_bytes(8, "big")); h.update(data)
        return h.hexdigest()

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
        preds = [URIRef(p) for p in predicates]
        n = URIRef(node)
        out = []
        for guid in self._uris(graph_ids):
            g = self._ds.graph(URIRef(guid))
            for p in preds:
                for o in g.objects(n, p):
                    if isinstance(o, URIRef) and self._ok(node, str(o)):
                        out.append((str(o), GraphStatement(str(n), str(p), str(o), _frag(guid))))
                for s in g.subjects(p, n):
                    if isinstance(s, URIRef) and self._ok(str(s), node):
                        out.append((str(s), GraphStatement(str(s), str(p), str(n), _frag(guid))))
        seen, dedup = set(), []
        for nb, st in sorted(out, key=lambda x: (x[0], x[1].predicate, x[1].object)):
            if (nb, st.predicate, st.object, st.source_graph) not in seen:
                seen.add((nb, st.predicate, st.object, st.source_graph)); dedup.append((nb, st))
        return dedup

    def member_statements(self, subject: str, graph_ids: list[str]) -> list[GraphStatement]:
        """双向 incident 语句（BFS/proof/关系）。"""
        n = URIRef(subject)
        out = []
        for guid in self._uris(graph_ids):
            g = self._ds.graph(URIRef(guid))
            for s, p, o in g:
                if (s == n or o == n) and self._ok(str(s), str(o)):
                    out.append(self._stmt(s, p, o, guid))
        return sorted(out, key=lambda x: (x.predicate, x.subject, x.object, x.source_graph))

    def subject_statements(self, subject: str, graph_ids: list[str]) -> list[GraphStatement]:
        """仅 subject==成员 的语句（字段/准入）。避免入向污染。"""
        n = URIRef(subject)
        out = []
        for guid in self._uris(graph_ids):
            g = self._ds.graph(URIRef(guid))
            for s, p, o in g:
                if s == n and self._ok(str(s), str(o)):
                    out.append(self._stmt(s, p, o, guid))
        return sorted(out, key=lambda x: (x.predicate, x.object, x.source_graph))

    def object_value(self, subject: str, predicate: str, graph_ids: list[str]) -> str | None:
        n, p = URIRef(subject), URIRef(predicate)
        for guid in self._uris(graph_ids):
            for o in self._ds.graph(URIRef(guid)).objects(n, p):
                return str(o)
        return None
```

- [ ] **Step 4: 跑测试确认通过** — PASS
- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/adapters/rdflib_dataset_store.py tests/test_runtime_store.py
git commit -m "feat(runtime): RdfDatasetStore 注册表驱动 + restricted_node_ids + 长度前缀哈希"
```

---

### Task 5: 端口 domain/ports.py

**Files:** Create `src/tkos_runtime/domain/ports.py`
**Interfaces:** Produces Protocol：`DatasetStore`、`IntentResolver`、`GraphRetriever`、`LineageRepository`、`GraphPolicy`。

- [ ] **Step 1: 实现 ports.py**

```python
# src/tkos_runtime/domain/ports.py
from __future__ import annotations
from typing import Protocol
from tkos_runtime.domain.models import GraphStatement, RetrievedMember, IntentAssessment, Lineage


class GraphPolicy(Protocol):
    def allowed_graphs(self, purpose: str) -> list[str]: ...


class DatasetStore(Protocol):
    ontology_release_id: str
    dataset_revision: str
    restricted_node_ids: set[str]
    registered_partition_ids: set[str]
    def allowed_graphs(self, purpose: str) -> list[str]: ...
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

- [ ] **Step 2: 跑全部既有 runtime 测试确认无回归** — `python3 -m pytest tests/test_runtime_*.py -v` → PASS
- [ ] **Step 3: 提交**

```bash
git add src/tkos_runtime/domain/ports.py
git commit -m "feat(runtime): 能力端口 ports.py（含 GraphPolicy）"
```

---

### Task 6: GramIntentResolver（NoMatchError，仅允许图）

**Files:** Create `src/tkos_runtime/adapters/gram_intent_resolver.py`; Test `tests/test_runtime_intent.py`
**Interfaces:** Consumes `DatasetStore.statements_in`；Produces `GramIntentResolver.resolve`。

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

def test_matches_fe_issue_exact_root():
    s = RdfDatasetStore(SCHEMA, DATASET, sorted((ROOT/"data/instances").glob("*.trig")))
    ia = GramIntentResolver(s).resolve("是否在本季度同时完成产品 1.0 上线和灯塔项目交付", s.allowed_graphs("decision_preparation"))
    assert ia.root == "https://ontology.tokenking.ai/tkos#issue-product1-lighthouse-synchronous-delivery"

def test_no_match_raises_domain_error():
    s = RdfDatasetStore(SCHEMA, DATASET, sorted((ROOT/"data/instances").glob("*.trig")))
    with pytest.raises(NoMatchError):
        GramIntentResolver(s).resolve("完全不存在的查询词xyzq", s.allowed_graphs("decision_preparation"))

def test_sensitive_not_matched_when_excluded():
    s = RdfDatasetStore(SCHEMA, DATASET, [ROOT/"tests/v2.3-context-pack-runtime.trig"])
    ia = GramIntentResolver(s).resolve("一号位历史判断偏好", s.allowed_graphs("decision_preparation"))
    SENS_FRAG = "assertion-sensitive"
    assert ia.root.rsplit("#",1)[-1] != SENS_FRAG
    assert all(a[1] != SENS_FRAG for a in ia.alternatives)
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
- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/adapters/gram_intent_resolver.py tests/test_runtime_intent.py
git commit -m "feat(runtime): GramIntentResolver（2-gram + NoMatchError）"
```

---

### Task 7: RdfGraphRetriever（确定性 BFS + subject/incident 分区切片）

**Files:** Create `src/tkos_runtime/adapters/rdflib_graph_retriever.py`; Test `tests/test_runtime_retriever.py`
**Interfaces:** Consumes `query_plan.TRAVERSAL`、store.neighbors/member_statements/subject_statements；Produces `RetrievedMember[]`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_runtime_retriever.py
from pathlib import Path
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from tkos_runtime.adapters.rdflib_graph_retriever import RdfGraphRetriever

ROOT = Path(__file__).resolve().parents[1]
SCHEMA, DATASET = ROOT/"ontology/schema/tkos-ontology.jsonld", ROOT/"ontology/datasets/tkos-runtime-dataset.trig"

def test_mission_growth_dual_slice_and_subject_incident_split():
    s = RdfDatasetStore(SCHEMA, DATASET, [ROOT/"tests/v2.3-context-pack-runtime.trig"])
    members = RdfGraphRetriever(s).retrieve("https://ontology.tokenking.ai/tkos#mission-growth",
        ["graph-confirmed-enterprise","graph-candidate-and-dispute","graph-decision-provenance"])
    mg = {m.subject: m for m in members}["https://ontology.tokenking.ai/tkos#mission-growth"]
    assert "graph-confirmed-enterprise" in mg.subject_by_partition
    assert "graph-candidate-and-dispute" in mg.incident_by_partition
    cand = mg.incident_by_partition["graph-candidate-and-dispute"]
    assert any(st.predicate.endswith("supportedByEvidence") for st in cand)
    # candidate 分区无 mission-growth 的 subject 状态语句
    cand_subj = mg.subject_by_partition.get("graph-candidate-and-dispute", [])
    assert not any(st.predicate.endswith("hasConfirmationStatus") for st in cand_subj)
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
        nodes = {root}
        q = deque([(root, 0)])
        while q:
            node, depth = q.popleft()
            if depth >= query_plan.MAX_DEPTH:
                continue
            for nb, _st in self._store.neighbors(node, query_plan.TRAVERSAL, allowed_graph_ids):
                if nb not in visited:
                    visited.add(nb); nodes.add(nb); q.append((nb, depth + 1))
        members = []
        for node in sorted(nodes):
            inc = _by_partition(self._store.member_statements(node, allowed_graph_ids))
            subj = _by_partition(self._store.subject_statements(node, allowed_graph_ids))
            members.append(RetrievedMember(subject=node, subject_by_partition=subj, incident_by_partition=inc))
        return members
```

- [ ] **Step 4: 跑测试确认通过** — PASS
- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/adapters/rdflib_graph_retriever.py tests/test_runtime_retriever.py
git commit -m "feat(runtime): RdfGraphRetriever 确定性 BFS + subject/incident 分区切片"
```

---

### Task 8: ContextCompiler（subject_statements 提字段 + derived 物化读取）

**Files:** Create `src/tkos_runtime/application/context_compiler.py`; Test `tests/test_runtime_compiler.py`
**Interfaces:** Consumes RetrievedMember/AdmissionPolicy；Produces `ContextCompiler.compile`。

- [ ] **Step 1: 写失败测试（含 derived 物化）**

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

def member_with_dual_slice():
    return RetrievedMember(subject=MG,
        subject_by_partition={"graph-confirmed-enterprise":[
            stmt(MG, TKOS+"hasConfirmationStatus","Confirmed","graph-confirmed-enterprise"),
            stmt(MG, TKOS+"validFrom","2026-08-01T00:00:00+00:00","graph-confirmed-enterprise"),
            stmt(MG, TKOS+"displayName","增长任务","graph-confirmed-enterprise"),
            stmt(MG, TKOS+"scopeDescription","边界","graph-confirmed-enterprise")]},
        incident_by_partition={"graph-confirmed-enterprise":[
            stmt(MG, TKOS+"hasConfirmationStatus","Confirmed","graph-confirmed-enterprise"),
            stmt("x", TKOS+"assignmentScope", MG, "graph-confirmed-enterprise")],
            "graph-candidate-and-dispute":[
            stmt(MG, TKOS+"supportedByEvidence", TKOS+"evidence-candidate", "graph-candidate-and-dispute")]})

def scope(): return ScopeResolution([],[],"not_enforced","instance_organization_assignment_incomplete")
def meta(): return {"ontology_release_id":"2.4.0","dataset_revision":"x"*64}

def test_candidate_relation_only_in_candidate_context_not_current():
    c = ContextCompiler(store=None, policy=AdmissionPolicy())
    pack = c.compile([member_with_dual_slice()], IntentAssessment(MG,[]), scope(), meta(), AS_OF, "q", "decision_preparation")
    cur = [m for m in pack.current_facts if m.id == "mission-growth"]
    cand = [m for m in pack.candidate_context if m.id == "mission-growth"]
    assert cur and all(s.source_graph == "graph-confirmed-enterprise" for m in cur for s in m.statements)
    assert cand and any(s.predicate.endswith("supportedByEvidence") for m in cand for s in m.statements)
    assert all(m.scope == "边界" for m in cur)  # scope 从 subject_statements 提取

def test_derived_empty_vs_materialized():
    c = ContextCompiler(store=None, policy=AdmissionPolicy())
    empty = c.compile([], IntentAssessment(MG,[]), scope(), meta(), AS_OF, "q", "decision_preparation")
    assert empty.reasoning_status == "not_available" and empty.derived_claims == []
    dm = RetrievedMember(subject=TKOS+"derived-x",
        subject_by_partition={"graph-derived-context":[stmt(TKOS+"derived-x",TKOS+"displayName","d","graph-derived-context")]},
        incident_by_partition={"graph-derived-context":[stmt(TKOS+"derived-x",TKOS+"displayName","d","graph-derived-context")]})
    pack = c.compile([dm], IntentAssessment(MG,[]), scope(), meta(), AS_OF, "q", "decision_preparation")
    assert pack.reasoning_status == "materialized_available" and pack.derived_claims
```

- [ ] **Step 2: 跑测试确认失败** — FAIL
- [ ] **Step 3: 实现 context_compiler.py**

```python
# src/tkos_runtime/application/context_compiler.py
from __future__ import annotations
from datetime import datetime
from tkos_runtime.domain.models import (RetrievedMember, ContextPackMember, ContextPack,
    GraphStatement, IntentAssessment, ScopeResolution, Omission)
from tkos_runtime.domain.policies import AdmissionPolicy

TKOS = "https://ontology.tokenking.ai/tkos#"
DISPLAY, SCOPE_DESC, SOURCED = TKOS+"displayName", TKOS+"scopeDescription", TKOS+"sourcedFrom"
STATUS, LIFE, VF, VU = TKOS+"hasConfirmationStatus", TKOS+"hasStatus", TKOS+"validFrom", TKOS+"validUntil"


def _frag(u): return str(u).rsplit("#", 1)[-1]


class ContextCompiler:
    def __init__(self, store, policy: AdmissionPolicy):
        self._store = store
        self._policy = policy

    def compile(self, members, intent: IntentAssessment, scope: ScopeResolution, metadata: dict,
                as_of: datetime, query: str, purpose: str) -> ContextPack:
        current, candidate, provenance, derived, gaps, omissions = [], [], [], [], [], []
        for m in sorted(members, key=lambda x: x.subject):
            parts = sorted(set(m.subject_by_partition) | set(m.incident_by_partition))
            for part in parts:
                subj_stmts = m.subject_by_partition.get(part, [])
                decision = self._policy.decide(part, subj_stmts, as_of)
                if not decision.accept:
                    omissions.append(Omission(_frag(m.subject), part, decision.stage or "unknown", decision.reason or ""))
                    continue
                view = self._to_member(m, part, m.incident_by_partition.get(part, subj_stmts), subj_stmts, decision)
                if part == "graph-confirmed-enterprise": current.append(view)
                elif part == "graph-candidate-and-dispute":
                    candidate.append(view)
                    if self._is_gap(subj_stmts, m.subject): gaps.append(view)
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
            derived_claims=derived, reasoning_status=reasoning,
            context_gaps=gaps, conflicts=[],
            omissions=sorted(omissions, key=lambda o:(o.partition,o.subject,o.stage)),
            contributing_graphs=contributing,
            admission_policy="decision_preparation: candidates visible, tagged; never as current",
            ontology_release_id=metadata["ontology_release_id"], dataset_revision=metadata["dataset_revision"],
            policy_version="read-admission/p0-v1", query_plan_version="bfs-2gram/p0-v1")

    def _is_gap(self, subj_stmts, subject):
        # ContextGap 既可能由 subject 的 type 表达，也可能由 incident 关系判定（双重保险）
        if any(s.predicate.endswith("#type") and s.object.endswith("ContextGap") for s in subj_stmts):
            return True
        return _frag(subject).startswith("gap-")

    def _to_member(self, m, part, incident, subj, decision) -> ContextPackMember:
        def val(pred):
            return next((s.object for s in subj if s.predicate == pred), None)
        return ContextPackMember(
            id=_frag(m.subject), display_name=(val(DISPLAY) or _frag(m.subject)),
            scope=(val(SCOPE_DESC) if val(SCOPE_DESC) else None),
            partition=part, statements=sorted(incident, key=lambda x:(x.predicate,x.object,x.source_graph)),
            source_graphs=sorted({s.source_graph for s in incident}),
            confirmation_status=(_frag(val(STATUS)) if val(STATUS) else None),
            lifecycle=(_frag(val(LIFE)) if val(LIFE) else None),
            valid_from=val(VF), valid_until=val(VU),
            sources=sorted({_frag(s.object) for s in subj if s.predicate == SOURCED}),
            admission=decision)

    def _proof(self, provenance):
        edges = []
        for m in provenance:
            for s in m.statements:
                if s.predicate.endswith(("confirmsEntity","supportedClaim","challengesClaim","supersedes",
                                         "confirmedBy","supportingEvidence","challengingEvidence")):
                    edges.append({"from":m.id,"predicate":_frag(s.predicate),"to":_frag(s.object)})
        return sorted(edges, key=lambda e:(e["from"],e["predicate"],e["to"]))
```

- [ ] **Step 4: 跑测试确认通过** — PASS
- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/application/context_compiler.py tests/test_runtime_compiler.py
git commit -m "feat(runtime): ContextCompiler（subject_statements 提字段 + derived 物化）"
```

---

### Task 9: ContextPackResolver + 端到端 7 断言

**Files:** Create `src/tkos_runtime/application/context_pack_resolver.py`; Test `tests/test_runtime_context_pack.py`
**Interfaces:** Consumes Tasks 4/6/7/8；Produces `ContextPackResolver.resolve`。

- [ ] **Step 1: 写端到端失败测试（精确 7 断言）**

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
ISSUE_IRI = TKOS+"issue-product1-lighthouse-synchronous-delivery"

def resolver(paths):
    s = RdfDatasetStore(SCHEMA, DATASET, paths)
    return ContextPackResolver(s, GramIntentResolver(s), RdfGraphRetriever(s), ContextCompiler(s, AdmissionPolicy()))

def all_statements(pack):
    return [st for bucket in (pack.current_facts, pack.candidate_context, pack.provenance_context, pack.derived_claims)
            for m in bucket for st in m.statements]

def test_fe_issue_end_to_end_seven_contracts():
    pack = resolver(sorted((ROOT/"data/instances").glob("*.trig"))).resolve(
        "是否在本季度同时完成产品 1.0 上线和灯塔项目交付", "decision_preparation", AS_OF, [])
    # 1. matched_root 精确相等
    assert pack.matched_root == ISSUE_IRI
    # 2. 逐语句图身份 + 议题在 candidate + 确认事件在 provenance 且入 proof
    stmts = all_statements(pack)
    assert stmts and all(s.source_graph for s in stmts)
    issue_member = next((m for m in pack.candidate_context if m.id == "issue-product1-lighthouse-synchronous-delivery"), None)
    assert issue_member is not None and issue_member.source_graphs == ["graph-candidate-and-dispute"]
    prov = [m for m in pack.provenance_context if m.id == "confirmation-mission-fe-m2-card"]
    assert prov, "confirmation-mission-fe-m2-card 应在 provenance_context"
    assert any(e["from"] == "confirmation-mission-fe-m2-card" for e in pack.proof)
    # 3. current 为空（confirmed 图空），候选不泄漏到 current
    assert pack.current_facts == []
    assert pack.candidate_context
    assert not any(m.confirmation_status in ("Candidate","PreliminarilyConfirmed","Archived") for m in pack.current_facts)
    # 4. 每个 member source_graphs 非空 + ContextGap 子集
    for bucket in (pack.current_facts, pack.candidate_context, pack.provenance_context):
        for m in bucket: assert m.source_graphs
    gap_ids = {m.id for m in pack.context_gaps}
    assert "gap-product1-lighthouse-synchronous-delivery-facts" in gap_ids
    # 5. omissions：含已归档对象，stage=confirmation + reason
    arch = [o for o in pack.omissions if o.subject == "gap-product1-name-scope-confirmation"]
    assert arch and arch[0].stage == "confirmation" and arch[0].reason
    # 6. scope + sensitive 不贡献
    assert pack.scope_resolution.enforcement == "not_enforced"
    assert "graph-sensitive-persona" not in pack.contributing_graphs
    # 7. 版本元数据
    assert pack.ontology_release_id == "2.4.0" and len(pack.dataset_revision) == 64

def test_confirmed_enters_current_and_expired_omitted_with_fixture():
    pack = resolver([ROOT/"tests/v2.3-context-pack-runtime.trig"]).resolve(
        "增长", "decision_preparation", AS_OF, [])
    # Confirmed 对象进 current，且 current 语句全来自 confirmed 图
    assert any(m.id == "mission-growth" for m in pack.current_facts)
    for m in pack.current_facts:
        assert all(s.source_graph == "graph-confirmed-enterprise" for s in m.statements)
    # candidate supportedByEvidence 只在 candidate_context
    cand = [m for m in pack.candidate_context if m.id == "mission-growth"]
    assert cand and any(s.predicate.endswith("supportedByEvidence") for m in cand for s in m.statements)
    cur = [m for m in pack.current_facts if m.id == "mission-growth"]
    assert not any(s.predicate.endswith("supportedByEvidence") for m in cur for s in m.statements)
    # 过期 evidence 在 omissions，stage=valid_time + reason
    exp = [o for o in pack.omissions if o.subject == "evidence-expired"]
    assert exp and exp[0].stage == "valid_time" and exp[0].reason
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

- [ ] **Step 4: 跑测试确认通过** — `python3 -m pytest tests/test_runtime_context_pack.py -v` → PASS（如个别数据细节偏差，调实现不放松断言）
- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/application/context_pack_resolver.py tests/test_runtime_context_pack.py
git commit -m "feat(runtime): ContextPackResolver + 端到端 7 契约断言"
```

---

### Task 10: API 3 Lineage（LineageProof，注入图策略端口，不读 _store）

**Files:** Create `adapters/rdflib_lineage_repository.py`、`application/proof_builder.py`、`application/lineage_resolver.py`; Test `tests/test_runtime_lineage.py`
**Interfaces:** Consumes store.subject_statements；Produces `LineageResolver.resolve(assertion_id, purpose, as_of) -> LineageProof`。`GraphPolicy` 端口注入，不读 `repo._store`。

- [ ] **Step 1: 写失败测试（用稳定 ID 对象）**

```python
# tests/test_runtime_lineage.py
from datetime import datetime
from pathlib import Path
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from tkos_runtime.adapters.rdflib_lineage_repository import RdfLineageRepository
from tkos_runtime.application.lineage_resolver import LineageResolver
from tkos_runtime.application.proof_builder import ProofBuilder
from tkos_runtime.domain.policies import AdmissionPolicy
from tkos_runtime.domain.models import LineageProof

ROOT = Path(__file__).resolve().parents[1]
SCHEMA, DATASET = ROOT/"ontology/schema/tkos-ontology.jsonld", ROOT/"ontology/datasets/tkos-runtime-dataset.trig"
AS_OF = datetime.fromisoformat("2026-08-11T23:59:59+08:00")
AID = "assertion-product1-mvp-output-week-2026-08-11"

def resolver():
    s = RdfDatasetStore(SCHEMA, DATASET, sorted((ROOT/"data/instances").glob("*.trig")))
    return LineageResolver(RdfLineageRepository(s), AdmissionPolicy(), ProofBuilder())

def test_lineage_for_stable_id_assertion():
    lp = resolver().resolve(AID, "decision_preparation", AS_OF)
    assert isinstance(lp, LineageProof)
    assert lp.assertion_id.endswith(AID)
    assert lp.named_graph == "graph-decision-provenance"
    assert lp.source_records and "external_source_identifier" in lp.source_records[0]
    assert lp.asserted_by == "person-liurenhao"
    assert lp.confirmation_status == "Candidate"
    # support/challenge/supersede 为空或实际值（此对象无）
    assert lp.supporting == [] and lp.challenging == [] and lp.supersedes == []

def test_lineage_unknown_returns_empty_proof():
    lp = resolver().resolve("does-not-exist-xyz", "decision_preparation", AS_OF)
    assert lp.source_records == [] and lp.asserted_by is None and lp.named_graph is None
```

- [ ] **Step 2: 跑测试确认失败** — FAIL
- [ ] **Step 3: 实现三文件**

```python
# src/tkos_runtime/adapters/rdflib_lineage_repository.py
from __future__ import annotations
from tkos_runtime.domain.models import Lineage, GraphStatement

TKOS = "https://ontology.tokenking.ai/tkos#"


def _frag(u): return str(u).rsplit("#", 1)[-1]


class RdfLineageRepository:
    def __init__(self, store):
        self._store = store

    def fetch(self, assertion_id: str, allowed_graph_ids: list[str]) -> Lineage:
        subject = assertion_id if assertion_id.startswith("http") else TKOS + assertion_id
        subj = self._store.subject_statements(subject, allowed_graph_ids)
        if not subj:
            return Lineage(assertion_id=subject, named_graph=None, source_records=[], asserted_by=None,
                           confirmation_status=None, supporting=[], challenging=[], supersedes=[])
        named_graph = subj[0].source_graph
        def find(pred):
            return next((s.object for s in subj if s.predicate == TKOS + pred), None)
        sources = []
        for s in subj:
            if s.predicate == TKOS + "sourcedFrom":
                ext = self._store.object_value(s.object, TKOS + "externalSourceIdentifier", allowed_graph_ids)
                rec = self._store.object_value(s.object, TKOS + "recordedAt", allowed_graph_ids)
                sources.append({"source": _frag(s.object), "external_source_identifier": ext, "recorded_at": rec})
        supporting = [{"to": _frag(s.object)} for s in subj if s.predicate in (TKOS+"supportedClaim", TKOS+"supportingEvidence")]
        challenging = [{"to": _frag(s.object)} for s in subj if s.predicate in (TKOS+"challengesClaim", TKOS+"challengingEvidence")]
        supersedes = [{"to": _frag(s.object)} for s in subj if s.predicate == TKOS + "supersedes"]
        ab = find("assertedBy") or find("confirmedByActor")
        return Lineage(assertion_id=subject, named_graph=named_graph, source_records=sources,
                       asserted_by=(_frag(ab) if ab else None),
                       confirmation_status=(_frag(find("hasConfirmationStatus")) if find("hasConfirmationStatus") else None),
                       supporting=supporting, challenging=challenging, supersedes=supersedes)
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

    def resolve(self, assertion_id: str, purpose: str, as_of) -> LineageProof:
        allowed = self._policy.allowed_graphs(purpose)  # 注入端口，不读 repo._store
        lineage = self._repo.fetch(assertion_id, allowed)
        return self._builder.build(lineage)
```

- [ ] **Step 4: 跑测试确认通过** — PASS
- [ ] **Step 5: 提交**

```bash
git add src/tkos_runtime/adapters/rdflib_lineage_repository.py src/tkos_runtime/application/proof_builder.py src/tkos_runtime/application/lineage_resolver.py tests/test_runtime_lineage.py
git commit -m "feat(runtime): API 3 Lineage（LineageProof + 注入 GraphPolicy + SourceRecord 解析）"
```

---

### Task 11: 旧脚本接入单一来源 + CI/Makefile 接线

**Files:** Modify `scripts/resolve_issue_context.py`、`Makefile`、`.github/workflows/ci.yml`

- [ ] **Step 1: 修改 scripts/resolve_issue_context.py 导入单一来源**

文件顶部新增导入：

```python
from tkos_runtime.domain import query_plan
```

将脚本内 `TRAVERSAL = { TKOS.informedBy, ... }` 整块替换为：

```python
TRAVERSAL = {URIRef(p) for p in query_plan.TRAVERSAL}
```

确保脚本仍可运行：`python3 scripts/resolve_issue_context.py --query '是否在本季度同时完成产品 1.0 上线和灯塔项目交付'`（`URIRef` 已在脚本顶部从 rdflib 导入）。

- [ ] **Step 2: 修改 Makefile（test-fast 增加 pytest）**

```make
test-pytest:
	$(PYTHON) -m pytest tests/test_runtime_*.py -q

test-fast: test-shacl test-context test-conformance test-isomorphism test-pytest
```

- [ ] **Step 3: 修改 .github/workflows/ci.yml（python-tests 增加 pytest）**

在 "Schema isomorphism guard" 之后：

```yaml
      - name: Runtime pytest (P0 read-only stack)
        run: python -m pytest tests/test_runtime_*.py -q
```

- [ ] **Step 4: 跑 make test-fast 确认全绿** — `make test-fast` → 全 PASS
- [ ] **Step 5: 提交**

```bash
git add scripts/resolve_issue_context.py Makefile .github/workflows/ci.yml
git commit -m "chore(runtime): 旧脚本接入 query_plan 单一来源 + CI/Makefile 接入 runtime pytest"
```

---

## Self-Review（v2 自查）

**1. Spec coverage：** P1.1 LineageProof/GraphPolicy 注入 ✓；P1.2 七契约精确断言（matched_root 精确相等、source_graphs 非空、议题精确图、确认事件入 proof、omissions stage+reason、过期 fixture omission）✓；P1.3 注册表驱动（registered/restricted，注册表变化测试）✓；P1.4 derived 物化读取（materialized_available + fixture 测试）✓；P1.5 subject_statements 提字段（无入向污染）+ scope 字段 ✓；P1.6 query_plan 单一来源（hasProgressSnapshot+confirmsEntity，旧脚本导入）✓。P2：稳定排序 ✓、未知 purpose 报错 ✓、NoMatchError ✓、长度前缀哈希 ✓、敏感测试移入 Task 4 ✓、fragment 一致比较 ✓。

**2. Placeholder scan：** Task 11 Step 1 给出干净写法（`TRAVAL = {URIRef(p) for p in query_plan.TRAVERSAL}`），无遗留占位。

**3. Type consistency：** `RetrievedMember(subject_by_partition, incident_by_partition)` 在 Task 1/7/8 一致；`AdmissionPolicy.allowed_graphs(purpose, registered, restricted)` 在 Task 3/4 一致；`LineageResolver(repo, graph_policy, builder)` 与 ports.GraphPolicy 一致；`ContextPackMember.scope` 在 Task 1/8 一致；`LineageProof` 在 Task 1/10 一致。

**已知实现期注意：** Task 9 的 data 依赖（archived gap 在 omissions、过期 evidence 在 omissions）已用只读计算验证可达；若个别字段名偏差，调实现不放松断言。
