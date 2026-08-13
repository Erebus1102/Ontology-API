import json
import os

from fastapi.testclient import TestClient

from tkos_runtime.api.auth import _load_credentials, Principal
from tkos_runtime.api.server import create_app


def test_principal_defaults_single_key(monkeypatch):
    monkeypatch.setenv("TKOS_API_KEY", "k-single")
    p = _load_credentials()["k-single"]
    assert p.role == "cxo"           # 单 Key 默认 cxo 全可见（C.4 红线）
    assert p.tenant == "default"
    assert p.on_behalf_of is None
    assert p.confirmer is False
    assert p.default_scenario is None
    assert "*" in p.allowed_purposes


def test_cross_tenant_resolve_returns_404(monkeypatch):
    """C3: Principal.allowed_scopes narrows visible graphs.

    Both keys permit ``decision_preparation`` so the purpose gate (which runs
    first) passes for both — this isolates the scope mechanism. The first key
    has ``scopes=None`` (cxo default, all-visible) → 200 on the FE issue query.
    The second key has ``scopes=[]`` (empty set) → intersection with purpose-
    allowed graphs is empty → intent finds nothing → 404 with
    ``ontology_context_not_found`` (does NOT leak existence).

    Note: the plan's literal test used ``purposes:["mission_review"]`` for the
    second key with a ``decision_preparation`` request body — that would 403
    at the purpose gate before reaching the scope filter, so it could not
    verify the C3 mechanism. Both keys here allow ``decision_preparation``
    to isolate the scope→404 path.
    """
    monkeypatch.setenv("TKOS_API_KEYS_JSON", json.dumps({
        "tokenking-key": {
            "name": "tk-cxo", "tenant": "tokenking", "role": "cxo",
            "purposes": ["*"], "scopes": None,
        },
        "other-key": {
            "name": "other", "tenant": "other", "role": "executor",
            "purposes": ["decision_preparation"], "scopes": [],
        },
    }))
    client = TestClient(create_app())
    body = {
        "enterprise_id": "tk",
        "purpose": "decision_preparation",
        "query": "是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
        "as_of": "2026-08-11T00:00:00+08:00",
    }
    # 第一租户：scopes=None → 全可见 → 200
    r1 = client.post(
        "/v1/context-packs:resolve",
        headers={"Authorization": "Bearer tokenking-key"},
        json=body,
    )
    assert r1.status_code == 200, r1.text
    # 第二租户：scopes=[] → 图不可见 → 无命中 → 404（不泄漏存在性）
    r2 = client.post(
        "/v1/context-packs:resolve",
        headers={"Authorization": "Bearer other-key"},
        json=body,
    )
    assert r2.status_code == 404, r2.text
    assert r2.json()["detail"]["code"] == "ontology_context_not_found"
