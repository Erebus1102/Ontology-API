import os
from tkos_runtime.api.auth import _load_credentials, Principal

def test_principal_defaults_single_key(monkeypatch):
    monkeypatch.setenv("TKOS_API_KEY", "k-single")
    p = _load_credentials()["k-single"]
    assert p.role == "cxo"           # 单 Key 默认 cxo 全可见（C.4 红线）
    assert p.tenant == "default"
    assert p.on_behalf_of is None
    assert p.confirmer is False
    assert p.default_scenario is None
    assert "*" in p.allowed_purposes
