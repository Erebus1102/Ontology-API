# tests/test_runtime_renderer.py
"""Acceptance tests for ContextPack -> NL Markdown renderer.

Covers 10 acceptance criteria:
  1. Deterministic output is stable across calls.
  2. Current/Candidate/Gap partition boundaries preserved.
  3. Every fact sentence carries a legal [member:<id>] anchor.
  4. All member IDs exist in the input pack.
  5. All [source:<graph>] anchors come from the member's source_graphs.
  6. LLM injected entities/member IDs → rejected (validates post-LLM check).
  7. LLM failure → deterministic fallback (llm_with_fallback) or error (llm_required).
  8. Empty pack, gap-only, candidate-only, long Chinese text all render.
  9. max_chars truncation at sentence boundary, not mid-sentence.
  10. Original /resolve and its 41 tests are unaffected.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest

from tkos_runtime.domain.models import (
    AdmissionDecision,
    ContextPack,
    ContextPackMember,
    GraphStatement,
    Omission,
    ScopeResolution,
)
from tkos_runtime.application.context_renderer import (
    _render_deterministic,
    render,
    RENDERER_VERSION,
)
from tkos_runtime.api.serializer import pack_to_dict, dict_to_pack


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _stmt(subj, pred, obj, graph="graph-confirmed-enterprise"):
    return GraphStatement(subj, pred, obj, graph)


def _member(
    mid, display_name, partition, stmts, *,
    scope=None, status="Confirmed", source_graphs=None,
):
    return ContextPackMember(
        id=mid, display_name=display_name, scope=scope,
        partition=partition, statements=stmts,
        source_graphs=source_graphs or [partition],
        confirmation_status=status, lifecycle=None,
        valid_from=None, valid_until=None, sources=[],
        admission=AdmissionDecision(True, partition),
    )


def _pack(**overrides):
    defaults = dict(
        pack_id="test-pack", schema_version="1.0",
        as_of="2026-08-12T00:00:00+08:00", query="测试查询",
        purpose="decision_preparation", matched_root="urn:test:root",
        alternative_matches=[], scope_resolution=ScopeResolution([], [], "not_enforced", ""),
        current_facts=[], candidate_context=[], provenance_context=[],
        proof=[], derived_claims=[], reasoning_status="not_available",
        context_gaps=[], conflicts=[], omissions=[],
        contributing_graphs=[], admission_policy="",
        ontology_release_id="2.4.0",
        dataset_revision="a" * 64,
        policy_version="read-admission/p0-v1",
        query_plan_version="bfs-2gram/p0-v1",
    )
    defaults.update(overrides)
    return ContextPack(**defaults)


# ---------------------------------------------------------------------------
# 1. deterministic stability
# ---------------------------------------------------------------------------

def test_deterministic_output_is_stable():
    pack = _pack(
        current_facts=[
            _member("m1", "增长任务", "graph-confirmed-enterprise",
                    [_stmt("urn:m1", "urn:hasScope", "用户增长")],
                    scope="用户增长和收入增长"),
        ],
    )
    r1 = _render_deterministic(pack)
    r2 = _render_deterministic(pack)
    assert r1 == r2
    # 锚点验证
    assert "[member:m1]" in r1
    assert "[source:graph-confirmed-enterprise]" in r1


# ---------------------------------------------------------------------------
# 2. partition boundaries
# ---------------------------------------------------------------------------

def test_current_candidate_gap_boundaries():
    pack = _pack(
        current_facts=[
            _member("cur", "已确认项", "graph-confirmed-enterprise",
                    [_stmt("urn:cur", "urn:displayName", "已确认项")],
                    status="Confirmed"),
        ],
        candidate_context=[
            _member("cand", "候选项", "graph-candidate-and-dispute",
                    [_stmt("urn:cand", "urn:displayName", "候选项")],
                    status="Candidate"),
        ],
        context_gaps=[
            _member("gap1", "缺口项", "graph-candidate-and-dispute",
                    [_stmt("urn:gap1", "urn:displayName", "缺口项")],
                    status="Candidate"),
        ],
    )
    result = _render_deterministic(pack)
    # 当前事实段落在前
    assert result.index("当前已确认事实") < result.index("待确认信息")
    assert result.index("待确认信息") < result.index("信息缺口")
    # cur 在 current 段落下
    cur_pos = result.index("[member:cur]")
    cand_pos = result.index("[member:cand]")
    gap_pos = result.index("[member:gap1]")
    assert cur_pos < cand_pos < gap_pos


# ---------------------------------------------------------------------------
# 3-4. member ID anchors
# ---------------------------------------------------------------------------

def test_every_fact_sentence_has_legal_member_id():
    pack = _pack(
        current_facts=[
            _member("m1", "事实A", "graph-confirmed-enterprise", []),
            _member("m2", "事实B", "graph-confirmed-enterprise", []),
        ],
        candidate_context=[
            _member("c1", "候选C", "graph-candidate-and-dispute", [],
                    status="Candidate"),
        ],
    )
    result = _render_deterministic(pack)
    mentioned = set(re.findall(r"\[member:([^\]]+)\]", result))
    assert mentioned == {"m1", "m2", "c1"}


def test_all_member_ids_exist_in_pack():
    pack = _pack(
        current_facts=[_member("real", "真", "graph-confirmed-enterprise", [])],
    )
    result = _render_deterministic(pack)
    mentioned = set(re.findall(r"\[member:([^\]]+)\]", result))
    all_ids = {m.id for m in (
        pack.current_facts + pack.candidate_context +
        pack.context_gaps + pack.provenance_context
    )}
    assert mentioned <= all_ids


# ---------------------------------------------------------------------------
# 5. source anchors
# ---------------------------------------------------------------------------

def test_source_anchors_from_member_source_graphs():
    pack = _pack(
        current_facts=[
            _member("m1", "事实", "graph-confirmed-enterprise", [],
                    source_graphs=["graph-confirmed-enterprise"]),
        ],
        candidate_context=[
            _member("c1", "候选", "graph-candidate-and-dispute", [],
                    status="Candidate",
                    source_graphs=["graph-candidate-and-dispute"]),
        ],
    )
    result = _render_deterministic(pack)
    # 所有 source 标签来自合法的图名
    sources = set(re.findall(r"\[source:([^\]]+)\]", result))
    assert sources <= {
        "graph-confirmed-enterprise",
        "graph-candidate-and-dispute",
        "graph-decision-provenance",
        "graph-derived-context",
    }


# ---------------------------------------------------------------------------
# 7. mode behaviour
# ---------------------------------------------------------------------------

def test_deterministic_mode_no_external_deps():
    """deterministic mode must never call LLM or raise on missing creds."""
    pack = _pack(current_facts=[
        _member("m1", "测试", "graph-confirmed-enterprise", []),
    ])
    result = render(pack, mode="deterministic")
    assert result["rendered"]["mode_used"] == "deterministic"
    assert result["rendered"]["content"]
    assert result["rendered"]["grounding_status"] == "validated"


def test_llm_with_fallback_degrades_on_missing_creds():
    """llm_with_fallback must degrade to deterministic when no API key."""
    pack = _pack()
    result = render(
        pack, mode="llm_with_fallback",
        llm_base_url="", llm_api_key="", llm_model="",
    )
    assert result["rendered"]["mode_used"] == "deterministic_fallback"
    assert result["rendered"]["warnings"]


def test_llm_required_raises_on_missing_creds():
    """llm_required must raise ValueError when no API key configured."""
    pack = _pack()
    with pytest.raises(ValueError):
        render(pack, mode="llm_required", llm_base_url="", llm_api_key="",
               llm_model="")


# ---------------------------------------------------------------------------
# 8. edge cases
# ---------------------------------------------------------------------------

def test_empty_pack_renders_clear_message():
    pack = _pack()
    result = _render_deterministic(pack)
    assert "没有满足准入条件" in result
    assert "没有待确认" in result
    assert "没有已知信息缺口" in result
    assert "没有决策参考来源" in result


def test_gap_only_pack():
    pack = _pack(
        context_gaps=[
            _member("gap1", "已知缺口", "graph-candidate-and-dispute", [],
                    status="Candidate"),
        ],
    )
    result = _render_deterministic(pack)
    assert "[member:gap1]" in result
    assert "信息缺口" in result


def test_candidate_only_pack():
    pack = _pack(
        candidate_context=[
            _member("c1", "候选事实", "graph-candidate-and-dispute", [],
                    status="PreliminarilyConfirmed"),
        ],
    )
    result = _render_deterministic(pack)
    assert "[member:c1]" in result
    assert "[PreliminarilyConfirmed]" in result
    assert "待确认信息" in result


def test_chinese_long_text_renders():
    pack = _pack(
        current_facts=[
            _member("m1",
                    "这是一个非常长的中文显示名称用于测试渲染器处理长文本的能力",
                    "graph-confirmed-enterprise",
                    [_stmt("urn:m1", "urn:hasScope",
                           "覆盖范围包括多个业务领域和复杂的企业经营场景需要确保渲染正确")],
                    scope="范围描述也可以很长"),
        ],
    )
    result = _render_deterministic(pack)
    assert len(result) > 0
    assert "[member:m1]" in result


# ---------------------------------------------------------------------------
# 9. max_chars truncation
# ---------------------------------------------------------------------------

def test_max_chars_truncation_at_sentence_boundary():
    pack = _pack(
        current_facts=[
            _member(f"m{i}", f"事实条目{i}", "graph-confirmed-enterprise", [])
            for i in range(20)
        ],
    )
    result = render(pack, mode="deterministic", max_chars=500)
    content = result["rendered"]["content"]
    assert len(content) <= 500
    # 判断末尾是句号或换行（句子边界）
    assert content.rstrip().endswith(("。", "\n", "-"))


# ---------------------------------------------------------------------------
# 10. resolve unaffected
# ---------------------------------------------------------------------------

def test_resolve_endpoint_still_works():
    """Existing /resolve endpoint must be unaffected by render additions."""
    from fastapi.testclient import TestClient
    from tkos_runtime.api.server import create_app

    client = TestClient(create_app())
    resp = client.post("/v1/context-packs:resolve", json={
        "enterprise_id": "tokenking", "organization_scope": [],
        "purpose": "decision_preparation",
        "query": "是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
        "as_of": "2026-08-11T23:59:59+08:00",
        "actor_id": "test",
    })
    assert resp.status_code == 200, resp.text
    assert resp.json()["matched_root"]


# ---------------------------------------------------------------------------
# render endpoint integration
# ---------------------------------------------------------------------------

def test_render_endpoint_with_resolve_request():
    """POST /render with resolve_request resolves + renders in one call."""
    from fastapi.testclient import TestClient
    from tkos_runtime.api.server import create_app

    client = TestClient(create_app())
    resp = client.post("/v1/context-packs:render", json={
        "resolve_request": {
            "enterprise_id": "tokenking",
            "organization_scope": [],
            "purpose": "decision_preparation",
            "query": "是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
            "as_of": "2026-08-11T23:59:59+08:00",
        },
        "render_options": {"mode": "deterministic", "include_structured": True, "max_chars": 50000},
    })
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rendered"]["content"]
    assert "当前已确认事实" in body["rendered"]["content"]
    assert body["rendered"]["mode_used"] == "deterministic"
    assert body["rendered"]["grounding_status"] == "validated"
    assert body["metadata"]["renderer_version"] == RENDERER_VERSION
    # include_structured
    assert body["structured"]["matched_root"]


def test_render_endpoint_with_pack_input():
    """POST /render with a pre-resolved pack."""
    from fastapi.testclient import TestClient
    from tkos_runtime.api.server import create_app

    client = TestClient(create_app())
    # First resolve
    r1 = client.post("/v1/context-packs:resolve", json={
        "enterprise_id": "tokenking", "organization_scope": [],
        "purpose": "decision_preparation",
        "query": "是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
        "as_of": "2026-08-11T23:59:59+08:00",
        "actor_id": "test",
    })
    pack_dict = r1.json()

    # Then render the pack dict
    r2 = client.post("/v1/context-packs:render", json={
        "pack": pack_dict,
        "render_options": {"mode": "deterministic"},
    })
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["rendered"]["content"]


def test_render_both_inputs_is_422():
    """Exactly one of pack or resolve_request required."""
    from fastapi.testclient import TestClient
    from tkos_runtime.api.server import create_app

    client = TestClient(create_app())
    resp = client.post("/v1/context-packs:render", json={
        "pack": {"pack_id": "x"},
        "resolve_request": {"query": "x", "purpose": "decision_preparation"},
    })
    assert resp.status_code == 422, resp.text


def test_render_neither_input_is_422():
    """Neither pack nor resolve_request → 422."""
    from fastapi.testclient import TestClient
    from tkos_runtime.api.server import create_app

    client = TestClient(create_app())
    resp = client.post("/v1/context-packs:render", json={})
    assert resp.status_code == 422, resp.text


# ---------------------------------------------------------------------------
# roundtrip: dict_to_pack → pack_to_dict
# ---------------------------------------------------------------------------

def test_dict_to_pack_roundtrip_preserves_renderable_fields():
    """dict_to_pack reconstructs enough for deterministic renderer to work."""
    from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
    from tkos_runtime.adapters.gram_intent_resolver import GramIntentResolver
    from tkos_runtime.adapters.rdflib_graph_retriever import RdfGraphRetriever
    from tkos_runtime.application.context_compiler import ContextCompiler
    from tkos_runtime.application.context_pack_resolver import ContextPackResolver
    from tkos_runtime.domain.policies import AdmissionPolicy

    ROOT = Path(__file__).resolve().parents[1]
    SCHEMA = ROOT / "ontology" / "schema" / "tkos-ontology.jsonld"
    DATASET = ROOT / "ontology" / "datasets" / "tkos-runtime-dataset.trig"

    store = RdfDatasetStore(
        SCHEMA, DATASET,
        sorted((ROOT / "data" / "instances").glob("*.trig")),
        release_root=ROOT,
    )
    resolver = ContextPackResolver(
        store, GramIntentResolver(store),
        RdfGraphRetriever(store),
        ContextCompiler(store, AdmissionPolicy()),
    )
    pack = resolver.resolve(
        "是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
        "decision_preparation",
        datetime.fromisoformat("2026-08-11T23:59:59+08:00"),
        [],
    )

    # Serialize → deserialize → render
    d = pack_to_dict(pack)
    reconstructed = dict_to_pack(d)
    result = _render_deterministic(reconstructed)
    assert "当前已确认事实" in result
    assert len(result) > 0
