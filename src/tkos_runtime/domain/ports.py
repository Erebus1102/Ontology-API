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


class TextPolisher(Protocol):
    """LLM 语言润色端口。只改写文本流畅性，不得改变事实、分区或锚点。"""
    def polish(self, text: str, language: str) -> str: ...
    """返回润色后文本；失败必须抛异常（由调用方决定降级策略）。"""
