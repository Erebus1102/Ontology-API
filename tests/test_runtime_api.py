# tests/test_runtime_api.py
"""End-to-end HTTP tests for the FastAPI read server (Phase B).

Exercises POST /v1/context-packs:resolve as a thin adapter over the Phase-A
ContextPackResolver. The happy-path assertions mirror the FE-issue contracts
from tests/test_runtime_context_pack.py (no weakening of Phase-A semantics).

Auth: All business endpoints require ``Authorization: Bearer <TKOS_API_KEY>``
(401 if missing/wrong, 403 if purpose not permitted). Health endpoints
(/health, /ready) are exempt; /version requires auth.
"""
from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from tkos_runtime.api.server import create_app

TKOS = "https://ontology.tokenking.ai/tkos#"
ISSUE = TKOS + "issue-product1-lighthouse-synchronous-delivery"

BASE_REQ = {
    "enterprise_id": "tokenking",
    "organization_scope": [],
    "purpose": "decision_preparation",
    "query": "是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
    "as_of": "2026-08-11T23:59:59+08:00",
    "actor_id": "agent-harness",
}

# shared test API key
_TEST_KEY = "tkos-test-key-2026"


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {_TEST_KEY}"}


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def client_with_auth(monkeypatch):
    """TestClient with TKOS_API_KEY set — all business endpoints get a valid
    Bearer token header."""
    monkeypatch.setenv("TKOS_API_KEY", _TEST_KEY)
    return TestClient(create_app())


# ---------------------------------------------------------------------------
# resolve endpoint tests
# ---------------------------------------------------------------------------

def test_resolve_fe_issue_happy_path(client_with_auth):
    resp = client_with_auth.post(
        "/v1/context-packs:resolve", json=BASE_REQ, headers=_auth_headers()
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["matched_root"] == ISSUE
    assert body["current_facts"] == []
    assert body["candidate_context"]
    assert body["scope_resolution"]["enforcement"] == "not_enforced"
    assert "graph-sensitive-persona" not in body["contributing_graphs"]
    assert body["ontology_release_id"] == "2.4.0"


def test_resolve_unknown_purpose_is_422(client_with_auth):
    bad = dict(BASE_REQ, purpose="bogus_purpose")
    resp = client_with_auth.post(
        "/v1/context-packs:resolve", json=bad, headers=_auth_headers()
    )
    assert resp.status_code == 422, resp.text


def test_resolve_no_intent_match_is_404(client_with_auth):
    # Phase-A GramIntentResolver indexes URI fragments as haystack, so
    # ASCII-letter gibberish can still 2-gram-match. Pure non-letter repeats
    # produce a genuine NoMatchError -> HTTP 404.
    bad = dict(BASE_REQ, query="zzz zzz zzz")
    resp = client_with_auth.post(
        "/v1/context-packs:resolve", json=bad, headers=_auth_headers()
    )
    assert resp.status_code == 404, resp.text


def test_as_of_without_timezone_is_422(client_with_auth):
    """Naive datetimes cannot be compared against timezone-aware instance data."""
    bad = dict(BASE_REQ, as_of="2026-08-11T23:59:59")
    resp = client_with_auth.post(
        "/v1/context-packs:resolve", json=bad, headers=_auth_headers()
    )
    assert resp.status_code == 422, resp.text
    assert "timezone" in resp.json()["detail"].lower()


def test_as_of_with_timezone_is_accepted(client_with_auth):
    """Explicit +08:00 offset is valid."""
    good = dict(BASE_REQ, as_of="2026-08-11T23:59:59+08:00")
    resp = client_with_auth.post(
        "/v1/context-packs:resolve", json=good, headers=_auth_headers()
    )
    assert resp.status_code == 200, resp.text


def test_as_of_zulu_suffix_is_accepted(client_with_auth):
    """Z suffix is normalised to +00:00 (Python 3.9 compat)."""
    good = dict(BASE_REQ, as_of="2026-08-11T15:59:59Z")
    resp = client_with_auth.post(
        "/v1/context-packs:resolve", json=good, headers=_auth_headers()
    )
    assert resp.status_code == 200, resp.text


# ---------------------------------------------------------------------------
# health endpoint tests
# ---------------------------------------------------------------------------

def test_health_always_200():
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"status": "ok"}


def test_health_no_auth_required():
    """Health endpoint must be accessible without auth (kubelet probes)."""
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200, resp.text


