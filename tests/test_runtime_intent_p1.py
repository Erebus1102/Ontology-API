# tests/test_runtime_intent_p1.py
"""P1/P1.1 IntentAssessment —— 角色语义 / 409 歧义 / 404 候选 / 意图切面。

五审核心问题："200 但锚点错误"——跨度门禁能判断"知识库可能覆盖"但
不能判断用户要查的对象类型与关系角色。P1 一次性加入：
  * intent_facets（entity / requested_role / operation）
  * "风险" constrain Risk 类实体、"进展/进度" prefer ProgressSnapshot
  * top1/top2 有效维度完全并列 → 409 ontology_context_ambiguous
    （严格规则，无 IRI 兜底）
  * 404 alternatives 返回门禁后候选建议（英文/中文知识否决 →
    baseline[:5]；constrain 池空 → baseline[:5]）

P1.1 排序维度（用户审定，六维）：
  exact_match ＞ entity_evidence（英文 token 在 name 字段命中，含
  2 字符全大写实体代号如 FE）＞ requested-role compatibility（目标
  角色候选池内消歧）＞ evidence（name∪scope 的业务主题 gram 覆盖，
  泛业务名词如 模型 保留、纯功能词如 当前 切断）＞ name_evidence
  （名称命中压 scope 命中）＞ effective_score（base + prefer boost）。
  409 候选为 5 元组 (score, id, name, primary_type, matched_evidence)。
  精确断言：root 精确 ==（禁止裸 assert ia.root）；409 候选集合恰 ==
  （完整并列集，不受 top5 截断）；候选全部来自 allowed_graph_ids。
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from tkos_runtime.adapters.gram_intent_resolver import GramIntentResolver
from tkos_runtime.domain.models import AmbiguousMatchError, NoMatchError

ROOT = Path(__file__).resolve().parents[1]
SCHEMA, DATASET = (
    ROOT / "ontology/schema/tkos-ontology.jsonld",
    ROOT / "ontology/datasets/tkos-runtime-dataset.trig",
)

TKOS = "https://ontology.tokenking.ai/tkos#"


def _frag(u: str) -> str:
    return str(u).rsplit("#", 1)[-1]


def _full_store():
    return RdfDatasetStore(
        SCHEMA, DATASET,
        sorted((ROOT / "data" / "instances").glob("*.trig")),
        release_root=ROOT,
    )


def _resolve(store, query):
    return GramIntentResolver(store).resolve(
        query, store.allowed_graphs("decision_preparation"))


# ── 404 candidates（英文/中文知识否决携带门禁后候选）──────────────────

def test_p1_bedrock_veto_carries_candidates():
    s = _full_store()
    with pytest.raises(NoMatchError) as ei:
        GramIntentResolver(s).resolve(
            "TKOS deepresearch模块要不要上bedrock的模型",
            s.allowed_graphs("decision_preparation"))
    assert ei.value.candidates
    # P1.1 六维排序下 bedrock 404 建议 top1（验证数据）：
    # capability-tokenhub-runtime-base（scope 覆盖 模块/模型 证据 2）
    assert ei.value.candidates[0][0] == 8
    assert ei.value.candidates[0][1] == "capability-tokenhub-runtime-base"
    assert ei.value.candidates[0][2]  # display_name 非空
    assert ei.value.candidates[0][3] == "CompanyCapability"  # type
    assert set(ei.value.candidates[0][4]) == {"name", "scope"}  # evidence


def test_p1_pricing_veto_carries_candidates():
    s = _full_store()
    with pytest.raises(NoMatchError) as ei:
        GramIntentResolver(s).resolve(
            "TokenKing产品应该怎么定价",
            s.allowed_graphs("decision_preparation"))
    assert ei.value.candidates
    assert all(len(c) == 5 for c in ei.value.candidates)


# ── 角色语义：精确 root 断言（禁止裸 assert ia.root）──────────────────

def test_p1_risk_constraint_lighthouse_exact_root():
    """"灯塔项目有哪些风险" → constrain Risk → 精确 root resource-conflict
    （name 证据 1 vs 0 压制 scope 噪声）。"""
    ia = _resolve(_full_store(), "灯塔项目有哪些风险")
    assert ia.root == TKOS + "risk-product1-lighthouse-resource-conflict"


def test_p1_progress_preference_current_progress_exact_root():
    """产品 1.0 当前进度如何 → prefer ProgressSnapshot（13+5 vs 12）→
    精确 root component-availability。"""
    ia = _resolve(_full_store(), "产品 1.0 当前进度如何")
    assert ia.root == TKOS + "progress-product1-component-availability-2026-08-11"


def test_p1_progress_preference_tokenhub_root_unchanged():
    """TokenHub 模块当前进度如何 → prefer 只加成不排除 → capability
    root 保持不变（契约 #5）。"""
    ia = _resolve(_full_store(), "TokenHub 模块当前进度如何")
    assert ia.root == TKOS + "capability-tokenhub-runtime-base"


