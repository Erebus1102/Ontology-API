# tests/test_runtime_api.py
"""End-to-end HTTP tests for the FastAPI read server (Phase B).

Exercises POST /v1/context-packs:resolve as a thin adapter over the Phase-A
ContextPackResolver. The happy-path assertions mirror the FE-issue contracts
from tests/test_runtime_context_pack.py (no weakening of Phase-A semantics).
"""
from __future__ import annotations

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


def test_resolve_fe_issue_happy_path():
    client = TestClient(create_app())
    resp = client.post("/v1/context-packs:resolve", json=BASE_REQ)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["matched_root"] == ISSUE
    assert body["current_facts"] == []
    assert body["candidate_context"]
    assert body["scope_resolution"]["enforcement"] == "not_enforced"
    assert "graph-sensitive-persona" not in body["contributing_graphs"]
    assert body["ontology_release_id"] == "2.4.0"


def test_resolve_unknown_purpose_is_422():
    client = TestClient(create_app())
    bad = dict(BASE_REQ, purpose="bogus_purpose")
    resp = client.post("/v1/context-packs:resolve", json=bad)
    assert resp.status_code == 422, resp.text


def test_resolve_no_intent_match_is_404():
    client = TestClient(create_app())
    # Phase-A GramIntentResolver indexes URI fragments as haystack, so
    # ASCII-letter gibberish can still 2-gram-match. Pure non-letter repeats
    # produce a genuine NoMatchError -> HTTP 404.
    bad = dict(BASE_REQ, query="zzz zzz zzz")
    resp = client.post("/v1/context-packs:resolve", json=bad)
    assert resp.status_code == 404, resp.text


def test_as_of_without_timezone_is_422():
    """Naive datetimes cannot be compared against timezone-aware instance data."""
    client = TestClient(create_app())
    bad = dict(BASE_REQ, as_of="2026-08-11T23:59:59")
    resp = client.post("/v1/context-packs:resolve", json=bad)
    assert resp.status_code == 422, resp.text
    assert "timezone" in resp.json()["detail"].lower()


def test_as_of_with_timezone_is_accepted():
    """Explicit +08:00 offset is valid."""
    client = TestClient(create_app())
    good = dict(BASE_REQ, as_of="2026-08-11T23:59:59+08:00")
    resp = client.post("/v1/context-packs:resolve", json=good)
    assert resp.status_code == 200, resp.text


def test_as_of_zulu_suffix_is_accepted():
    """Z suffix is normalised to +00:00 (Python 3.9 compat)."""
    client = TestClient(create_app())
    good = dict(BASE_REQ, as_of="2026-08-11T15:59:59Z")
    resp = client.post("/v1/context-packs:resolve", json=good)
    assert resp.status_code == 200, resp.text
