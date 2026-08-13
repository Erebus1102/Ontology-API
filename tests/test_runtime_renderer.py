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

TKOS = "https://ontology.tokenking.ai/tkos#"


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


def _typed_root_pack(mid="m1", display="测试", purpose="decision_preparation", **overrides):
    """Pack whose matched_root is a real, typed member (P0 contract: ghost
    roots are integrity errors — compile()/render() must name a member that
    actually lands in a section)."""
    overrides.setdefault("current_facts", [
        _member(mid, display, "graph-confirmed-enterprise", []),
    ])
    pack = _pack(matched_root=TKOS + mid, purpose=purpose, **overrides)
    root_member = pack.current_facts[0]
    root_member.rdf_types = [TKOS + "Outcome"]
    return pack


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
    pack = _typed_root_pack()
    result = render(pack, mode="deterministic")
    assert result["rendered"]["mode_used"] == "deterministic"
    assert result["rendered"]["content"]
    assert result["rendered"]["grounding_status"] == "structurally_validated"
    assert result["rendered"]["semantic_preservation"] == "not_proven"
    assert result["render_schema_version"] == "context-render/2.0"


def test_llm_with_fallback_degrades_on_missing_polisher():
    """llm_with_fallback must degrade to deterministic when polisher is None."""
    pack = _typed_root_pack()
    result = render(pack, mode="llm_with_fallback", polisher=None)
    assert result["rendered"]["mode_used"] == "deterministic_fallback"
    assert result["rendered"]["warnings"]
    assert result["rendered"]["grounding_status"] == "structurally_validated"


def test_llm_required_raises_on_missing_polisher():
    """llm_required must raise ValueError when no polisher provided.

    P0: pack needs a real root member so compile() succeeds and the
    polisher check is what raises (ghost roots raise before this point)."""
    pack = _typed_root_pack()
    with pytest.raises(ValueError, match="TextPolisher"):
        render(pack, mode="llm_required", polisher=None)


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

def test_max_chars_fact_unit_budget():
    """max_chars enforced as fact-unit budget, never char-level truncation.

    With 50 typed members and tight max_chars, only a subset fits;
    rest appear in render_omissions in decision_context."""
    pack = _pack(
        current_facts=[
            _member(f"m{i}", f"事实条目{i}", "graph-confirmed-enterprise", [],
                    status="Confirmed")
            for i in range(50)
        ],
        matched_root=TKOS + "m0",
    )
    # set rdf_types on all members so DCC classifies them
    for m in pack.current_facts:
        m.rdf_types = [TKOS + "Outcome"]

    result = render(pack, mode="deterministic", max_chars=600)
    content = result["rendered"]["content"]
    warnings = result["rendered"]["warnings"]
    # Fact-unit budget: some units omitted via decision_context
    omissions = result["decision_context"]["render_omissions"]
    assert len(omissions) > 0 or any("omitted" in w for w in warnings), \
        f"expected omissions or omission warnings, got omissions={len(omissions)}, warnings={warnings}"
    # No mid-sentence truncation — full footer is present
    assert "renderer:" in content
    assert "pack_id:" in content


# ---------------------------------------------------------------------------
# 10. resolve unaffected
# ---------------------------------------------------------------------------

def test_resolve_endpoint_still_works(monkeypatch):
    """Existing /resolve endpoint must be unaffected by render additions."""
    monkeypatch.setenv("TKOS_API_KEY", "test-key")
    from fastapi.testclient import TestClient
    from tkos_runtime.api.server import create_app

    client = TestClient(create_app())
    resp = client.post("/v1/context-packs:resolve", json={
        "enterprise_id": "tokenking", "organization_scope": [],
        "purpose": "decision_preparation",
        "query": "是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
        "as_of": "2026-08-11T23:59:59+08:00",
        "actor_id": "test",
    }, headers={"Authorization": "Bearer test-key"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["matched_root"]


# ---------------------------------------------------------------------------
# render endpoint integration
# ---------------------------------------------------------------------------

def test_render_endpoint_with_resolve_request(monkeypatch):
    """POST /render with resolve_request resolves + renders in one call."""
    monkeypatch.setenv("TKOS_API_KEY", "test-key")
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
    }, headers={"Authorization": "Bearer test-key"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["rendered"]["content"]
    # DCC v1 uses section-based format (not "当前已确认事实")
    assert body["rendered"]["mode_used"] == "deterministic"
    assert body["rendered"]["grounding_status"] == "structurally_validated"
    assert body["rendered"]["semantic_preservation"] == "not_proven"
    assert body["render_schema_version"] == "context-render/2.0"
    assert body["decision_context"]["compiler_version"] == "decision-context/v1"
    assert body["metadata"]["renderer_version"] == RENDERER_VERSION
    # include_structured
    assert body["structured"]["matched_root"]


def test_render_endpoint_with_pack_input(monkeypatch):
    """POST /render with a pre-resolved pack."""
    monkeypatch.setenv("TKOS_API_KEY", "test-key")
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
    }, headers={"Authorization": "Bearer test-key"})
    pack_dict = r1.json()

    # Then render the pack dict
    r2 = client.post("/v1/context-packs:render", json={
        "pack": pack_dict,
        "render_options": {"mode": "deterministic"},
    }, headers={"Authorization": "Bearer test-key"})
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["rendered"]["content"]