# ── 409 歧义：完整并列候选集合精确断言 ────────────────────────────────

def _ambiguous_ids(err):
    return {c[1] for c in err.candidates}


def test_p1_progress_preference_launch_progress_ambiguous():
    """产品 1.0 上线进展如何 → 409，候选恰 == 两个 ProgressSnapshot
    （用户 P1.1 验收项："candidates 全部为 ProgressSnapshot"）。

    P1.1 数据事实：证据 gram 集 = {产品, 上线}（模板"进展如何"移除）。
    两个快照 name 覆盖 产品（ev 1/name_ev 1/eff 11 = base 6 + prefer
    5）；issue/risk 同样 ev 1 但 role_comp=0——用户规则"缺少明确实体
    强锚点时，只要存在带实体覆盖的目标角色候选，409/root 选择就在
    目标角色候选池内完成"：role_comp 维把两个快照升至居顶，二者六维
    全并列 → 409，候选恰 == 两个 ProgressSnapshot。"""
    s = _full_store()
    with pytest.raises(AmbiguousMatchError) as ei:
        GramIntentResolver(s).resolve(
            "产品 1.0 上线进展如何", s.allowed_graphs("decision_preparation"))
    assert _ambiguous_ids(ei.value) == {
        "progress-product1-component-availability-2026-08-11",
        "progress-product1-mvp-week-2026-08-11",
    }
    assert all(c[3] == "OutcomeProgressSnapshot" for c in ei.value.candidates)


def test_p1_risk_constraint_fe_ambiguous():
    """FE 当前有哪些风险 → 两个 Risk 实体完全并列 → 409。"""
    s = _full_store()
    with pytest.raises(AmbiguousMatchError) as ei:
        GramIntentResolver(s).resolve(
            "FE 当前有哪些风险", s.allowed_graphs("decision_preparation"))
    assert _ambiguous_ids(ei.value) == {
        "risk-fe-m1-context-conflict",
        "risk-fe-m1-no-product-consumption",
    }


def test_p1_model_selection_ambiguous():
    """模型现在应该怎么选择（B4）→ 409，候选包含 barrier-five-control-
    points（用户 P1.1 验收项），恰 == 三路并列（完整并列集不截断）。

    P1.1 数据事实：证据 gram 保留泛业务名词后 = {模型, 选择}。barrier /
    august-mission-portfolio-baseline / dual-business-feedback-loop 的
    scope 各覆盖 模型+选择（ev 2、name_ev 0）；名称含"选择"的节点只
    覆盖 选择（ev 1）→ 三路 ev=2 并列居顶 → 409（用户规则："候选证据
    同时计算 name 与 scope"——barrier 的证据全在 scope）。"""
    s = _full_store()
    with pytest.raises(AmbiguousMatchError) as ei:
        GramIntentResolver(s).resolve(
            "模型现在应该怎么选择", s.allowed_graphs("decision_preparation"))
    assert _ambiguous_ids(ei.value) == {
        "barrier-five-control-points",
        "strategy-content-august-mission-portfolio-baseline",
        "strategy-content-dual-business-feedback-loop",
    }
    # barrier 的证据全在 scope（name 零证据）——matched_evidence 供 Agent 消歧
    barrier = next(c for c in ei.value.candidates
                   if c[1] == "barrier-five-control-points")
    assert barrier[3] == "CompetitiveBarrier"
    assert barrier[4]["name"] == [] and barrier[4]["scope"] == ["模型", "选择"]


# ── 候选安全：全部来自 allowed_graph_ids、不含敏感图节点 ──────────────

def test_p1_candidates_from_allowed_graphs_only():
    s = _full_store()
    allowed = s.allowed_graphs("decision_preparation")
    allowed_frags = {_frag(st.subject) for st in s.statements_in(allowed)}
    with pytest.raises(NoMatchError) as ei:
        GramIntentResolver(s).resolve(
            "TKOS deepresearch模块要不要上bedrock的模型", allowed)
    for _, frag, _n, _t, _me in ei.value.candidates:
        assert frag in allowed_frags
        assert frag != "assertion-sensitive"
    with pytest.raises(AmbiguousMatchError) as ei2:
        GramIntentResolver(s).resolve("FE 当前有哪些风险", allowed)
    for _, frag, _n, _t, _me in ei2.value.candidates:
        assert frag in allowed_frags
        assert frag != "assertion-sensitive"


