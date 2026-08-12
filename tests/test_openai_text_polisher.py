# tests/test_openai_text_polisher.py
"""OpenAITextPolisher 适配器单元测试：超时配置与环境变量。

部署中发现：render LLM 模式默认 30s 超时，大 pack 的润色请求
（~10K 字符输入 + 长生成）在方舟上会超时降级（deterministic_fallback）。
修复：默认超时改读 LLM_TIMEOUT 环境变量（默认 120s），显式传参优先。
"""
import pytest

from tkos_runtime.adapters.openai_text_polisher import OpenAITextPolisher


def test_timeout_defaults_to_env_llm_timeout(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT", "77")
    monkeypatch.setenv("LLM_BASE_URL", "http://example.invalid")
    monkeypatch.setenv("LLM_AUTH_TOKEN", "k")
    polisher = OpenAITextPolisher()
    assert polisher._timeout == 77


def test_timeout_defaults_to_120_without_env(monkeypatch):
    monkeypatch.delenv("LLM_TIMEOUT", raising=False)
    monkeypatch.setenv("LLM_BASE_URL", "http://example.invalid")
    monkeypatch.setenv("LLM_AUTH_TOKEN", "k")
    polisher = OpenAITextPolisher()
    assert polisher._timeout == 120


def test_timeout_explicit_arg_overrides_env(monkeypatch):
    monkeypatch.setenv("LLM_TIMEOUT", "77")
    monkeypatch.setenv("LLM_BASE_URL", "http://example.invalid")
    monkeypatch.setenv("LLM_AUTH_TOKEN", "k")
    polisher = OpenAITextPolisher(timeout=5.0)
    assert polisher._timeout == 5.0


def test_missing_credentials_raises(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("LLM_AUTH_TOKEN", raising=False)
    with pytest.raises(ValueError, match="LLM_BASE_URL"):
        OpenAITextPolisher()
