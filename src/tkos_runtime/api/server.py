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
  * Naive (timezone-less) ``as_of`` -> HTTP 422.
  * ``NoMatchError`` (no intent match) -> HTTP 404.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

# Auto-load .env for LLM credentials (python-dotenv).
# Gracefully no-op if python-dotenv is not installed or .env is absent.
try:
    from dotenv import load_dotenv
    _ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
    load_dotenv(_ENV_PATH)
except ImportError:
    pass

from fastapi import FastAPI, HTTPException

from tkos_runtime.adapters.gram_intent_resolver import GramIntentResolver
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from tkos_runtime.adapters.rdflib_graph_retriever import RdfGraphRetriever
from tkos_runtime.application.context_compiler import ContextCompiler
from tkos_runtime.application.context_pack_resolver import ContextPackResolver
from tkos_runtime.domain.models import NoMatchError
from tkos_runtime.domain.policies import AdmissionPolicy
from tkos_runtime.api.models import ResolveRequest
from tkos_runtime.adapters.openai_text_polisher import OpenAITextPolisher
from tkos_runtime.api.render_models import RenderRequest
from tkos_runtime.api.serializer import dict_to_pack, pack_to_dict
from tkos_runtime.application.context_renderer import render

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
            as_of = datetime.fromisoformat(req.as_of.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"invalid as_of: {exc}") from exc
        if as_of.tzinfo is None:
            raise HTTPException(
                status_code=422,
                detail="as_of must include a timezone offset (e.g. +08:00 or Z)",
            )
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

    @app.post("/v1/context-packs:render")
    def resolve_and_render(req: RenderRequest) -> dict:
        opts = req.render_options
        # Resolve source pack
        if req.resolve_request is not None:
            rr = req.resolve_request
            try:
                as_of = datetime.fromisoformat(
                    rr.get("as_of", "").replace("Z", "+00:00")
                )
            except ValueError as exc:
                raise HTTPException(
                    status_code=422, detail=f"invalid as_of: {exc}"
                ) from exc
            if as_of.tzinfo is None:
                raise HTTPException(
                    status_code=422,
                    detail="as_of must include a timezone offset (e.g. +08:00 or Z)",
                )
            try:
                pack = resolver.resolve(
                    query=rr.get("query", ""),
                    purpose=rr.get("purpose", "decision_preparation"),
                    as_of=as_of,
                    organization_scope=list(rr.get("organization_scope", [])),
                )
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            except NoMatchError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc
            pack_origin = "server_resolved"
        else:
            try:
                pack = dict_to_pack(req.pack)  # type: ignore[arg-type]
            except Exception as exc:
                raise HTTPException(
                    status_code=422, detail=f"invalid pack: {exc}"
                ) from exc
            pack_origin = "client_supplied"

        # Build polisher for LLM modes
        polisher = None
        if opts.mode in ("llm_with_fallback", "llm_required"):
            try:
                polisher = OpenAITextPolisher()
            except ValueError:
                pass  # creds not configured; render() handles fallback/raise

        try:
            result = render(
                pack,
                mode=opts.mode,
                format=opts.format,
                max_chars=opts.max_chars,
                language=opts.language,
                polisher=polisher,
                pack_origin=pack_origin,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        if opts.include_structured:
            result["structured"] = pack_to_dict(pack)
        return result

    return app


# Module-level app for ``uvicorn tkos_runtime.api.server:app``.
app = create_app()