# ── intent_facets 精确锚定 ─────────────────────────────────────────────

def test_p1_facets_real_fe():
    ia = _resolve(_full_store(),
                  "是否在本季度同时完成产品 1.0 上线和灯塔项目交付")
    f = ia.intent_facets
    assert f.entity == "产品 1.0 本季度同时完成 上线 灯塔 交付"
    assert f.requested_role is None
    assert f.operation is None


def test_p1_facets_research():
    ia = _resolve(_full_store(), "产品 1.0 与灯塔交付研究结论是什么")
    f = ia.intent_facets
    assert f.entity == "产品 1.0 灯塔交付"
    assert f.requested_role is None
    assert f.operation is None


def test_p1_facets_tokenhub():
    ia = _resolve(_full_store(), "TokenHub 模块当前进度如何")
    f = ia.intent_facets
    assert f.entity == "tokenhub"
    assert f.requested_role == "progress"
    assert f.operation == "status"


def test_p1_facets_lighthouse_risk():
    ia = _resolve(_full_store(), "灯塔项目有哪些风险")
    f = ia.intent_facets
    assert f.entity == "灯塔"
    assert f.requested_role == "risk"
    assert f.operation == "list"


def test_p1_facets_current_progress():
    ia = _resolve(_full_store(), "产品 1.0 当前进度如何")
    f = ia.intent_facets
    assert f.entity == "产品 1.0"
    assert f.requested_role == "progress"
    assert f.operation == "status"


def test_p1_facets_history_v23():
    """v2.3 小包：历史数据 → 无触发词 → role/operation None。"""
    s = RdfDatasetStore(
        SCHEMA, DATASET, [ROOT / "tests/v2.3-context-pack-runtime.trig"],
        release_root=ROOT)
    ia = GramIntentResolver(s).resolve(
        "历史数据", s.allowed_graphs("decision_preparation"))
    f = ia.intent_facets
    assert f.entity == "历史数据"
    assert f.requested_role is None
    assert f.operation is None


def test_p1_facets_model_selection_operation_select():
    """P1.1："选择" → operation="select"。含"选择"的查询（模型现在应该
    怎么选择）是 409 路径，无 200 root 可取，故直接单元调用
    _build_facets 锚定 operation 与 entity 提取。"""
    from tkos_runtime.adapters.gram_intent_resolver import _build_facets
    f = _build_facets(
        "TokenHub 模型怎么选择", "capability-tokenhub-runtime-base", None,
        {"capability-tokenhub-runtime-base":
         "产品模块 tokenhub agent 运行底座（持续运行）"})
    assert f.operation == "select"
    assert f.entity == "tokenhub"
    assert f.requested_role is None


# ── API 契约：409 歧义 / 404 alternatives ──────────────────────────────

_TEST_KEY = "tkos-test-key-2026"


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {_TEST_KEY}"}


BASE_REQ = {
    "enterprise_id": "tokenking",
    "organization_scope": [],
    "purpose": "decision_preparation",
    "query": "是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
    "as_of": "2026-08-13T23:59:59+08:00",
    "actor_id": "agent-harness",
}


@pytest.fixture
def client_with_auth(monkeypatch):
    monkeypatch.setenv("TKOS_API_KEY", _TEST_KEY)
    return TestClient(__import__(
        "tkos_runtime.api.server", fromlist=["create_app"]).create_app())


def test_p1_ambiguous_409_resolve(client_with_auth):
    """产品 1.0 上线进展如何 → 409 + code + 完整并列候选（精确 id），
    P1.1 每项附 type 与 matched_evidence。"""
    req = dict(BASE_REQ, query="产品 1.0 上线进展如何")
    resp = client_with_auth.post(
        "/v1/context-packs:resolve", json=req, headers=_auth_headers())
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "ontology_context_ambiguous"
    assert detail["query"] == "产品 1.0 上线进展如何"
    assert detail["suggested_action"] == "disambiguate_query"
    assert {c["id"] for c in detail["candidates"]} == {
        "progress-product1-component-availability-2026-08-11",
        "progress-product1-mvp-week-2026-08-11",
    }
    assert all({"score", "id", "name", "type", "matched_evidence"}
               <= set(c) for c in detail["candidates"])
    for c in detail["candidates"]:
        assert c["type"] == "OutcomeProgressSnapshot"
        assert c["matched_evidence"] == {"name": ["产品"], "scope": []}


