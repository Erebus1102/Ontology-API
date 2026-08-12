# tests/test_runtime_dcc_e2e.py
"""DCC v1 review round (r4): 真实 FE 议题的十八条端到端断言。

Resolves the real FE issue ("是否在本季度同时完成产品 1.0 上线和灯塔项目交付")
through the full stack (store -> resolver -> DecisionContextCompiler -> render)
and asserts the five P1 contract fixes plus the r4 Render Schema v2 contract:

  P1-1  max_chars 硬断言：先按 slot 选单元、后测真实 Markdown 长度、
        从最低优先级回收；省略仅计入非可回收项（缺口与根议题不可回收）。
  P1-2  根议题取自 pack.matched_root：view_key/query/matched_root/
        epistemic_summary 全部落入 decision_context.issue。
  P1-3  信息缺口去重：真实 FE 议题恰好 8 项缺口，每个 view_key 恰好一次。
  P1-4  EchoPolisher（回显 stub）经 llm_with_fallback 通路必须通过
        section-aware 校验（mode_used = llm_with_fallback，无校验失败）。
  P1-5  view_key 锚点校验：对真实内容做 swapped-partition / swapped-source
        攻击必须被拒绝（phantom/missing + 对应 swapped 告警）。
  r4    Render Schema v2：render_schema_version / grounding_status /
        semantic_preservation / mode_used 枚举。
"""
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

TKOS = "https://ontology.tokenking.ai/tkos#"
QUERY = "是否在本季度同时完成产品 1.0 上线和灯塔项目交付"
AS_OF = datetime.fromisoformat("2026-08-11T23:59:59+08:00")
MAX_CHARS = 6000

ROOT_FRAG = "issue-product1-lighthouse-synchronous-delivery"
ROOT_PARTITION = "graph-candidate-and-dispute"
ISSUE = TKOS + ROOT_FRAG
N_EXPECTED_GAPS = 8

ANCHOR_RE = re.compile(
    r"\[member:([^\]]+)\]\[partition:([^\]]+)\]\[source:([^\]]+)\]"
)


def _resolve_real_fe_issue():
    """Full-stack resolve of the real FE issue (same wiring as Phase-A tests)."""
    from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
    from tkos_runtime.adapters.gram_intent_resolver import GramIntentResolver
    from tkos_runtime.adapters.rdflib_graph_retriever import RdfGraphRetriever
    from tkos_runtime.application.context_compiler import ContextCompiler
    from tkos_runtime.application.context_pack_resolver import ContextPackResolver
    from tkos_runtime.domain.policies import AdmissionPolicy

    store = RdfDatasetStore(
        ROOT / "ontology" / "schema" / "tkos-ontology.jsonld",
        ROOT / "ontology" / "datasets" / "tkos-runtime-dataset.trig",
        sorted((ROOT / "data" / "instances").glob("*.trig")),
        release_root=ROOT,
    )
    resolver = ContextPackResolver(
        store, GramIntentResolver(store),
        RdfGraphRetriever(store),
        ContextCompiler(store, AdmissionPolicy()),
    )
    return resolver.resolve(QUERY, "decision_preparation", AS_OF, [])


def _anchors(text: str) -> list[tuple[str, str, str]]:
    """Per-line complete-anchor parse: (member, partition, source)."""
    found: list[tuple[str, str, str]] = []
    for line in text.split("\n"):
        for m in ANCHOR_RE.finditer(line):
            found.append((m.group(1), m.group(2), m.group(3)))
    return found


class EchoPolisher:
    """Test stub: 原样回显确定性文本，验证 llm_with_fallback 校验通路。"""

    def polish(self, text: str, language: str = "zh-CN") -> str:
        return text


