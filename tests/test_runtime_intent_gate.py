# tests/test_runtime_intent_gate.py
"""P0 修复 —— 低置信度拒绝门禁（匹配层）+ API 端到端。

复现案例："TKOS deepresearch模块要不要上bedrock的模型"
  → 2-gram 碎片撞出 206 个候选，无强命中仍被选为 root。
  → 本门禁：top1 必须至少有一个主题词强命中，否则 NoMatchError → 404
    {code: ontology_context_not_found, unmatched_terms, suggested_action}。

强命中规则（用户评审后修订，含三审）：
  * 英文：完整 token（≥3 字符，非泛词）按 token-set 交集命中；
    未知关键实体（不在任何对象 token-set 中）参与否决 → 立即拒绝
    （"TokenHub 要不要上 bedrock 模型"：bedrock 未知即知识缺口）。
    强命中与 +30 加权只认 name 字段 token——scopeDescription 提及
    "TokenHub" 不构成命中（三审反例：assertion-* 曾靠 scope 穿透）。
  * 中文：只认业务主题词 —— 功能词/泛词停用（现在/应该/怎么/是否/
    需要/可以/如何/当前/情况/要不要/产品/公司/...）；与停用词相邻的
    碎片 gram（"司现/在应/该怎"）不构成强命中；强命中只限 name 字段
    （displayName/objectId），scopeDescription 只作底分。
  * 中文主题跨度准入（三审 + 四审修订）：移除疑问模板（有哪些/进展
    如何/有没有/是不是）与停用词后，剩余连续中文片段（span）用**覆盖
    率**判定——span 内 2-gram 在全库（name+scope）出现比例 < 0.5 =
    未知主题 → 拒绝并计入 unmatched_terms（"TokenHub 应该如何定价"：
    span[定价] 覆盖率 0 → 404）。跨界碎片（线进/有哪/些风）只存在于
    span 内部，由覆盖率容忍——四审误拒回归：
    产品 1.0 上线进展如何 / 产品 1.0 当前进度如何 /
    灯塔项目有哪些风险 / FE 当前有哪些风险 → 200。
    "模型现在应该怎么选择"：span[选择] 全库覆盖（barrier 的 scope 含
    "模型选择与路由权"）→ 200（二轮的 404 是 name-only 强命中门产物，
    四审起中文准入不再要求 top1 name 字段命中）。

保持型回归：FE 真实议题、英文实体词（TokenHub）、非 Issue 实体查询
必须继续命中。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from tkos_runtime.adapters.gram_intent_resolver import GramIntentResolver
from tkos_runtime.domain.models import NoMatchError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA, DATASET = (
    ROOT / "ontology/schema/tkos-ontology.jsonld",
    ROOT / "ontology/datasets/tkos-runtime-dataset.trig",
)

TKOS = "https://ontology.tokenking.ai/tkos#"
BEDROCK_QUERY = "TKOS deepresearch模块要不要上bedrock的模型"
PRICING_QUERY = "TokenKing产品应该怎么定价"
REAL_FE_QUERY = "是否在本季度同时完成产品 1.0 上线和灯塔项目交付"
RESEARCH_QUERY = "产品 1.0 与灯塔交付研究结论是什么"
TOKENHUB_QUERY = "TokenHub 模块当前进度如何"


def _full_store():
    return RdfDatasetStore(
        SCHEMA, DATASET,
        sorted((ROOT / "data" / "instances").glob("*.trig")),
        release_root=ROOT,
    )


# ── 门禁：拒绝无强命中的查询 ────────────────────────────────────────────

def test_bedrock_query_rejected_with_unmatched_terms():
    """deepresearch/bedrock 为未知关键实体 → NoMatchError 且携带 terms。"""
    s = _full_store()
    with pytest.raises(NoMatchError) as ei:
        GramIntentResolver(s).resolve(
            BEDROCK_QUERY, s.allowed_graphs("decision_preparation"))
    assert "deepresearch" in ei.value.unmatched_terms
    assert "bedrock" in ei.value.unmatched_terms


def test_pricing_query_rejected():
    """"定价"：泛词/字符碎片不构成可信命中 → 拒绝（修复前命中噪声对象）。"""
    s = _full_store()
    with pytest.raises(NoMatchError):
        GramIntentResolver(s).resolve(
            PRICING_QUERY, s.allowed_graphs("decision_preparation"))


def test_pure_unknown_query_still_rejected():
    """既有无匹配路径不受影响。"""
    s = _full_store()
    with pytest.raises(NoMatchError):
        GramIntentResolver(s).resolve(
            "完全不存在的查询词xyzq", s.allowed_graphs("decision_preparation"))


# ── 保持型回归：合法查询必须继续命中 ────────────────────────────────────

def test_fe_issue_still_matches():
    s = _full_store()
    ia = GramIntentResolver(s).resolve(
        REAL_FE_QUERY, s.allowed_graphs("decision_preparation"))
    assert ia.root == TKOS + "issue-product1-lighthouse-synchronous-delivery"


def test_english_token_full_match_still_works():
    """英文完整 token 命中（tokenhub）仍合法成为 root。"""
    s = _full_store()
    ia = GramIntentResolver(s).resolve(
        TOKENHUB_QUERY, s.allowed_graphs("decision_preparation"))
    assert ia.root == TKOS + "capability-tokenhub-runtime-base"


def test_research_entity_query_still_matches():
    """非 Issue 实体查询（Research）仍可合法成为 root（P0 不限制类型）。"""
    s = _full_store()
    ia = GramIntentResolver(s).resolve(
        RESEARCH_QUERY, s.allowed_graphs("decision_preparation"))
    assert ia.root == TKOS + "research-product1-lighthouse-schedule-and-delivery"


def test_sensitive_not_matched_fragment_consistent():
    """敏感图对象不能进入候选（保持既有断言）。

    三审起查询改为"历史数据"：旧查询（一号位历史判断偏好）在 v2.3 小
    包中主题（判断/偏好/一号位）全文零出现，按中文剩余主题否决应 404；
    敏感排除的验证改由通过门禁的查询承载（evidence-expired 的
    displayName 含"历史"）。"""
    s = RdfDatasetStore(
        SCHEMA, DATASET, [ROOT / "tests/v2.3-context-pack-runtime.trig"],
        release_root=ROOT)
    ia = GramIntentResolver(s).resolve(
        "历史数据", s.allowed_graphs("decision_preparation"))
    SENS = "assertion-sensitive"
    assert ia.root.rsplit("#", 1)[-1] != SENS
    assert all(a[1] != SENS for a in ia.alternatives)


# ── 独立评审反例回归（B1/B2/B4）────────────────────────────────────────

def test_review_B1_pricing_variant_rejected():
    """"公司现在应该怎么定价"：功能词（现在/应该/怎么）+ 泛词（公司）
    停用后剩余主题"定价"全文 0 出现 → 未知主题否决（三审起中文主题
    进入 unmatched_terms）。修复前命中 evidence-ceoagent-*
    （displayName 含"公司现实"）。"""
    s = _full_store()
    with pytest.raises(NoMatchError) as ei:
        GramIntentResolver(s).resolve(
            "公司现在应该怎么定价", s.allowed_graphs("decision_preparation"))
    # 三审：中文未知主题必须进入 unmatched_terms（此前为空，无法否决）
    assert "定价" in ei.value.unmatched_terms
    assert ei.value.match_reasons and "知识库全文" in ei.value.match_reasons[0]


def test_review_B2_unknown_entity_veto():
    """"TokenHub 要不要上 bedrock 模型"：bedrock 未知关键实体 → 否决。
    修复前 tokenhub 已知强命中继续选根 → strategy-content-* 编译 500。"""
    s = _full_store()
    with pytest.raises(NoMatchError) as ei:
        GramIntentResolver(s).resolve(
            "TokenHub 要不要上 bedrock 模型",
            s.allowed_graphs("decision_preparation"))
    assert "bedrock" in ei.value.unmatched_terms
    assert "tokenhub" not in ei.value.unmatched_terms


def test_review_R3_tokenhub_pricing_rejected():
    """"TokenHub 应该如何定价"（三审反例）：tokenhub 已知英文实体强命中，
    但剩余中文主题"定价"全文 0 出现 → 未知主题否决。修复前 200 且
    anchor=assertion-product1-mvp-output-week-2026-08-11（scope 提及
    TokenHub 穿透门禁）。"""
    s = _full_store()
    with pytest.raises(NoMatchError) as ei:
        GramIntentResolver(s).resolve(
            "TokenHub 应该如何定价", s.allowed_graphs("decision_preparation"))
    assert "定价" in ei.value.unmatched_terms
    assert "tokenhub" not in ei.value.unmatched_terms  # 已知实体不误拒


def test_review_R3_tokenhub_fee_plan_rejected():
    """"TokenHub 要不要采用新的收费方案"（三审反例）：收费/用新/费方
    全文 0 出现（采用/方案为已知知识不否决）→ 404。修复前 200 且
    root=research-product1-lighthouse-schedule-and-delivery。"""
    s = _full_store()
    with pytest.raises(NoMatchError) as ei:
        GramIntentResolver(s).resolve(
            "TokenHub 要不要采用新的收费方案",
            s.allowed_graphs("decision_preparation"))
    assert "收费" in ei.value.unmatched_terms
    assert "tokenhub" not in ei.value.unmatched_terms


def test_review_R3_tokenhub_progress_still_matches():
    """保持型回归：进度 存在于 scopeDescription（全文 2 处）→ 已知知识，
    不得被中文剩余主题否决误拒（进度在 name 字段零覆盖）。"""
    s = _full_store()
    ia = GramIntentResolver(s).resolve(
        TOKENHUB_QUERY, s.allowed_graphs("decision_preparation"))
    assert ia.root == TKOS + "capability-tokenhub-runtime-base"


def test_review_R4_launch_progress_matches():
    """四审误拒回归：产品 1.0 上线进展如何 → 200（旧规则把跨界碎片
    线进=上线|进展 当未知主题否决；span[上线] 覆盖率 1/1 通过）。"""
    s = _full_store()
    ia = GramIntentResolver(s).resolve(
        "产品 1.0 上线进展如何", s.allowed_graphs("decision_preparation"))
    assert ia.root


def test_review_R4_current_progress_matches():
    """四审误拒回归：产品 1.0 当前进度如何 → 200（进度 只在 scope 有
    覆盖、name 零覆盖——旧强命中门要求 top1 name 命中而误拒；四审起
    中文准入 = span 覆盖率，不再要求 name 字段）。"""
    s = _full_store()
    ia = GramIntentResolver(s).resolve(
        "产品 1.0 当前进度如何", s.allowed_graphs("decision_preparation"))
    assert ia.root


def test_review_R4_lighthouse_risks_matches():
    """四审误拒回归：灯塔项目有哪些风险 → 200（有哪/些风 为"有哪些"
    模板与边界碎片——模板整段移除、碎片由覆盖率容忍）。"""
    s = _full_store()
    ia = GramIntentResolver(s).resolve(
        "灯塔项目有哪些风险", s.allowed_graphs("decision_preparation"))
    assert ia.root


def test_review_R4_fe_risks_matches():
    """四审误拒回归：FE 当前有哪些风险 → 200。"""
    s = _full_store()
    ia = GramIntentResolver(s).resolve(
        "FE 当前有哪些风险", s.allowed_graphs("decision_preparation"))
    assert ia.root


def test_review_R4_model_selection_render_200(client_with_auth):
    """"模型现在应该怎么选择"（原 B4 反例）：span[选择] 在全库 13 处有
    覆盖（barrier-five-control-points 的 scope 含"模型选择与路由权"）
    → 200，root=barrier。二轮曾因 name-only 强命中门 404；四审中文准入
    改为 span 覆盖率后此查询合法命中，且 barrier root 可编译渲染
    （B4 编译器修复的成果：修复前该 root 编译 500）。"""
    req = dict(BASE_REQ, query="模型现在应该怎么选择")
    resp = client_with_auth.post(
        "/v1/context-packs:render", json={
            "resolve_request": req,
            "render_options": {"mode": "deterministic", "format": "markdown",
                               "include_structured": True, "max_chars": 6000,
                               "language": "zh-CN"},
        }, headers=_auth_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["decision_context"]["anchor"]["member_id"] == (
        "barrier-five-control-points")


# ── API 端到端 ──────────────────────────────────────────────────────────

_TEST_KEY = "tkos-test-key-2026"


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {_TEST_KEY}"}


BASE_REQ = {
    "enterprise_id": "tokenking",
    "organization_scope": [],
    "purpose": "decision_preparation",
    "query": REAL_FE_QUERY,
    "as_of": "2026-08-13T23:59:59+08:00",
    "actor_id": "agent-harness",
}


@pytest.fixture
def client_with_auth(monkeypatch):
    monkeypatch.setenv("TKOS_API_KEY", _TEST_KEY)
    return TestClient(__import__(
        "tkos_runtime.api.server", fromlist=["create_app"]).create_app())


def test_bedrock_resolve_404_structured(client_with_auth):
    """404 detail 结构化：code / unmatched_terms / suggested_action。"""
    bad = dict(BASE_REQ, query=BEDROCK_QUERY)
    resp = client_with_auth.post(
        "/v1/context-packs:resolve", json=bad, headers=_auth_headers())
    assert resp.status_code == 404, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "ontology_context_not_found"
    assert "deepresearch" in detail["unmatched_terms"]
    assert "bedrock" in detail["unmatched_terms"]
    assert detail["suggested_action"] == "submit_context_gap"


def test_bedrock_render_404_structured(client_with_auth):
    """render 端点内嵌 resolve 失败同样 404 结构化，且无正文产物。"""
    body = {
        "resolve_request": dict(BASE_REQ, query=BEDROCK_QUERY),
        "render_options": {
            "mode": "deterministic", "format": "markdown",
            "include_structured": True, "max_chars": 6000, "language": "zh-CN",
        },
    }
    resp = client_with_auth.post(
        "/v1/context-packs:render", json=body, headers=_auth_headers())
    assert resp.status_code == 404, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "ontology_context_not_found"
    assert detail["unmatched_terms"]
    assert "rendered" not in resp.json()


def test_review_R3_tokenhub_pricing_render_404(client_with_auth):
    """三审原始复现（HTTP 层）：TokenHub 应该如何定价 → 精确 404 +
    code，且 定价 在 unmatched_terms（修复前 200 且 anchor 错配）。"""
    body = {
        "resolve_request": dict(BASE_REQ, query="TokenHub 应该如何定价"),
        "render_options": {
            "mode": "deterministic", "format": "markdown",
            "include_structured": True, "max_chars": 6000, "language": "zh-CN",
        },
    }
    resp = client_with_auth.post(
        "/v1/context-packs:render", json=body, headers=_auth_headers())
    assert resp.status_code == 404, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "ontology_context_not_found"
    assert "定价" in detail["unmatched_terms"]


def test_fe_issue_render_still_200(client_with_auth):
    """合法查询不受门禁影响（回归）。"""
    body = {
        "resolve_request": BASE_REQ,
        "render_options": {
            "mode": "deterministic", "format": "markdown",
            "include_structured": True, "max_chars": 6000, "language": "zh-CN",
        },
    }
    resp = client_with_auth.post(
        "/v1/context-packs:render", json=body, headers=_auth_headers())
    assert resp.status_code == 200, resp.text


def test_research_entity_resolve_200_root_preserved(client_with_auth):
    """非 Issue 实体查询 200，matched_root 原样保留（P0 不限制类型）。"""
    req = dict(BASE_REQ, query=RESEARCH_QUERY)
    resp = client_with_auth.post(
        "/v1/context-packs:resolve", json=req, headers=_auth_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["matched_root"] == (
        TKOS + "research-product1-lighthouse-schedule-and-delivery")
