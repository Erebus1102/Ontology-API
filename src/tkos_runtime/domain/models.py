# src/tkos_runtime/domain/models.py
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class NoMatchError(Exception):
    """Intent 未匹配到任何对象（低置信度门禁拒绝或零命中）。

    ``unmatched_terms`` 携带查询中完全不存在于知识库的关键词
    （P0 门禁：英文完整 token 全索引缺失），供 API 层构造
    ``ontology_context_not_found`` 响应。
    """

    def __init__(self, message: str, unmatched_terms: list[str] | None = None,
                 match_reasons: list[str] | None = None,
                 candidates: list[tuple[int, str, str]] | None = None):
        super().__init__(message)
        self.unmatched_terms = list(unmatched_terms or [])
        self.match_reasons = list(match_reasons or [])
        # (score, id_fragment, display_name)——P1：404 建议候选（门禁后）。
        self.candidates = list(candidates or [])


class AmbiguousMatchError(Exception):
    """Intent 匹配歧义：top1/top2 有效维度（exact_match、name_evidence、
    effective_score）完全并列 → API 层 409 ``ontology_context_ambiguous``。

    严格规则：得分与名称证据均无并列分离 → 拒绝猜测（无 IRI 兜底）。
    ``candidates`` = 完整 role_ranked 上的**全部并列项**（不受 top5 截断）。
    """

    def __init__(self, message: str,
                 candidates: list[tuple[int, str, str]]):
        super().__init__(message)
        self.candidates = list(candidates)


class ContextRootMissingError(Exception):
    """编译期完整性错误：matched_root 未进入最终视图或与输出不一致。

    这是运行时完整性错误（API 映射 500），与匹配层"知识未命中"
    （NoMatchError → 404）严格区分，绝不 fallback 到无关对象。
    """

    def __init__(self, message: str, matched_root: str | None = None,
                 stage: str = "decision_context_compilation"):
        super().__init__(message)
        self.matched_root = matched_root
        self.stage = stage


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
    rdf_types: list[str] = field(default_factory=list)


@dataclass
class ScopeResolution:
    requested_scope: list[str]
    resolved_scope: list[str]
    enforcement: str
    reason: str


@dataclass(frozen=True)
class IntentFacets:
    """P1 意图切面。entity: 归一化实体串（空格连接，无则 None）；
    requested_role: risk|progress|issue|None；operation: list|status|None。"""
    entity: str | None
    requested_role: str | None
    operation: str | None


@dataclass
class IntentAssessment:
    root: str
    alternatives: list[tuple[int, str, str]]
    intent_facets: IntentFacets | None = None


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
    intent_facets: dict | None = None
