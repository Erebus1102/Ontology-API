# tests/test_runtime_contract_v1.py
"""B1/B2 v1-contract convergence tests for POST /v1/context-packs:resolve.

Covers the 2.0 v1 request shape:
  * scenario (enum-validated against the registry in docs/mvp/01 §5) derives
    purpose; unknown scenario -> 422 {code: unknown_scenario}
  * purpose derived from scenario + Key default_scenario (C1 Principal)
  * legacy fields (enterprise_id/organization_scope/purpose/actor_id) are
    still accepted during the deprecation transition (transition red line).
B2: render 并入 resolve（render:true 返回 Markdown + structured pack）；
    :render 端点的 client-supplied pack 路径仍接受（deprecated，未删除）。
B3: 统一版本固定块（api_version/request_id/ontology_release/
    dataset_revision/policy_version/query_plan_version）+ request_id 中间件。
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
        json={"query": "灯塔项目进展如何",
              "as_of": "2026-08-11T00:00:00+08:00",
              "scenario": "task_followup"},
    )
    assert r.status_code == 200, r.text
    # scenario-derived purpose flows into the Pack; exercises the non-trivial
    # task_followup -> mission_review mapping (Reconciliation #7). 查询取
    # mission_review 可见图（graph-decision-provenance）可覆盖的主题——
    # "风险" 仅存在于 graph-candidate-and-dispute，mission_review 门禁
    # 下按认知诚实返回 404 知识缺口。
    assert r.json()["purpose"] == "mission_review"


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
        json.dumps({_TEST_KEY: {"default_scenario": "task_followup"}}),
    )
    client = TestClient(create_app())
    r = client.post(
        "/v1/context-packs:resolve",
        headers=_auth_headers(),
        json={"query": "灯塔项目进展如何",
              "as_of": "2026-08-11T00:00:00+08:00"},
    )
    assert r.status_code == 200, r.text
    # Key-default path also exercises the non-trivial task_followup ->
    # mission_review mapping
    assert r.json()["purpose"] == "mission_review"


# ---------------------------------------------------------------------------
# B2: render 并入 resolve（render:true）+ client-supplied pack 过渡红线
# ---------------------------------------------------------------------------

def test_resolve_render_true_returns_markdown(client_with_auth):
    """render:true — resolve 单调用返回渲染 Markdown；结构化 pack 随附在
    structured（2.0 render 并入 resolve 的契约）。"""
    r = client_with_auth.post(
        "/v1/context-packs:resolve",
        headers=_auth_headers(),
        json={"query": "灯塔项目进展如何",
              "as_of": "2026-08-11T00:00:00+08:00",
              "render": True},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "rendered" in body
    assert body["rendered"]["rendering_status"] == "completed"
    assert body["rendered"]["content"]
    # structured pack carried alongside the rendering
    assert "structured" in body
    assert body["structured"]["matched_root"]


def test_render_client_supplied_pack_still_accepted(client_with_auth):
    """过渡红线：:render 端点的 client-supplied pack 路径仍可用
    （deprecated 但未删除）。"""
    resolved = client_with_auth.post(
        "/v1/context-packs:resolve",
        headers=_auth_headers(),
        json={"query": "灯塔项目进展如何",
              "as_of": "2026-08-11T00:00:00+08:00"},
    )
    assert resolved.status_code == 200, resolved.text
    r = client_with_auth.post(
        "/v1/context-packs:render",
        headers=_auth_headers(),
        json={"pack": resolved.json(),
              "render_options": {"format": "markdown",
                                 "mode": "deterministic"}},
    )
    assert r.status_code == 200, r.text
    assert "rendered" in r.json()
    assert r.json()["rendered"]["rendering_status"] == "completed"


# ---------------------------------------------------------------------------
# B3: 统一版本固定块 + request_id 中间件
# ---------------------------------------------------------------------------

def test_resolve_response_carries_version_block(client_with_auth):
    r = client_with_auth.post(
        "/v1/context-packs:resolve",
        headers=_auth_headers(),
        json={"query": "灯塔项目有哪些风险",
              "as_of": "2026-08-11T00:00:00+08:00"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    for k in ("api_version", "request_id", "dataset_revision",
              "policy_version", "query_plan_version"):
        assert k in j
    assert j["api_version"] == "v1"
    assert isinstance(j["ontology_release"]["company"], str) and j["ontology_release"]["company"]
    assert j["ontology_release"]["persona"] is None
    assert r.headers["X-Request-ID"] == j["request_id"]


def test_render_response_carries_version_block(client_with_auth):
    """B3: :render 端点（client-supplied pack）与 resolve 一样在顶层携带
    六键版本固定块（render() 字典缺 dataset_revision/policy_version/
    query_plan_version，由 attach_version_block 补齐）。"""
    resolved = client_with_auth.post(
        "/v1/context-packs:resolve",
        headers=_auth_headers(),
        json={"query": "灯塔项目进展如何",
              "as_of": "2026-08-11T00:00:00+08:00"},
    )
    assert resolved.status_code == 200, resolved.text
    r = client_with_auth.post(
        "/v1/context-packs:render",
        headers=_auth_headers(),
        json={"pack": resolved.json(),
              "render_options": {"format": "markdown",
                                 "mode": "deterministic"}},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    for k in ("api_version", "request_id", "dataset_revision",
              "policy_version", "query_plan_version"):
        assert k in j, k
    assert j["api_version"] == "v1"
    assert isinstance(j["ontology_release"]["company"], str) and j["ontology_release"]["company"]
    assert j["ontology_release"]["persona"] is None
    assert r.headers["X-Request-ID"] == j["request_id"]


def test_request_id_respects_client_header(client_with_auth):
    """B3: 客户端 X-Request-ID 头原样进入响应体 request_id 并回显响应头。"""
    r = client_with_auth.post(
        "/v1/context-packs:resolve",
        headers={**_auth_headers(), "X-Request-ID": "my-trace-1"},
        json={"query": "灯塔项目进展如何",
              "as_of": "2026-08-11T00:00:00+08:00"},
    )
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["request_id"] == "my-trace-1"
    assert r.headers["X-Request-ID"] == "my-trace-1"
