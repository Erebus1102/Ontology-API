# src/tkos_runtime/api/server.py
"""FastAPI read-API server (local dev) for API 1 Context Pack.

Thin HTTP adapter over the Phase-A ``ContextPackResolver``. Resolver semantics
are unchanged — this module only:
  * parses the request,
  * calls ``resolver.resolve(...)``,
  * serializes the returned ``ContextPack`` via ``pack_to_dict``,
  * maps domain errors to HTTP status codes.

Error mapping:
  * ``ValueError`` (raised by ``AdmissionPolicy.allowed_graphs`` on unknown
    purpose) -> HTTP 422.
  * ``NoMatchError`` (no intent match) -> HTTP 404.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException

from tkos_runtime.adapters.gram_intent_resolver import GramIntentResolver
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from tkos_runtime.adapters.rdflib_graph_retriever import RdfGraphRetriever
from tkos_runtime.application.context_compiler import ContextCompiler
from tkos_runtime.application.context_pack_resolver import ContextPackResolver
from tkos_runtime.domain.models import NoMatchError
from tkos_runtime.domain.policies import AdmissionPolicy
from tkos_runtime.api.models import ResolveRequest
from tkos_runtime.api.serializer import pack_to_dict

# src/tkos_runtime/api/server.py -> parents[3] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA = _REPO_ROOT / "ontology" / "schema" / "tkos-ontology.jsonld"
_DATASET = _REPO_ROOT / "ontology" / "datasets" / "tkos-runtime-dataset.trig"


def _default_store() -> RdfDatasetStore:
    instance_paths = sorted((_REPO_ROOT / "data" / "instances").glob("*.trig"))
    return RdfDatasetStore(_SCHEMA, _DATASET, instance_paths, release_root=_REPO_ROOT)


def _build_resolver(store: RdfDatasetStore) -> ContextPackResolver:
    intent = GramIntentResolver(store)
    retriever = RdfGraphRetriever(store)
    compiler = ContextCompiler(store, AdmissionPolicy())
    return ContextPackResolver(store, intent, retriever, compiler)


def create_app(store: RdfDatasetStore | None = None) -> FastAPI:
    """Application factory.

    If ``store`` is None, a default ``RdfDatasetStore`` is built from the
    repo-root schema/dataset/instances (same wiring as the Phase-A tests).
    """
    if store is None:
        store = _default_store()
    resolver = _build_resolver(store)
    app = FastAPI(title="TKOS Runtime — Context Pack API", version="0.1.0")

    @app.post("/v1/context-packs:resolve")
    def resolve(req: ResolveRequest) -> dict:
        try:
            as_of = datetime.fromisoformat(req.as_of)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"invalid as_of: {exc}") from exc
        try:
            pack = resolver.resolve(
                query=req.query,
                purpose=req.purpose,
                as_of=as_of,
                organization_scope=list(req.organization_scope),
            )
        except ValueError as exc:
            # AdmissionPolicy.allowed_graphs raises ValueError for unknown purpose.
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except NoMatchError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return pack_to_dict(pack)

    return app


# Module-level app for ``uvicorn tkos_runtime.api.server:app``.
app = create_app()