def test_render_client_supplied_pack_purpose_not_permitted_is_403(monkeypatch):
    """Client-supplied packs must NOT bypass the purpose gate (deployment
    blocker: purpose asserted only on the resolve_request branch)."""
    monkeypatch.setenv(
        "TKOS_API_KEYS_JSON",
        '{"k1": {"name": "restricted", "purposes": ["mission_review"]}}',
    )
    from fastapi.testclient import TestClient
    from tkos_runtime.api.server import create_app

    client = TestClient(create_app())
    # Pack declares decision_preparation, token only allows mission_review.
    pack_dict = pack_to_dict(_pack(purpose="decision_preparation"))
    resp = client.post("/v1/context-packs:render", json={
        "pack": pack_dict,
        "render_options": {"mode": "deterministic"},
    }, headers={"Authorization": "Bearer k1"})
    assert resp.status_code == 403, resp.text


def test_render_client_supplied_pack_permitted_purpose_is_200(monkeypatch):
    """A client-supplied pack whose purpose IS permitted still renders."""
    monkeypatch.setenv(
        "TKOS_API_KEYS_JSON",
        '{"k1": {"name": "restricted", "purposes": ["mission_review"]}}',
    )
    from fastapi.testclient import TestClient
    from tkos_runtime.api.server import create_app

    client = TestClient(create_app())
    pack_dict = pack_to_dict(_typed_root_pack(purpose="mission_review"))
    resp = client.post("/v1/context-packs:render", json={
        "pack": pack_dict,
        "render_options": {"mode": "deterministic"},
    }, headers={"Authorization": "Bearer k1"})
    assert resp.status_code == 200, resp.text


def test_render_both_inputs_is_422(monkeypatch):
    """Exactly one of pack or resolve_request required."""
    monkeypatch.setenv("TKOS_API_KEY", "test-key")
    from fastapi.testclient import TestClient
    from tkos_runtime.api.server import create_app

    client = TestClient(create_app())
    resp = client.post("/v1/context-packs:render", json={
        "pack": {"pack_id": "x"},
        "resolve_request": {"query": "x", "purpose": "decision_preparation"},
    }, headers={"Authorization": "Bearer test-key"})
    assert resp.status_code == 422, resp.text


def test_render_neither_input_is_422(monkeypatch):
    """Neither pack nor resolve_request → 422."""
    monkeypatch.setenv("TKOS_API_KEY", "test-key")
    from fastapi.testclient import TestClient
    from tkos_runtime.api.server import create_app

    client = TestClient(create_app())
    resp = client.post("/v1/context-packs:render", json={}, headers={"Authorization": "Bearer test-key"})
    assert resp.status_code == 422, resp.text


# ── Task 7: 422 envelope + e2e schema v2 ──────────────────────────────────

def test_render_budget_too_small_422_envelope(monkeypatch):
    """RenderBudgetTooSmall → HTTP 422 with detail envelope."""
    monkeypatch.setenv("TKOS_API_KEY", "test-key")
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
        "render_options": {"mode": "deterministic", "max_chars": 100},
    }, headers={"Authorization": "Bearer test-key"})
    assert resp.status_code == 422
    d = resp.json()["detail"]
    assert d["code"] == "render_budget_too_small"
    assert d["requested_max_chars"] == 100
    assert d["minimum_required_chars"] > 100


