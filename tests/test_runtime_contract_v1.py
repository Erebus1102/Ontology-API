# tests/test_runtime_contract_v1.py
"""B1 v1-contract convergence tests for POST /v1/context-packs:resolve.

Covers the 2.0 v1 request shape:
  * scenario (enum-validated against the registry in docs/mvp/01 §5) derives
    purpose; unknown scenario -> 422 {code: unknown_scenario}
  * purpose derived from scenario + Key default_scenario (C1 Principal)
  * legacy fields (enterprise_id/organization_scope/purpose/actor_id) are
    still accepted during the deprecation transition (transition red line).
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from tkos_runtime.api.server import create_app

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
# v1 resolve shape tests
# ---------------------------------------------------------------------------

def test_resolve_v1_shape_with_scenario(client_with_auth):
    r = client_with_auth.post(
        "/v1/context-packs:resolve",
        headers=_auth_headers(),
        json={"query": "灯塔项目有哪些风险",
              "as_of": "2026-08-11T00:00:00+08:00",
              "scenario": "strategic_research"},
    )
    assert r.status_code == 200, r.text
    # scenario-derived purpose flows into the Pack (B1: 记录进 Pack)
    assert r.json()["purpose"] == "decision_preparation"


def test_resolve_legacy_fields_still_accepted(client_with_auth):
    r = client_with_auth.post(
        "/v1/context-packs:resolve",
        headers=_auth_headers(),
        json={"enterprise_id": "tk",
              "purpose": "decision_preparation",
              "query": "灯塔项目有哪些风险",
              "as_of": "2026-08-11T00:00:00+08:00"},
    )
    assert r.status_code == 200, r.text   # 旧字段过渡期仍 200（B.5 红线）


def test_resolve_unknown_scenario_is_422(client_with_auth):
    r = client_with_auth.post(
        "/v1/context-packs:resolve",
        headers=_auth_headers(),
        json={"query": "灯塔项目有哪些风险",
              "as_of": "2026-08-11T00:00:00+08:00",
              "scenario": "no-such-scenario"},
    )
    assert r.status_code == 422
    assert r.json()["detail"]["code"] == "unknown_scenario"


def test_resolve_key_default_scenario_derives_purpose(monkeypatch):
    """No scenario and no purpose in the request -> purpose derived from the
    Key's default_scenario (TKOS_API_KEYS_JSON), proving the C1 Key-model
    path passes the authZ gate and the resolver end to end."""
    monkeypatch.delenv("TKOS_API_KEY", raising=False)
    monkeypatch.setenv(
        "TKOS_API_KEYS_JSON",
        json.dumps({_TEST_KEY: {"default_scenario": "strategic_research"}}),
    )
    client = TestClient(create_app())
    r = client.post(
        "/v1/context-packs:resolve",
        headers=_auth_headers(),
        json={"query": "灯塔项目有哪些风险",
              "as_of": "2026-08-11T00:00:00+08:00"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["purpose"] == "decision_preparation"
