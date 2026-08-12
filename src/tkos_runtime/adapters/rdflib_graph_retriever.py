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