def test_render_response_schema_v2(monkeypatch):
    """Full render response carries v2 schema: render_schema_version,
    structurally_validated grounding, not_proven semantic_preservation,
    decision_context with compiler_version."""
    monkeypatch.setenv("TKOS_API_KEY", "test-key")
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
        "render_options": {"mode": "deterministic", "max_chars": 50000},
    }, headers={"Authorization": "Bearer test-key"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["render_schema_version"] == "context-render/2.0"
    assert body["rendered"]["grounding_status"] == "structurally_validated"
    assert body["rendered"]["semantic_preservation"] == "not_proven"
    assert body["rendered"]["rendering_status"] == "completed"
    assert body["decision_context"]["compiler_version"] == "decision-context/v1"
    # Gap contract: no "没有已知信息缺口" when gaps exist
    n_gaps = len(body["decision_context"]["gaps"])
    if n_gaps > 0:
        assert "没有已知信息缺口" not in body["rendered"]["content"]
    # Epistemic summary has no (B)-type phrases
    summary = body["decision_context"].get("epistemic_summary", "")
    for banned in ("尚不", "最可能", "建议您", "推荐"):
        assert banned not in summary, f"found banned phrase '{banned}' in: {summary}"
    # mode_used never llm_polished
    assert body["rendered"]["mode_used"] != "llm_polished"
    assert body["rendered"]["mode_used"] in (
        "deterministic", "deterministic_fallback",
        "llm_with_fallback", "llm_required",
    )


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


# ---------------------------------------------------------------------------
# P1-2: forged / minimal pack rejection
# ---------------------------------------------------------------------------

def test_forged_pack_missing_governance_fields_is_rejected():
    """Minimal pack without dataset_revision/ontology_release_id → ValueError."""
    with pytest.raises(ValueError, match="dataset_revision"):
        dict_to_pack({"pack_id": "forged"})

    with pytest.raises(ValueError, match="ontology_release_id"):
        dict_to_pack({
            "pack_id": "forged",
            "dataset_revision": "a" * 64,
        })


def test_valid_pack_with_governance_fields_is_accepted():
    """Pack with both governance fields present → accepted."""
    pack = dict_to_pack({
        "pack_id": "validated-pack",
        "dataset_revision": "a" * 64,
        "ontology_release_id": "2.4.0",
    })
    assert pack.pack_id == "validated-pack"
    assert pack.dataset_revision == "a" * 64


# ---------------------------------------------------------------------------
# P1-2: pack_origin → grounding_status
# ---------------------------------------------------------------------------

def test_client_supplied_pack_records_pack_origin():
    """Client-supplied packs record pack_origin in metadata (v2: grounding always structurally_validated)."""
    pack = _typed_root_pack(display="事实")
    result = render(pack, mode="deterministic", pack_origin="client_supplied")
    assert result["rendered"]["grounding_status"] == "structurally_validated"
    assert result["metadata"]["pack_origin"] == "client_supplied"


def test_server_resolved_pack_records_pack_origin():
    """Server-resolved packs record pack_origin in metadata (v2: grounding always structurally_validated)."""
    pack = _typed_root_pack(display="事实")
    result = render(pack, mode="deterministic", pack_origin="server_resolved")
    assert result["rendered"]["grounding_status"] == "structurally_validated"
    assert result["metadata"]["pack_origin"] == "server_resolved"


# ---------------------------------------------------------------------------
# P1-3: gap dedup — context_gap members excluded from candidate_context section
# ---------------------------------------------------------------------------

def test_gap_members_not_duplicated_in_candidate_section():
    """Members appearing in both candidate_context and context_gaps must
    only appear under 信息缺口, not under 待确认信息."""
    pack = _pack(
        candidate_context=[
            _member("shared", "共享条目", "graph-candidate-and-dispute", [],
                    status="Candidate"),
            _member("cand-only", "仅候选", "graph-candidate-and-dispute", [],
                    status="Candidate"),
        ],
        context_gaps=[
            _member("shared", "共享条目", "graph-candidate-and-dispute", [],
                    status="Candidate"),
        ],
    )
    result = _render_deterministic(pack)
    # "shared" should appear exactly once (under 信息缺口)
    assert result.count("[member:shared]") == 1
    # "cand-only" should appear under 待确认信息
    cand_section_start = result.index("待确认信息")
    gap_section_start = result.index("信息缺口")
    cand_only_pos = result.index("[member:cand-only]")
    shared_pos = result.index("[member:shared]")
    assert cand_section_start < cand_only_pos < gap_section_start
    assert shared_pos > gap_section_start


# ---------------------------------------------------------------------------
# P1-1: adversarial LLM output validation (deterministic validator tests)
# ---------------------------------------------------------------------------

from tkos_runtime.application.context_renderer import (
    RenderedFactUnit,
    _validate_llm_output,
)

_MOCK_CURRENT_FACT = RenderedFactUnit(
    member_id="urn:test:m1",
    partition="graph-confirmed-enterprise",
    source_graphs=("graph-confirmed-enterprise",),
    canonical_claim="Q3 营收增长 15%",
    confirmation_status="Confirmed",
)

_MOCK_CANDIDATE_FACT = RenderedFactUnit(
    member_id="urn:test:c1",
    partition="graph-candidate-and-dispute",
    source_graphs=("graph-candidate-and-dispute",),
    canonical_claim="灯塔项目预计延迟 2 周交付",
    confirmation_status="Candidate",
)


def _wrap_in_markdown(text: str) -> str:
    return (
        "# Context Pack：测试\n\n"
        "> 查询时间：2026-08-12  |  用途：decision_preparation  |  数据版本：`abc123…`\n\n"
        "## 当前已确认事实\n\n"
        + text +
        "\n\n## 待确认信息\n\n"
        "## 信息缺口\n\n当前没有已知信息缺口。\n\n"
        "## 决策参考来源\n\n当前没有决策参考来源记录。\n\n"
        "> 推理状态：not_available\n"
    )


def test_validator_rejects_fabricated_revenue():
    """LLM added a fabricated revenue claim → validation must fail."""
    deterministic = _wrap_in_markdown(
        "- Q3 营收增长 15% [member:urn:test:m1][source:graph-confirmed-enterprise]"
    )
    polished = _wrap_in_markdown(
        "- Q3 营收增长 15%，已超额完成全年目标 200% [member:urn:test:m1][source:graph-confirmed-enterprise]"
    )
    valid, warnings = _validate_llm_output(
        [_MOCK_CURRENT_FACT], polished, deterministic_text=deterministic
    )
    assert not valid
    assert any("new numbers" in w.lower() or "injected" in w.lower() for w in warnings)


def test_validator_rejects_forged_source_graph():
    """LLM added a forged source anchor → validation must fail."""
    deterministic = _wrap_in_markdown(
        "- Q3 营收增长 15% [member:urn:test:m1][source:graph-confirmed-enterprise]"
    )
    polished = _wrap_in_markdown(
        "- Q3 营收增长 15% [member:urn:test:m1][source:graph-sensitive-restricted]"
    )
    valid, warnings = _validate_llm_output(
        [_MOCK_CURRENT_FACT], polished, deterministic_text=deterministic
    )
    assert not valid
    assert any("forged source" in w.lower() for w in warnings)


def test_validator_rejects_phantom_member_id():
    """LLM invented a member ID not in the original pack → validation must fail."""
    original = [
        _MOCK_CURRENT_FACT,
        RenderedFactUnit(
            member_id="urn:test:c1",
            partition="graph-candidate-and-dispute",
            source_graphs=("graph-candidate-and-dispute",),
            canonical_claim="灯塔项目预计延迟 2 周交付",
        ),
    ]
    deterministic = _wrap_in_markdown(
        "- Q3 营收增长 15% [member:urn:test:m1][source:graph-confirmed-enterprise]\n"
        "- 灯塔项目预计延迟 2 周交付 [member:urn:test:c1][source:graph-candidate-and-dispute]"
    )
    polished = _wrap_in_markdown(
        "- Q3 营收增长 15% [member:urn:test:m1][source:graph-confirmed-enterprise]\n"
        "- 灯塔项目预计延迟 2 周交付 [member:urn:test:c1][source:graph-candidate-and-dispute]\n"
        "- 新增虚假事实：竞品已倒闭 [member:urn:test:phantom][source:graph-candidate-and-dispute]"
    )
    valid, warnings = _validate_llm_output(
        original, polished, deterministic_text=deterministic
    )
    assert not valid
    assert any("phantom" in w.lower() for w in warnings)


def test_validator_rejects_candidate_in_current_section():
    """LLM moved a candidate fact into 当前已确认事实 section → validation must fail."""
    deterministic = (
        "# Context Pack：测试\n\n"
        "> 查询时间：2026-08-12  |  用途：decision_preparation  |  数据版本：`abc123…`\n\n"
        "## 当前已确认事实\n\n"
        "- Q3 营收增长 15% [member:urn:test:m1][source:graph-confirmed-enterprise]\n\n"
        "## 待确认信息\n\n"
        "- 灯塔项目预计延迟 2 周交付 [member:urn:test:c1][source:graph-candidate-and-dispute]\n\n"
    )
    polished = (
        "# Context Pack：测试\n\n"
        "> 查询时间：2026-08-12  |  用途：decision_preparation  |  数据版本：`abc123…`\n\n"
        "## 当前已确认事实\n\n"
        "- Q3 营收增长 15% [member:urn:test:m1][source:graph-confirmed-enterprise]\n"
        "- 灯塔项目预计延迟 2 周交付 [member:urn:test:c1][source:graph-candidate-and-dispute]\n\n"
        "## 待确认信息\n\n"
        "当前没有待确认的候选信息。\n\n"
    )
    valid, warnings = _validate_llm_output(
        [_MOCK_CURRENT_FACT, _MOCK_CANDIDATE_FACT], polished,
        deterministic_text=deterministic,
    )
    assert not valid
    assert any("candidate" in w.lower() for w in warnings)


def test_validator_passes_clean_output():
    """Clean LLM output that preserves all anchors and facts → validation passes."""
    deterministic = _wrap_in_markdown(
        "- Q3 营收增长 15% [member:urn:test:m1][source:graph-confirmed-enterprise]"
    )
    polished = deterministic  # LLM kept everything unchanged
    valid, warnings = _validate_llm_output(
        [_MOCK_CURRENT_FACT], polished, deterministic_text=deterministic
    )
    assert valid, f"warnings: {warnings}"
    assert not warnings


def test_validator_detects_missing_member():
    """LLM dropped a member → validation must fail."""
    deterministic = _wrap_in_markdown(
        "- Q3 营收增长 15% [member:urn:test:m1][source:graph-confirmed-enterprise]\n"
        "- 灯塔项目预计延迟 2 周交付 [member:urn:test:c1][source:graph-candidate-and-dispute]"
    )
    polished = _wrap_in_markdown(
        "- Q3 营收增长 15% [member:urn:test:m1][source:graph-confirmed-enterprise]"
    )
    # c1 is in original but not in polished
    valid, warnings = _validate_llm_output(
        [_MOCK_CURRENT_FACT, _MOCK_CANDIDATE_FACT], polished,
        deterministic_text=deterministic,
    )
    assert not valid
    assert any("missing member" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# P1-1b: URI boundary — CJK punctuation must terminate URL extraction
# ---------------------------------------------------------------------------

def test_validator_same_url_with_changed_cjk_punctuation_passes():
    """Same URL with surrounding Chinese punctuation changed → must pass.

    Regression: the old greedy regex captured ``https://x.example/；首批场景``
    as one URI, so removing a bracket made the strings diverge and triggered
    a false positive. The URL itself is unchanged.
    """
    deterministic = _wrap_in_markdown(
        "- 灯塔场景见 https://meeting-green-phi.vercel.app/（首批词元云集场景）"
        " [member:urn:test:m1][source:graph-confirmed-enterprise]"
    )
    # LLM removed the full-width parentheses around the trailing text — URL unchanged
    polished = _wrap_in_markdown(
        "- 灯塔场景见 https://meeting-green-phi.vercel.app/；首批词元云集场景"
        " [member:urn:test:m1][source:graph-confirmed-enterprise]"
    )
    valid, warnings = _validate_llm_output(
        [_MOCK_CURRENT_FACT], polished, deterministic_text=deterministic,
    )
    assert valid, f"false positive: {warnings}"


def test_validator_new_url_injected_is_rejected():
    """A genuinely new URL not in the deterministic baseline → must fail."""
    deterministic = _wrap_in_markdown(
        "- Q3 营收增长 15% [member:urn:test:m1][source:graph-confirmed-enterprise]"
    )
    polished = _wrap_in_markdown(
        "- Q3 营收增长 15%，详见 https://evil.example.com/report.pdf"
        " [member:urn:test:m1][source:graph-confirmed-enterprise]"
    )
    valid, warnings = _validate_llm_output(
        [_MOCK_CURRENT_FACT], polished, deterministic_text=deterministic,
    )
    assert not valid
    assert any("new uris" in w.lower() for w in warnings)