def test_ready_200_after_startup():
    """After create_app() returns, store is loaded → /ready should be 200."""
    client = TestClient(create_app())
    resp = client.get("/ready")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "ready"
    assert body["checks"]["store_loaded"] is True
    assert body["checks"]["startup_shacl"] in ("pass", "fail", "skipped")


def test_ready_503_while_not_ready():
    """When _state.ready is False, /ready returns 503.

    create_app() sets _state.ready = True at the end, so we create the app
    normally first, then flip the flag to simulate a not-ready state (e.g.
    graceful-drain scenario).
    """
    from tkos_runtime.api import server
    original = server._state.ready
    client = TestClient(create_app())
    try:
        # simulate not-ready (e.g. draining, SHACL fail)
        server._state.ready = False
        resp = client.get("/ready")
        assert resp.status_code == 503, resp.text
        assert resp.json()["status"] == "not_ready"
    finally:
        server._state.ready = original


def test_version_returns_fingerprints(monkeypatch):
    """GET /version returns ontology/dataset/code fingerprints."""
    monkeypatch.setenv("TKOS_API_KEY", _TEST_KEY)
    monkeypatch.setenv("TKOS_CODE_SHA", "abc123def456")
    client = TestClient(create_app())
    resp = client.get("/version", headers=_auth_headers())
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ontology_release_id"] == "2.4.0"
    assert isinstance(body["dataset_revision"], str) and len(body["dataset_revision"]) > 0
    assert body["code_sha"] == "abc123def456"
    assert body["app_version"] == "0.1.0"
    assert body["renderer_version"].startswith("context-renderer/")
    assert body["query_plan_version"].startswith("bfs-2gram/")
    assert body["policy_version"] == "read-admission/p0-v1"


def test_version_code_sha_unknown_when_not_set(monkeypatch):
    """When TKOS_CODE_SHA is not set, /version returns 'unknown'."""
    monkeypatch.setenv("TKOS_API_KEY", _TEST_KEY)
    # ensure env var is not set
    monkeypatch.delenv("TKOS_CODE_SHA", raising=False)
    client = TestClient(create_app())
    resp = client.get("/version", headers=_auth_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["code_sha"] == "unknown"


def test_version_requires_auth():
    """GET /version without token → 401 (fingerprint leak prevention)."""
    client = TestClient(create_app())
    resp = client.get("/version")
    assert resp.status_code == 401, resp.text


# ---------------------------------------------------------------------------
# auth tests
# ---------------------------------------------------------------------------

def test_resolve_without_token_is_401():
    """No Authorization header → 401."""
    client = TestClient(create_app())
    resp = client.post("/v1/context-packs:resolve", json=BASE_REQ)
    assert resp.status_code == 401, resp.text


def test_resolve_with_wrong_token_is_401(monkeypatch):
    """Wrong API key → 401."""
    monkeypatch.setenv("TKOS_API_KEY", _TEST_KEY)
    client = TestClient(create_app())
    resp = client.post(
        "/v1/context-packs:resolve",
        json=BASE_REQ,
        headers={"Authorization": "Bearer wrong-key"},
    )
    assert resp.status_code == 401, resp.text


def test_resolve_purpose_not_permitted_is_403(monkeypatch):
    """Purpose not in Principal.allowed_purposes → 403."""
    monkeypatch.setenv(
        "TKOS_API_KEYS_JSON",
        '{"k1": {"name": "restricted", "purposes": ["mission_review"]}}',
    )
    client = TestClient(create_app())
    resp = client.post(
        "/v1/context-packs:resolve",
        json=dict(BASE_REQ, purpose="decision_preparation"),
        headers={"Authorization": "Bearer k1"},
    )
    assert resp.status_code == 403, resp.text


def test_resolve_with_valid_token_is_200(monkeypatch):
    """Valid token → 200."""
    monkeypatch.setenv("TKOS_API_KEY", _TEST_KEY)
    client = TestClient(create_app())
    resp = client.post(
        "/v1/context-packs:resolve",
        json=BASE_REQ,
        headers=_auth_headers(),
    )
    assert resp.status_code == 200, resp.text


def test_health_no_auth_required_endpoint():
    """Explicit: /health returns 200 without any auth header."""
    client = TestClient(create_app())
    resp = client.get("/health")
    assert resp.status_code == 200


def test_ready_no_auth_required_endpoint():
    """Explicit: /ready returns 200 without any auth header."""
    client = TestClient(create_app())
    resp = client.get("/ready")
    assert resp.status_code == 200