def test_fe_issue_r4_eighteen_assertions():
    """真实 FE 议题十八条端到端断言（5 项 P1 + r4 契约）。"""
    from tkos_runtime.application.context_renderer import (
        _validate_llm_output, render,
    )
    from tkos_runtime.application.decision_context_compiler import (
        DecisionContextCompiler,
    )

    pack = _resolve_real_fe_issue()
    assert pack.matched_root == ISSUE

    # compile once — reused by render() and by the P1-5 attack validations
    compiled = DecisionContextCompiler().compile(pack, max_chars=MAX_CHARS)

    result = render(pack, mode="deterministic", max_chars=MAX_CHARS)
    content = result["rendered"]["content"]
    dc = result["decision_context"]
    omissions = dc["render_omissions"]
    gap_ids = {g.id for g in pack.context_gaps}

    # ── P1-1: max_chars 硬断言（先选单元、后测真实长度、低优先级回收）──
    # 1. 最终长度必须 <= max_chars（不可软跳过）
    assert len(content) <= MAX_CHARS, f"len={len(content)} > {MAX_CHARS}"
    # 2. 省略项全部可回收：缺口与根议题不可进入 render_omissions
    assert all(
        o["member_id"] not in gap_ids and o["member_id"] != ROOT_FRAG
        for o in omissions
    ), f"non-reclaimable omissions: {omissions}"

    # ── P1-2: 根议题取自 matched_root，字段齐备 ──
    # 3. 根议题 member_id 精确等于 matched_root 的 fragment
    assert dc["issue"]["member_id"] == ROOT_FRAG
    # 4. matched_root 原样落入 issue
    assert dc["issue"]["matched_root"] == ISSUE
    # 5. 查询原样落入 issue
    assert dc["issue"]["query"] == QUERY
    # 6. view_key = (member, partition) 精确匹配根议题所在视图
    assert dc["issue"]["view_key"] == [ROOT_FRAG, ROOT_PARTITION]
    # 7. epistemic_summary 在 issue 构建前计算并填充
    assert dc["issue"]["epistemic_summary"] and "候选视图" in dc["issue"]["epistemic_summary"]
    # 8. 根议题锚点行出现在 决策议题 章节
    issue_section = re.search(
        r"# 决策议题(.*?)(?=## 决策目标|\Z)", content, re.DOTALL
    ).group(1)
    assert f"[member:{ROOT_FRAG}]" in issue_section

    # ── P1-3: 信息缺口去重（每个 view_key 恰好一次）──
    # 9. 真实 FE 议题恰好 8 项缺口（回归断言：修复前为 16）
    assert len(dc["gaps"]) == N_EXPECTED_GAPS, f"gaps={len(dc['gaps'])}"
    # 10. 8 个 view_key 全部唯一
    gap_vks = [(g["member_id"], g["partition"]) for g in dc["gaps"]]
    assert len(set(gap_vks)) == N_EXPECTED_GAPS
    # 11. 缺口成员全部来自 pack.context_gaps（无伪造、无跨桶泄漏）
    assert {g["member_id"] for g in dc["gaps"]} == gap_ids
    # 12. 每个缺口 view_key 在正文中恰好出现一次（精确多重集比较）
    expected_gap_anchors = {
        (g["member_id"], g["partition"], (g["source_graphs"] or ["unknown"])[0])
        for g in dc["gaps"]
    }
    parsed = _anchors(content)
    assert all(
        parsed.count(a) == 1 for a in expected_gap_anchors
    ), f"gap anchor multiplicity: {expected_gap_anchors} vs {parsed}"
    # 13. 缺口锚点全部落在 拍板前需要补齐的信息 章节
    gaps_section = re.search(
        r"## 拍板前需要补齐的信息(.*?)(?=## 决策与判断依据|\Z)", content, re.DOTALL
    ).group(1)
    assert all(f"[member:{m}]" in gaps_section for m in gap_ids)

    # ── P1-4: EchoPolisher 经 llm_with_fallback 必须通过 section 校验 ──
    llm = render(
        pack, mode="llm_with_fallback", max_chars=MAX_CHARS,
        polisher=EchoPolisher(),
    )
    # 14. 回显文本通过校验 → 使用 LLM 模式产物
    assert llm["rendered"]["mode_used"] == "llm_with_fallback"
    # 15. 无校验失败告警（无 phantom/missing/duplicate/swapped/section 告警）
    llm_warnings = llm["rendered"]["warnings"]
    assert not any(
        w in ("LLM output failed validation; using deterministic renderer.",
              f"LLM unavailable ({'EchoPolisher'}), using deterministic renderer.")
        or "phantom view_keys" in w or "missing view_keys" in w
        or "has swapped" in w or "appears" in w and "times" in w
        for w in llm_warnings
    ), f"validation warnings: {llm_warnings}"

    # ── P1-5: view_key 锚点攻击必须被拒绝 ──
    lines = content.split("\n")
    # 16. swapped-partition：同一 member 两视图（candidate/provenance）互换 partition
    i_cand = next(i for i, l in enumerate(lines)
                  if "[member:mission-outcome-fe-m2-lighthouse-loop]"
                  "[partition:graph-candidate-and-dispute]" in l)
    i_prov = next(i for i, l in enumerate(lines)
                  if "[member:mission-outcome-fe-m2-lighthouse-loop]"
                  "[partition:graph-decision-provenance]" in l)
    evil = list(lines)
    evil[i_cand] = lines[i_cand].replace(
        "[partition:graph-candidate-and-dispute]",
        "[partition:graph-decision-provenance]", 1)
    evil[i_prov] = lines[i_prov].replace(
        "[partition:graph-decision-provenance]",
        "[partition:graph-candidate-and-dispute]", 1)
    valid, warns = _validate_llm_output(
        compiled, "\n".join(evil), deterministic_text=content,
    )
    assert not valid and any("has swapped partition" in w for w in warns), warns
    # 17. swapped-source：candidate 行与 provenance 行互换 source 锚点
    i_c = next(i for i, l in enumerate(lines)
               if "[member:outcome-native-agent-1-0-launch-2026-08]" in l)
    i_p = next(i for i, l in enumerate(lines)
               if "[member:portfolio-fe-2026-08]" in l)
    src_c = ANCHOR_RE.search(lines[i_c]).group(3)
    src_p = ANCHOR_RE.search(lines[i_p]).group(3)
    assert src_c != src_p  # attack must actually swap distinct sources
    evil = list(lines)
    evil[i_c] = lines[i_c].replace(f"[source:{src_c}]", f"[source:{src_p}]", 1)
    evil[i_p] = lines[i_p].replace(f"[source:{src_p}]", f"[source:{src_c}]", 1)
    valid, warns = _validate_llm_output(
        compiled, "\n".join(evil), deterministic_text=content,
    )
    assert not valid and any("has swapped source" in w for w in warns), warns

    # ── r4 契约：Render Schema v2 ──
    # 18. 三字段 + mode_used 枚举（不引入 llm_polished）
    assert (
        result["render_schema_version"] == "context-render/2.0"
        and result["rendered"]["grounding_status"] == "structurally_validated"
        and result["rendered"]["semantic_preservation"] == "not_proven"
        and result["rendered"]["mode_used"]
        in ("deterministic", "deterministic_fallback",
            "llm_with_fallback", "llm_required")
    )
