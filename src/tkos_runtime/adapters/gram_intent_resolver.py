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
