# src/tkos_runtime/application/context_pack_resolver.py
from __future__ import annotations
from datetime import datetime
from tkos_runtime.domain.models import ScopeResolution


class ContextPackResolver:
    def __init__(self, store, intent, retriever, compiler):
        self._store, self._intent, self._retriever, self._compiler = store, intent, retriever, compiler

    def resolve(self, query: str, purpose: str, as_of: datetime, organization_scope: list[str],
                principal_scopes: set[str] | None = None):
        # C3: principal_scopes (Principal.allowed_scopes) narrows visible graphs
        # at admission. None = no narrowing (cxo / single-key backward-compat);
        # empty set = cross-tenant fully blocked → intent finds nothing → 404.
        allowed = self._store.allowed_graphs(purpose, principal_scopes)
        assessment = self._intent.resolve(query, allowed)
        members = self._retriever.retrieve(assessment.root, allowed)
        scope = ScopeResolution(list(organization_scope), list(organization_scope),
                                "not_enforced", "instance_organization_assignment_incomplete")
        meta = {"ontology_release_id": self._store.ontology_release_id,
                "dataset_revision": self._store.dataset_revision}
        return self._compiler.compile(members, assessment, scope, meta, as_of, query, purpose)
