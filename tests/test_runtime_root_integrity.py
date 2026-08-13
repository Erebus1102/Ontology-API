# tests/test_runtime_root_integrity.py
"""P0 修复（Bedrock 错配事故）—— 编译器层根节点完整性。

故障链实锤（复现报告）：
  matched_root 是 StrategicResearch → decisions section
  → mandatory_view_keys 只在 issue section 找 root → root 不被保护
  → 6000 预算将 root 裁剪 → root_unit 查找落空
  → fallback 到第一个 StrategicIssue → "问 Bedrock 答灯塔"

本文件覆盖 P0-1（root 全局强制项）/ P0-2（删除 fallback）/
P0-3（一致性硬校验）/ P0-4（anchor 契约 + 任意类型可编译）：
  1. 非 Issue 类型的 root（Research/Outcome/Mission）同为 mandatory view
  2. root 永不进入 render_omissions
  3. 小预算 → RenderBudgetTooSmall（422），绝不裁剪 root 或另选议题
  4. root 视图缺失 → ContextRootMissingError，绝不 fallback 到无关 issue
  5. issue.member_id 与 fragment(matched_root) 始终一致
  6. anchor.member_id == fragment(matched_root)；正文含 root 三段锚点
  7. 任意类型 root 可编译（通用 anchor 单元，评审 B4 反例：
     CompetitiveBarrier 不在 ROLE_TABLE，修复前编译 500）
  8. 非 Issue root 的 Markdown 与结构化一致（评审 B3 反例：research
     root 是锚点，FE issue 只作关联经营议题）
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from tkos_runtime.domain.models import (
    AdmissionDecision, ContextPack, ContextPackMember, ContextRootMissingError,
    GraphStatement, ScopeResolution,
)
from tkos_runtime.application.decision_context_compiler import (
    DecisionContextCompiler, mandatory_view_keys, mandatory_floor,
    _build_units_by_section, build_type_index, build_name_index,
)
from tkos_runtime.application.context_renderer import render
from tkos_runtime.domain.render_units import (
    RenderBudgetTooSmall, SECTION_ORDER,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "ontology/schema/tkos-ontology.jsonld"
DATASET = ROOT / "ontology/datasets/tkos-runtime-dataset.trig"
INSTANCES = sorted((ROOT / "data" / "instances").glob("*.trig"))

TKOS = "https://ontology.tokenking.ai/tkos#"


def _units_from_pack(pack):
    """Build units_by_section exactly as DecisionContextCompiler.compile does."""
    return _build_units_by_section(
        pack, build_type_index(pack), build_name_index(pack)[0],
    )


def _m(mid, partition, types, statements=()):
    return ContextPackMember(id=mid, display_name=mid, scope=None, partition=partition,
        statements=list(statements), source_graphs=[partition], confirmation_status=None,
        lifecycle=None, valid_from=None, valid_until=None, sources=[],
        admission=AdmissionDecision(True, partition), rdf_types=[TKOS + t for t in types])


def _edge(subject, predicate, obj, graph="graph-candidate-and-dispute"):
    return GraphStatement(subject=TKOS + subject, predicate=TKOS + predicate,
                          object=TKOS + obj, source_graph=graph)


def _pack(**overrides):
    defaults = dict(
        pack_id="test", schema_version="1.0",
        as_of="2026-08-13T00:00:00+08:00", query="q",
        purpose="decision_preparation", matched_root="urn:test:root",
        alternative_matches=[], scope_resolution=ScopeResolution([], [], "not_enforced", ""),
        current_facts=[], candidate_context=[], provenance_context=[],
        proof=[], derived_claims=[], reasoning_status="not_available",
        context_gaps=[], conflicts=[], omissions=[],
        contributing_graphs=[], admission_policy="",
        ontology_release_id="2.4.0", dataset_revision="a" * 64,
        policy_version="read-admission/p0-v1", query_plan_version="bfs-2gram/p0-v1",
    )
    defaults.update(overrides)
    return ContextPack(**defaults)


def _research_root_pack(**overrides):
    """matched_root 为 StrategicResearch（归 decisions section）。

    修复前：root 不在 mandatory（仅在 issue section 查找）→ 可被裁剪；
    被裁后 root_unit 落空 → fallback 选择 issue-other（错配）。
    """
    defaults = dict(
        candidate_context=[
            _m("research-root", "graph-candidate-and-dispute", ["StrategicResearch"]),
            _m("issue-other", "graph-candidate-and-dispute", ["StrategicIssue"]),
            _m("outcome-1", "graph-candidate-and-dispute", ["Outcome"]),
            _m("risk-1", "graph-candidate-and-dispute", ["Risk"]),
        ],
        matched_root=TKOS + "research-root",
    )
    defaults.update(overrides)
    return _pack(**defaults)


def _selected_ids(compiled) -> set[str]:
    return {u.member_id for sec in compiled.units_by_section.values() for u in sec}


# ── P0-1: 非 Issue root 同为 mandatory view ──────────────────────────────

def test_non_issue_root_is_mandatory_view():
    """StrategicResearch root 必须进入 mandatory keys（修复前只找 issue section）。"""
    pack = _research_root_pack()
    compiled = DecisionContextCompiler().compile(pack, max_chars=8000)
    # root 行在最终视图中（不因类型被漏保护）
    assert "research-root" in _selected_ids(compiled)
    # root 不在 render_omissions
    assert all(o.member_id != "research-root" for o in compiled.omissions)


def test_root_mandatory_across_all_sections():
    """mandatory_view_keys 必须在全部 section 中按 member_id 查找 root。"""
    pack = _research_root_pack()
    units = _units_from_pack(pack)
    keys = mandatory_view_keys(pack, units)
    assert any(k[0] == "research-root" for k in keys), keys


def test_outcome_root_is_mandatory_too():
    """Outcome 类型 root 同样受保护（实体查询合法化）；
    三审契约：非 StrategicIssue root 的 issue = null，anchor = root。"""
    pack = _pack(
        candidate_context=[
            _m("outcome-root", "graph-candidate-and-dispute", ["Outcome"]),
            _m("issue-other", "graph-candidate-and-dispute", ["StrategicIssue"]),
            _m("risk-1", "graph-candidate-and-dispute", ["Risk"]),
        ],
        matched_root=TKOS + "outcome-root",
    )
    compiled = DecisionContextCompiler().compile(pack, max_chars=8000)
    dc = compiled.decision_context
    assert dc["issue"] is None
    assert dc["anchor"]["member_id"] == "outcome-root"
    assert all(o.member_id != "outcome-root" for o in compiled.omissions)


# ── P0-2: 小预算拒绝而非替换 root ───────────────────────────────────────

def test_small_budget_raises_not_root_replacement():
    """预算容不下 mandatory（含 root）→ RenderBudgetTooSmall(422)；
    绝不裁剪 root 后 fallback 到另一个 issue（修复前的错配路径）。"""
    pack = _research_root_pack()
    with pytest.raises(RenderBudgetTooSmall):
        DecisionContextCompiler().compile(pack, max_chars=300)


def test_missing_root_view_raises_not_fallback():
    """matched_root 视图在 pack 中不存在（完整性错误）→ ContextRootMissingError；
    绝不静默 fallback 到第一个 issue 角色成员。"""
    pack = _research_root_pack(matched_root=TKOS + "ghost-root")
    with pytest.raises(ContextRootMissingError) as ei:
        DecisionContextCompiler().compile(pack, max_chars=8000)
    assert "ghost-root" in str(ei.value)
    assert ei.value.matched_root == TKOS + "ghost-root"
    assert ei.value.stage == "decision_context_compilation"


# ── P0-3: 一致性断言 ────────────────────────────────────────────────────

def test_issue_only_for_strategic_issue_root():
    """三审契约：issue 只承载 StrategicIssue——issue root 时 member_id
    精确等于 matched_root 的 fragment（不再另选），matched_root 原样保留。"""
    pack = _pack(
        candidate_context=[
            _m("issue-root", "graph-candidate-and-dispute", ["StrategicIssue"]),
            _m("risk-1", "graph-candidate-and-dispute", ["Risk"]),
        ],
        matched_root=TKOS + "issue-root",
    )
    compiled = DecisionContextCompiler().compile(pack, max_chars=8000)
    dc = compiled.decision_context
    assert dc["issue"]["member_id"] == "issue-root"
    assert dc["issue"]["matched_root"] == TKOS + "issue-root"
    assert dc["anchor"]["member_id"] == "issue-root"


def test_issue_none_for_non_issue_root():
    """三审契约：Research root 的 issue 必须为 null（研究对象 ≠ 经营
    议题），anchor 仍 = matched_root。"""
    pack = _research_root_pack()
    compiled = DecisionContextCompiler().compile(pack, max_chars=8000)
    dc = compiled.decision_context
    assert dc["issue"] is None
    assert dc["anchor"]["member_id"] == "research-root"


def test_anchor_contract_matches_root_and_query():
    """query_context / anchor / related_issue 契约（评审 B3 + 三审：
    related_issue 必须有显式业务边证据）。"""
    pack = _research_root_pack(
        candidate_context=[
            _m("research-root", "graph-candidate-and-dispute", ["StrategicResearch"]),
            _m("issue-other", "graph-candidate-and-dispute", ["StrategicIssue"],
               statements=[_edge("issue-other", "researchedBy", "research-root")]),
            _m("outcome-1", "graph-candidate-and-dispute", ["Outcome"]),
            _m("risk-1", "graph-candidate-and-dispute", ["Risk"]),
        ],
    )
    compiled = DecisionContextCompiler().compile(pack, max_chars=8000)
    dc = compiled.decision_context
    assert dc["query_context"] == {"query": pack.query}
    assert dc["anchor"]["member_id"] == "research-root"
    assert dc["anchor"]["type"] == "StrategicResearch"
    assert dc["anchor"]["view_key"] == ["research-root", "graph-candidate-and-dispute"]
    # 边证据：issue-other researchedBy research-root → 谓词与边 source_graph
    assert dc["related_issue"]["member_id"] == "issue-other"
    assert dc["related_issue"]["predicate"] == "researchedBy"
    assert dc["related_issue"]["edge_source_graph"] == "graph-candidate-and-dispute"


def test_related_issue_none_without_edge():
    """三审契约：root 与 issue 之间无显式业务边 → related_issue = null
    （修复前 issue-other 无任何语句连接 root 仍被判定为关联）。"""
    pack = _research_root_pack()
    compiled = DecisionContextCompiler().compile(pack, max_chars=8000)
    assert compiled.decision_context["related_issue"] is None


def test_any_type_root_compiles_generic_anchor():
    """B4 反例（用户审定选项 2）：非 ROLE_TABLE 类型 root（CompetitiveBarrier）
    必须可编译 —— 通用 anchor 单元。修复前 ContextRootMissingError（500）。"""
    pack = _pack(
        candidate_context=[
            _m("barrier-five-control-points", "graph-candidate-and-dispute",
               ["CompetitiveBarrier"]),
            _m("issue-other", "graph-candidate-and-dispute", ["StrategicIssue"]),
            _m("risk-1", "graph-candidate-and-dispute", ["Risk"]),
        ],
        matched_root=TKOS + "barrier-five-control-points",
    )
    compiled = DecisionContextCompiler().compile(pack, max_chars=8000)
    dc = compiled.decision_context
    assert dc["anchor"]["member_id"] == "barrier-five-control-points"
    assert dc["anchor"]["type"] == "CompetitiveBarrier"
    # 三审契约：非 StrategicIssue root → issue = null；issue-other 无边
    # （无语句连接 root）→ related_issue = null
    assert dc["issue"] is None
    assert dc["related_issue"] is None
    # 正文含 root 完整三段锚点 + 关联经营议题章节。评审四审契约：无显式
    # 业务边的 StrategicIssue 不进"关联经营议题"（与 related_issue=null
    # 同生同灭）——修复前正文仍输出 issue-other，与结构化结果矛盾。
    content = render(pack, mode="deterministic", max_chars=8000)["rendered"]["content"]
    assert "[member:barrier-five-control-points]" in content
    assert "## 关联经营议题" in content
    related_block = content.split("## 关联经营议题")[1].split("## 决策目标")[0]
    assert "[member:issue-other]" not in related_block
    assert "（无）" in related_block


def test_related_issue_view_granularity_two_partitions():
    """评审四审契约：proven 视图按 view_key=(member_id, partition) 粒度，
    不按 member_id 合并跨分区视图。同 member 双分区、边只声明在其中一个
    分区 → 两个 proven 视图都进"关联经营议题"章节；related_issue 取稳定
    排序序首的视图（候选分区在前）。"""
    pack = _pack(
        candidate_context=[
            _m("research-root", "graph-candidate-and-dispute",
               ["StrategicResearch"]),
            # 无边的分区视图：issue-other 自身不声明任何连接 root 的语句
            _m("issue-other", "graph-candidate-and-dispute", ["StrategicIssue"]),
            # 声明边的分区视图：researchedBy 边只在此视图的语句中
            _m("issue-other", "graph-edge-view", ["StrategicIssue"],
               statements=[_edge("issue-other", "researchedBy", "research-root",
                                 graph="graph-edge-view")]),
            _m("outcome-1", "graph-candidate-and-dispute", ["Outcome"]),
            _m("risk-1", "graph-candidate-and-dispute", ["Risk"]),
        ],
        matched_root=TKOS + "research-root",
    )
    compiled = DecisionContextCompiler().compile(pack, max_chars=8000)
    dc = compiled.decision_context
    # related_issue 视图粒度：view_key 保留 (member_id, partition)
    assert dc["related_issue"]["view_key"] == [
        "issue-other", "graph-candidate-and-dispute"]
    assert dc["related_issue"]["member_id"] == "issue-other"
    assert dc["related_issue"]["predicate"] == "researchedBy"
    assert dc["related_issue"]["edge_source_graph"] == "graph-edge-view"
    # 两个分区视图都进 issue 章节（proven 成员的全部视图，不合并）
    issue_units = compiled.units_by_section["issue"]
    assert sorted((u.member_id, u.partition) for u in issue_units) == [
        ("issue-other", "graph-candidate-and-dispute"),
        ("issue-other", "graph-edge-view"),
    ]
    # proven 视图为 mandatory —— 预算收紧时仍不可裁剪（结构/正文强一致）
    with pytest.raises(RenderBudgetTooSmall):
        DecisionContextCompiler().compile(pack, max_chars=300)
    # Markdown 双视图行 + 相关结构化一致
    content = render(pack, mode="deterministic", max_chars=8000)["rendered"]["content"]
    assert "[member:issue-other][partition:graph-candidate-and-dispute]" in content
    assert "[member:issue-other][partition:graph-edge-view]" in content


def test_research_root_markdown_anchor_consistency():
    """B3 反例（全链路）：非 Issue root 的 Markdown 必须与结构化一致 ——
    research root 是本体匹配锚点；FE issue 只作为关联经营议题呈现，
    不得被表述为用户本次决策议题。"""
    from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
    from tkos_runtime.adapters.gram_intent_resolver import GramIntentResolver
    from tkos_runtime.adapters.rdflib_graph_retriever import RdfGraphRetriever
    from tkos_runtime.application.context_compiler import ContextCompiler
    from tkos_runtime.application.context_pack_resolver import ContextPackResolver
    from tkos_runtime.domain.policies import AdmissionPolicy

    store = RdfDatasetStore(SCHEMA, DATASET, INSTANCES, release_root=ROOT)
    resolver = ContextPackResolver(
        store, GramIntentResolver(store),
        RdfGraphRetriever(store), ContextCompiler(store, AdmissionPolicy()),
    )
    pack = resolver.resolve(
        "产品 1.0 与灯塔交付研究结论是什么", "decision_preparation",
        datetime.fromisoformat("2026-08-13T23:59:59+08:00"), [])
    result = render(pack, mode="deterministic", max_chars=12000)
    content = result["rendered"]["content"]
    dc = result["decision_context"]

    RESEARCH = "research-product1-lighthouse-schedule-and-delivery"
    FE_ISSUE = "issue-product1-lighthouse-synchronous-delivery"
    assert dc["anchor"]["member_id"] == RESEARCH
    # 三审契约：research root 的 issue = null；related_issue 必须有真实
    # 业务边证据（issue researchedBy research，数据中唯一 TRAVERSAL 边）
    assert dc["issue"] is None
    assert dc["related_issue"]["member_id"] == FE_ISSUE
    assert dc["related_issue"]["predicate"] == "researchedBy"
    assert dc["related_issue"]["edge_source_graph"] == "graph-candidate-and-dispute"

    anchor_block = content.split("## 本体匹配锚点")[1].split("## 关联经营议题")[0]
    assert f"[member:{RESEARCH}]" in anchor_block
    related_block = content.split("## 关联经营议题")[1].split("## 决策目标")[0]
    assert f"[member:{FE_ISSUE}]" in related_block
    # FE issue 不能出现在锚点区块；research root 不能出现在关联议题区块
    assert f"[member:{FE_ISSUE}]" not in anchor_block
    assert RESEARCH not in related_block


def test_root_integrity_under_tight_budget_at_floor():
    """max_chars == 含 root 的 floor：root 必须存活且完整，其余被裁。"""
    pack = _research_root_pack()
    units = _units_from_pack(pack)
    keys = mandatory_view_keys(pack, units)
    # floor 是真实装配长度：root + 固定文本 + 全部非 mandatory 的 omission 摘要
    f = mandatory_floor(pack, units, keys)
    tight = DecisionContextCompiler().compile(pack, max_chars=f)
    assert "research-root" in _selected_ids(tight)
    assert all(o.member_id != "research-root" for o in tight.omissions)