def test_p1_ambiguous_409_render(client_with_auth):
    """render 端点内嵌 resolve 歧义同样 409，且无正文产物。"""
    body = {
        "resolve_request": dict(BASE_REQ, query="FE 当前有哪些风险"),
        "render_options": {
            "mode": "deterministic", "format": "markdown",
            "include_structured": True, "max_chars": 6000, "language": "zh-CN",
        },
    }
    resp = client_with_auth.post(
        "/v1/context-packs:render", json=body, headers=_auth_headers())
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "ontology_context_ambiguous"
    assert {c["id"] for c in detail["candidates"]} == {
        "risk-fe-m1-context-conflict",
        "risk-fe-m1-no-product-consumption",
    }
    for c in detail["candidates"]:
        assert c["type"] == "Risk"
        assert set(c["matched_evidence"]) == {"name", "scope"}
    assert "rendered" not in resp.json()


def test_p1_404_alternatives_resolve(client_with_auth):
    """bedrock 未知实体 → 404 + alternatives 非空（门禁后候选建议，
    只暴露 score/id/name 三项）。"""
    req = dict(BASE_REQ, query="TKOS deepresearch模块要不要上bedrock的模型")
    resp = client_with_auth.post(
        "/v1/context-packs:resolve", json=req, headers=_auth_headers())
    assert resp.status_code == 404, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "ontology_context_not_found"
    assert detail["alternatives"]
    assert all({"score", "id", "name"} <= set(a)
               and "matched_evidence" not in a
               for a in detail["alternatives"])
    assert any(a["id"] == "capability-tokenhub-runtime-base"
               for a in detail["alternatives"])


# ── facets 进 ContextPack（resolve / render / roundtrip）────────────────

def _resolved_pack(query):
    from tkos_runtime.application.context_compiler import ContextCompiler
    from tkos_runtime.application.context_pack_resolver import ContextPackResolver
    from tkos_runtime.adapters.rdflib_graph_retriever import RdfGraphRetriever
    from tkos_runtime.domain.policies import AdmissionPolicy
    from datetime import datetime
    store = _full_store()
    resolver = ContextPackResolver(
        store, GramIntentResolver(store), RdfGraphRetriever(store),
        ContextCompiler(store, AdmissionPolicy()))
    return resolver.resolve(
        query, "decision_preparation",
        datetime.fromisoformat("2026-08-13T23:59:59+08:00"), [])


def test_p1_intent_facets_in_resolve_200():
    """灯塔风险 resolve → pack.intent_facets 精确 dict。"""
    pack = _resolved_pack("灯塔项目有哪些风险")
    assert pack.intent_facets == {
        "entity": "灯塔", "requested_role": "risk", "operation": "list",
    }


def test_p1_intent_facets_none_when_absent():
    """无触发词查询 → facets dict 仍携带 entity、role/operation 为 None。"""
    pack = _resolved_pack("是否在本季度同时完成产品 1.0 上线和灯塔项目交付")
    assert pack.intent_facets == {
        "entity": "产品 1.0 本季度同时完成 上线 灯塔 交付",
        "requested_role": None, "operation": None,
    }


def test_p1_intent_facets_render_structured(client_with_auth):
    """render include_structured → decision_context 透出 intent_facets。"""
    req = dict(BASE_REQ, query="灯塔项目有哪些风险")
    resp = client_with_auth.post(
        "/v1/context-packs:render", json={
            "resolve_request": req,
            "render_options": {"mode": "deterministic", "format": "markdown",
                               "include_structured": True, "max_chars": 6000,
                               "language": "zh-CN"},
        }, headers=_auth_headers())
    assert resp.status_code == 200, resp.text
    assert resp.json()["structured"]["intent_facets"] == {
        "entity": "灯塔", "requested_role": "risk", "operation": "list",
    }


def test_p1_intent_facets_roundtrip():
    """pack_to_dict → dict_to_pack 保持 intent_facets（serializer round-trip）。"""
    from tkos_runtime.api.serializer import dict_to_pack, pack_to_dict
    pack = _resolved_pack("产品 1.0 当前进度如何")
    assert pack.intent_facets["requested_role"] == "progress"
    restored = dict_to_pack(pack_to_dict(pack))
    assert restored.intent_facets == pack.intent_facets
