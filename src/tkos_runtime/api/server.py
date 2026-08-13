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
  * ``NoMatchError`` (knowledge gap / low-confidence gate) -> HTTP 404 with
    structured detail ``{code: ontology_context_not_found, query,
    unmatched_terms, alternatives: [], suggested_action: submit_context_gap}``.
  * ``ContextRootMissingError`` (compile-time integrity failure) -> HTTP 500
    ``{code: context_root_missing, matched_root, stage}`` — never falls back
    to an unrelated issue.
"""
from __future__ import annotations

import logging
import os
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

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse

from tkos_runtime.adapters.gram_intent_resolver import GramIntentResolver
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from tkos_runtime.adapters.rdflib_graph_retriever import RdfGraphRetriever
from tkos_runtime.application.context_compiler import ContextCompiler
from tkos_runtime.application.context_pack_resolver import ContextPackResolver
from tkos_runtime.domain.models import (
    AmbiguousMatchError, ContextRootMissingError, NoMatchError,
)
from tkos_runtime.domain.policies import AdmissionPolicy
from tkos_runtime.api.models import ResolveRequest
from tkos_runtime.adapters.openai_text_polisher import OpenAITextPolisher
from tkos_runtime.api.render_models import RenderRequest
from tkos_runtime.api.serializer import dict_to_pack, pack_to_dict
from tkos_runtime.application.context_renderer import render
from tkos_runtime.domain.render_units import RenderBudgetTooSmall

# authN/authZ (deployment blockers B2)
from tkos_runtime.api.auth import (
    Principal,
    _load_credentials,
    assert_purpose,
    require_token,
)


def _knowledge_gap_404(exc: NoMatchError, query: str) -> HTTPException:
    """P0: 知识不足响应（用户审定的 schema）——与编译期完整性错误严格
    区分：NoMatchError 是匹配层的"知识未命中"（404），ContextRootMissingError
    是编译期的完整性错误（500，绝不 fallback）。

    P1: alternatives 由 exc.candidates 填充（门禁后候选建议；英文/中文
    知识否决与 constrain 池空各按候选池契约提供 baseline[:5]）。"""
    return HTTPException(status_code=404, detail={
        "code": "ontology_context_not_found",
        "query": query,
        "unmatched_terms": list(exc.unmatched_terms),
        "alternatives": [
            {"score": s, "id": i, "name": n}
            for s, i, n, _t, _me in exc.candidates
        ],
        "suggested_action": "submit_context_gap",
    })


def _ambiguous_409(exc: AmbiguousMatchError, query: str) -> HTTPException:
    """P1: 歧义响应（用户审定的严格规则）——top1/top2 有效维度完全并列
    → 拒绝猜测（无 IRI 兜底）；candidates = 完整并列集（不受 top5 截断）。

    P1.1: 每项候选附 type（本体主类型短名）与 matched_evidence
    （name/scope 的 CJK gram 匹配明细）——同分候选靠类型与证据位置
    支撑 Agent 消歧（"模型选择"：barrier 证据全在 scope）。"""
    return HTTPException(status_code=409, detail={
        "code": "ontology_context_ambiguous", "query": query,
        "candidates": [
            {"score": s, "id": i, "name": n,
             "type": t, "matched_evidence": me}
            for s, i, n, t, me in exc.candidates
        ],
        "suggested_action": "disambiguate_query"})

# version constants for /version fingerprint aggregation
from tkos_runtime.application.context_renderer import RENDERER_VERSION
from tkos_runtime.domain.query_plan import QUERY_PLAN_VERSION

# src/tkos_runtime/api/server.py -> parents[3] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA = _REPO_ROOT / "ontology" / "schema" / "tkos-ontology.jsonld"
_DATASET = _REPO_ROOT / "ontology" / "datasets" / "tkos-runtime-dataset.trig"
_SHAPES = _REPO_ROOT / "ontology" / "shapes" / "tkos-validation-shapes.jsonld"


# ---------------------------------------------------------------------------
# runtime state for health / readiness probes (deployment blockers B1)
# ---------------------------------------------------------------------------

class _RuntimeState:
    """Per-worker runtime state for health/readiness probes."""
    ready: bool = False
    startup_shacl_status: str = "skipped"  # "pass" | "fail" | "skipped"


_state = _RuntimeState()


# ---------------------------------------------------------------------------
# store construction
# ---------------------------------------------------------------------------

def _is_sensitive_instance(path: Path) -> bool:
    """Heuristic: filename contains 'sensitive' or 'persona' (O(1))."""
    name = path.name.lower()
    return "sensitive" in name or "persona" in name


def _default_store() -> RdfDatasetStore:
    instance_paths = sorted((_REPO_ROOT / "data" / "instances").glob("*.trig"))
    # B.4: exclude sensitive partition instances unless explicitly opted in
    if os.environ.get("TKOS_INCLUDE_SENSITIVE", "0") != "1":
        instance_paths = [p for p in instance_paths if not _is_sensitive_instance(p)]
    return RdfDatasetStore(_SCHEMA, _DATASET, instance_paths, release_root=_REPO_ROOT)


def _build_resolver(store: RdfDatasetStore) -> ContextPackResolver:
    intent = GramIntentResolver(store)
    retriever = RdfGraphRetriever(store)
    compiler = ContextCompiler(store, AdmissionPolicy())
    return ContextPackResolver(store, intent, retriever, compiler)


# ---------------------------------------------------------------------------
# startup SHACL gate
# ---------------------------------------------------------------------------

def _run_startup_shacl_if_enabled(store: RdfDatasetStore) -> str:
    """Run pyshacl at startup if ``TKOS_STARTUP_SHACL=1``.

    Returns ``"pass"``, ``"fail"``, or ``"skipped"``.

    Defense-in-depth (deployment design §5.1): re-validate the loaded graph
    locally before the Pod accepts traffic — CI already gates publishes, this
    catches a corrupted image at startup. Fails closed: any validation error
    → ``"fail"`` (do not accept traffic over an unvalidated graph).
    """
    if os.environ.get("TKOS_STARTUP_SHACL") != "1":
        return "skipped"
    try:
        from pyshacl import validate as shacl_validate
        from rdflib import Graph

        shapes = Graph().parse(str(_SHAPES), format="json-ld")
        ontology = Graph().parse(str(_SCHEMA), format="json-ld")
        merged = Graph()
        # Union of all loaded graphs (schema + dataset + instances) — the same
        # materialised view the store serves, mirroring run_instance_conformance.
        for graph in store._ds.graphs():
            for triple in graph:
                merged.add(triple)
        conforms, _, _ = shacl_validate(
            data_graph=merged,
            shacl_graph=shapes,
            ont_graph=ontology,
            inference="rdfs",
            advanced=True,
        )
        return "pass" if conforms else "fail"
    except Exception as exc:  # noqa: BLE001 — fail closed on any validation error
        logging.getLogger(__name__).warning("startup SHACL failed: %s", exc)
        return "fail"


# ---------------------------------------------------------------------------
# health / readiness / version handlers
# ---------------------------------------------------------------------------

def _register_health_routes(app: FastAPI, store: RdfDatasetStore) -> None:
    """Register GET /health, /ready, /version on *app*."""

    @app.get("/health")
    async def health() -> dict:
        """Liveness probe — unconditionally 200."""
        return {"status": "ok"}

    @app.get("/ready")
    async def ready():
        """Readiness probe — 200 when Store loaded + optional SHACL pass."""
        if _state.ready:
            return {
                "status": "ready",
                "checks": {
                    "store_loaded": True,
                    "startup_shacl": _state.startup_shacl_status,
                },
            }
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "reason": (
                    "store_loading"
                    if _state.startup_shacl_status == "skipped"
                    else "startup_shacl_failed"
                ),
            },
        )

    @app.get("/version")
    async def version(
        principal: Principal = Depends(require_token),
    ) -> dict:
        """Version fingerprint — requires auth (prevents fingerprint leak)."""
        code_sha = os.environ.get("TKOS_CODE_SHA", "unknown")
        ds_rev = getattr(store, "dataset_revision", "unknown")
        return {
            "ontology_release_id": getattr(store, "ontology_release_id", "unknown"),
            "dataset_revision": ds_rev[:16] if isinstance(ds_rev, str) else "unknown",
            "code_sha": code_sha,
            "policy_version": "read-admission/p0-v1",
            "query_plan_version": QUERY_PLAN_VERSION,
            "renderer_version": RENDERER_VERSION,
            "app_version": app.version,
        }


# ---------------------------------------------------------------------------
# application factory
# ---------------------------------------------------------------------------

def create_app(store: RdfDatasetStore | None = None) -> FastAPI:
    """Application factory.

    If ``store`` is None, a default ``RdfDatasetStore`` is built from the
    repo-root schema/dataset/instances (same wiring as the Phase-A tests).
    """
    if store is None:
        store = _default_store()
    resolver = _build_resolver(store)
    app = FastAPI(title="TKOS Runtime — Context Pack API", version="0.1.0")

    # ── auth: load credentials onto app state ──
    app.state.principals = _load_credentials()

    # ── readiness: run optional startup SHACL, then set ready ──
    _state.startup_shacl_status = _run_startup_shacl_if_enabled(store)
    _state.ready = (_state.startup_shacl_status != "fail")

    # ── health routes (before business endpoints) ──
    _register_health_routes(app, store)

    @app.post("/v1/context-packs:resolve")
    def resolve(
        req: ResolveRequest,
        principal: Principal = Depends(require_token),
    ) -> dict:
        assert_purpose(req.purpose, principal)
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
            raise _knowledge_gap_404(exc, req.query) from exc
        except AmbiguousMatchError as exc:
            raise _ambiguous_409(exc, req.query) from exc
        return pack_to_dict(pack)

    @app.post("/v1/context-packs:render")
    def resolve_and_render(
        req: RenderRequest,
        principal: Principal = Depends(require_token),
    ) -> dict:
        opts = req.render_options
        # Resolve source pack
        if req.resolve_request is not None:
            rr = req.resolve_request
            # authZ: validate purpose on the resolved request
            assert_purpose(
                rr.get("purpose", "decision_preparation"), principal
            )
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
                raise _knowledge_gap_404(exc, rr.get("query", "")) from exc
            except AmbiguousMatchError as exc:
                raise _ambiguous_409(exc, rr.get("query", "")) from exc
            pack_origin = "server_resolved"
        else:
            try:
                pack = dict_to_pack(req.pack)  # type: ignore[arg-type]
            except Exception as exc:
                raise HTTPException(
                    status_code=422, detail=f"invalid pack: {exc}"
                ) from exc
            # authZ: purpose gate must cover client-supplied packs too — the
            # pack declares its own purpose; verify the principal may use it.
            assert_purpose(pack.purpose, principal)
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
        except RenderBudgetTooSmall as exc:
            raise HTTPException(status_code=422, detail={
                "code": "render_budget_too_small",
                "requested_max_chars": exc.requested_max_chars,
                "minimum_required_chars": exc.minimum_required_chars,
            }) from exc
        except ContextRootMissingError as exc:
            # P0-2: 编译期完整性错误 = 运行时 500，绝不 fallback 到无关对象。
            raise HTTPException(status_code=500, detail={
                "code": "context_root_missing",
                "matched_root": exc.matched_root,
                "stage": exc.stage,
            }) from exc
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
