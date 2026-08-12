# src/tkos_runtime/application/context_renderer.py
"""ContextPack -> NL Markdown 渲染器。

核心设计：
  * 每个 member 先编译为一个不可变的 ``RenderedFactUnit``（canonical_claim），
    后者在整个渲染链路中不能被修改。
  * deterministic 模式：直接按分区组装事实单元。
  * LLM 模式：对整体 Markdown 文本润色，然后逐单元校验——member ID、分区、source、
    数字/URI 不变——任一失败则降级。
  * 字符预算：在编译阶段按事实单元选择，超预算单元进入 render_omissions，
    不对最终字符串做字符级截断。
  * Gap 去重：candidate_context 中排除已在 context_gaps 中的 member。
"""
from __future__ import annotations

import dataclasses
import os
import re
from typing import Any, Optional

from tkos_runtime.domain.models import ContextPack, ContextPackMember
from tkos_runtime.domain.ports import TextPolisher

RENDERER_VERSION = "context-renderer/p0-v1"

# ── predicate → Chinese label mapping ──────────────────────────────────────
_PREDICATE_LABELS: dict[str, str] = {
    "hasOutcome": "成果",
    "hasScope": "范围",
    "hasResponsibleAssignment": "负责人",
    "hasRisk": "风险",
    "hasCriterion": "成功标准",
    "hasMilestone": "里程碑",
    "hasProgressSnapshot": "当前进度",
    "dependsOn": "依赖",
    "hasContextGap": "已知缺口",
    "informedBy": "基于",
    "supportedByEvidence": "支持证据",
    "hasRationale": "理由",
    "hasPortfolio": "所属组合",
    "hasKeyPath": "关键路径",
    "contributesTo": "贡献于",
    "belongsTo": "属于",
    "delivers": "交付",
    "supports": "支持",
    "expects": "期望",
    "confirmedBy": "由...确认",
    "challengesClaim": "挑战",
    "challengingEvidence": "挑战性证据",
    "isReviewedBy": "审核",
    "isDeliveredBy": "由...交付",
    "hasSuccessCriterion": "成功标准",
    "contains": "包含",
    "confirmsEntity": "确认实体",
    "researchedBy": "调研",
    "sourcedFrom": "来源",
}


def _frag(uri: str) -> str:
    return uri.rsplit("#", 1)[-1] if "#" in uri else uri.rsplit("/", 1)[-1]


# ── RenderedFactUnit ────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class RenderedFactUnit:
    """不可变事实单元。LLM 不得修改 canonical_claim；只能返回润色版文本。"""
    member_id: str
    partition: str
    source_graphs: tuple[str, ...]   # sorted tuple for hashability
    canonical_claim: str             # deterministic compiler output, immutable
    display_name: str = ""
    confirmation_status: Optional[str] = None

    def to_markdown_line(self) -> str:
        """生成最终 Markdown 行（含锚点）。"""
        main_source = self.source_graphs[0] if self.source_graphs else "unknown"
        return f"- {self.canonical_claim} [member:{self.member_id}][source:{main_source}]"


# ── unit compiler ───────────────────────────────────────────────────────────

def _relational_phrases(member: ContextPackMember) -> list[str]:
    phrases: list[str] = []
    seen: set[str] = set()
    for stmt in member.statements:
        pf = _frag(stmt.predicate)
        of = _frag(stmt.object)
        if pf in _PREDICATE_LABELS and stmt.object.startswith("https://"):
            phrase = f"{_PREDICATE_LABELS[pf]}：{of}"
            if phrase not in seen:
                seen.add(phrase)
                phrases.append(phrase)
    return phrases


def _compile_unit(member: ContextPackMember) -> RenderedFactUnit:
    """将一个 ContextPackMember 编译为不可变事实单元。"""
    label = member.display_name or member.scope or member.id
    parts = [label]

    if member.scope and member.scope != label:
        parts.append(f"（{member.scope}）")

    phrases = _relational_phrases(member)
    if phrases:
        parts.append("；".join(phrases[:3]))

    status = member.confirmation_status
    if status and status not in ("Confirmed",):
        parts.append(f"[{status}]")

    # assemble canonical_claim (no anchors — anchors added at assembly time)
    claim = ""
    if len(parts) == 1:
        claim = parts[0]
    else:
        claim = f"{parts[0]}，{'，'.join(parts[1:])}"

    return RenderedFactUnit(
        member_id=member.id,
        partition=member.partition,
        source_graphs=tuple(sorted(member.source_graphs)),
        canonical_claim=claim,
        display_name=member.display_name,
        confirmation_status=member.confirmation_status,
    )


# ── unit-level validator (for LLM output) ───────────────────────────────────

def _extract_unit_ids(text: str) -> set[str]:
    return set(re.findall(r"\[member:([^\]]+)\]", text))


def _extract_sources(text: str) -> set[str]:
    return set(re.findall(r"\[source:([^\]]+)\]", text))


def _extract_numbers(text: str) -> set[str]:
    """Extract numeric tokens (integers, floats, percentages)."""
    return set(re.findall(r"\d+(?:\.\d+)?%?", text))


def _extract_uris(text: str) -> set[str]:
    return set(re.findall(r"https?://[^\s\]\[]+", text))


def _validate_llm_output(
    original_units: list[RenderedFactUnit],
    polished: str,
    deterministic_text: str = "",
) -> tuple[bool, list[str]]:
    """强校验：member ID 一一对应、分区不变、source 不变、无数值/URI 注入。

    Numbers and URIs are validated against the full *deterministic* text
    (metadata headers/footers included), not just the canonical claims,
    so that dates, ontology versions, dataset revisions, and member URLs
    already present in the deterministic output do not trigger false
    positives.
    """
    warnings: list[str] = []

    # build lookup
    orig_by_id: dict[str, RenderedFactUnit] = {
        u.member_id: u for u in original_units
    }

    # 1. member IDs exact match
    orig_ids = set(orig_by_id.keys())
    polished_ids = _extract_unit_ids(polished)
    missing = orig_ids - polished_ids
    phantom = polished_ids - orig_ids
    if missing:
        warnings.append(f"missing member IDs: {missing}")
    if phantom:
        warnings.append(f"phantom member IDs: {phantom}")

    # 2. sources must be subset of originals (no forged sources)
    orig_sources: set[str] = set()
    for u in original_units:
        orig_sources.update(u.source_graphs)
    polished_sources = _extract_sources(polished)
    forged_sources = polished_sources - orig_sources
    if forged_sources:
        warnings.append(f"forged source anchors: {forged_sources}")

    # 3. partition boundary check — candidate source must not appear
    #    under current-facts heading
    current_section = re.search(
        r"当前已确认事实.*?(?=## |\Z)", polished, re.DOTALL
    )
    if current_section:
        cur_text = current_section.group(0)
        if "graph-candidate-and-dispute" in cur_text:
            warnings.append(
                "candidate graph source appeared in 当前已确认事实 section"
            )

    # 4. no new numbers — baseline is the FULL deterministic text
    #    (includes metadata: dates, ontology versions, dataset revisions)
    baseline_numbers: set[str] = set()
    if deterministic_text:
        baseline_numbers.update(_extract_numbers(deterministic_text))
    for u in original_units:
        baseline_numbers.update(_extract_numbers(u.canonical_claim))
    polished_numbers = _extract_numbers(polished)
    new_numbers = polished_numbers - baseline_numbers
    if new_numbers:
        warnings.append(f"new numbers injected: {new_numbers}")

    # 5. no new URIs — baseline is the FULL deterministic text
    #    (includes ontology namespace, member URLs, source URIs)
    baseline_uris: set[str] = set()
    if deterministic_text:
        baseline_uris.update(_extract_uris(deterministic_text))
    for u in original_units:
        baseline_uris.add(u.member_id)
    baseline_uris.update(orig_sources)
    polished_uris = _extract_uris(polished)
    new_uris = polished_uris - baseline_uris
    if new_uris:
        warnings.append(f"new URIs injected: {new_uris}")

    # 6. status tags preserved
    for u in original_units:
        if u.confirmation_status and u.confirmation_status not in ("Confirmed",):
            tag = f"[{u.confirmation_status}]"
            if tag in u.canonical_claim and tag not in polished:
                warnings.append(f"status tag lost: {tag} (member {u.member_id})")

    return len(warnings) == 0, warnings


# ── assembly ────────────────────────────────────────────────────────────────

def _assemble_markdown(
    units: list[RenderedFactUnit],
    pack: ContextPack,
    omissions: list[dict[str, str]],
) -> str:
    """将事实单元按分区组装为 Markdown。"""
    gap_ids = {g.id for g in pack.context_gaps}
    current = [u for u in units if u.partition == "graph-confirmed-enterprise"]
    # Gap members are excluded from candidate section — they appear only under 信息缺口
    candidate = [
        u for u in units
        if u.partition == "graph-candidate-and-dispute" and u.member_id not in gap_ids
    ]
    provenance = [u for u in units if u.partition == "graph-decision-provenance"]
    derived = [u for u in units if u.partition == "graph-derived-context"]

    lines: list[str] = []
    query_text = pack.query or "(无查询)"
    lines.append(f"# Context Pack：{query_text}")
    lines.append("")
    lines.append(
        f"> 查询时间：{pack.as_of}  |  "
        f"用途：{pack.purpose}  |  "
        f"数据版本：`{pack.dataset_revision[:12]}…`"
    )
    lines.append("")

    def _section(title: str, section_units: list[RenderedFactUnit], empty_msg: str):
        lines.append(f"## {title}")
        lines.append("")
        if not section_units:
            lines.append(empty_msg)
        else:
            for u in section_units:
                lines.append(u.to_markdown_line())
        lines.append("")

    _section("当前已确认事实", current, "当前没有满足准入条件的已确认事实。")
    _section("待确认信息", candidate, "当前没有待确认的候选信息。")
    _section("信息缺口",
             [u for u in units if u.member_id in {
                 g.id for g in pack.context_gaps
             }],
             "当前没有已知信息缺口。")
    _section("决策参考来源", provenance, "当前没有决策参考来源记录。")

    lines.append(f"> 推理状态：{pack.reasoning_status}")
    lines.append(f"> 作用域执行：{pack.scope_resolution.enforcement}")
    if omissions:
        lines.append("")
        lines.append("### 被省略的成员")
        for o in omissions:
            lines.append(f"- `{o['member_id']}` — {o['reason']}")
    lines.append("")
    lines.append("---")
    lines.append(
        f"pack_id: `{pack.pack_id}`  |  "
        f"ontology: {pack.ontology_release_id}  |  "
        f"renderer: {RENDERER_VERSION}"
    )
    lines.append("")
    return "\n".join(lines)


def _select_units(
    units: list[RenderedFactUnit],
    pack: ContextPack,
    max_chars: int,
) -> tuple[list[RenderedFactUnit], list[dict[str, str]]]:
    """按事实单元预算选择：头部 + 完整事实单元 + 尾部。

    超预算单元进入 omissions，不做字符级截断。
    """
    # Fixed overhead (headers, footers — approximate)
    overhead = 300
    budget = max_chars - overhead

    # Order: current → candidate (minus gaps) → provenance → gaps
    gap_ids = {g.id for g in pack.context_gaps}
    ordered: list[RenderedFactUnit] = []
    for u in units:
        if u.partition == "graph-confirmed-enterprise":
            ordered.append(u)
    for u in units:
        if u.partition == "graph-candidate-and-dispute" and u.member_id not in gap_ids:
            ordered.append(u)
    for u in units:
        if u.partition == "graph-decision-provenance":
            ordered.append(u)
    for u in units:
        if u.partition == "graph-candidate-and-dispute" and u.member_id in gap_ids:
            ordered.append(u)

    included: list[RenderedFactUnit] = []
    omissions: list[dict[str, str]] = []
    used = 0
    for u in ordered:
        line = u.to_markdown_line()
        if used + len(line) + 1 <= budget:
            included.append(u)
            used += len(line) + 1
        else:
            omissions.append({
                "member_id": u.member_id,
                "reason": "max_chars_exceeded",
            })

    return included, omissions


# ── main render entry point ─────────────────────────────────────────────────

def _render_deterministic(pack: ContextPack) -> str:
    """确定性渲染（用于内部和测试）。"""
    units = _compile_all_units(pack)
    return _assemble_markdown(units, pack, [])


def _compile_all_units(pack: ContextPack) -> list[RenderedFactUnit]:
    """编译 Pack 中所有 member 为事实单元。"""
    gap_ids = {g.id for g in pack.context_gaps}
    units: list[RenderedFactUnit] = []
    for m in pack.current_facts:
        units.append(_compile_unit(m))
    for m in pack.candidate_context:
        if m.id not in gap_ids:
            units.append(_compile_unit(m))
    for m in pack.provenance_context:
        units.append(_compile_unit(m))
    for m in pack.context_gaps:
        units.append(_compile_unit(m))
    return units


def _polish_via_llm(deterministic_text: str, polisher: TextPolisher) -> str:
    """通过 TextPolisher 端口润色（不直接依赖 OpenAI）。"""
    return polisher.polish(deterministic_text, "zh-CN")


def render(
    pack: ContextPack,
    *,
    mode: str = "deterministic",
    format: str = "markdown",
    max_chars: int = 12000,
    language: str = "zh-CN",
    polisher: TextPolisher | None = None,
    pack_origin: str = "server_resolved",
) -> dict[str, Any]:
    """将 ContextPack 渲染为 NL Markdown。

    Args:
        pack: 已解析的 ContextPack。
        mode: deterministic | llm_with_fallback | llm_required。
        max_chars: 输出字符上限（按事实单元选择，非字符截断）。
        polisher: TextPolisher 实例（LLM 模式需要）。
        pack_origin: server_resolved → grounding=validated；
                     client_supplied → grounding=unverified_input。
    """
    # ── compile once ──────────────────────────────────────────────────
    all_units = _compile_all_units(pack)

    # ── budget selection (fact-unit budget, never char-level truncation) ──
    included_units, budget_omissions = _select_units(all_units, pack, max_chars)

    # ── assemble deterministic content ─────────────────────────────────
    warnings: list[str] = []
    if budget_omissions:
        warnings.append(
            f"{len(budget_omissions)} member(s) omitted due to max_chars={max_chars}"
        )
    content = _assemble_markdown(included_units, pack, budget_omissions)

    # ── grounding: trust level depends on origin ───────────────────────
    grounding = "validated" if pack_origin == "server_resolved" else "unverified_input"
    mode_used = mode

    # ── LLM polish (optional) ──────────────────────────────────────────
    if mode in ("llm_with_fallback", "llm_required"):
        if polisher is None:
            msg = "LLM mode requires a TextPolisher instance."
            if mode == "llm_required":
                raise ValueError(msg)
            warnings.append(f"{msg}; using deterministic renderer.")
            mode_used = "deterministic_fallback"
            grounding = "unverified_input"
        else:
            try:
                polished = _polish_via_llm(content, polisher)
                valid, val_warnings = _validate_llm_output(
                    included_units, polished, deterministic_text=content
                )
                warnings.extend(val_warnings)
                if valid:
                    content = polished
                elif mode == "llm_required":
                    raise ValueError(
                        f"LLM output validation failed: {'; '.join(val_warnings)}"
                    )
                else:
                    warnings.append(
                        "LLM output failed validation; using deterministic renderer."
                    )
                    mode_used = "deterministic_fallback"
                    grounding = "unverified_input"
            except Exception as exc:
                if mode == "llm_required":
                    raise
                warnings.append(
                    f"LLM unavailable ({exc}); using deterministic renderer."
                )
                mode_used = "deterministic_fallback"
                grounding = "unverified_input"

    return {
        "rendered": {
            "format": format,
            "content": content,
            "mode_requested": mode,
            "mode_used": mode_used,
            "grounding_status": grounding,
            "warnings": warnings,
        },
        "metadata": {
            "context_pack_id": pack.pack_id,
            "dataset_revision": pack.dataset_revision,
            "ontology_release_id": pack.ontology_release_id,
            "renderer_version": RENDERER_VERSION,
            "pack_origin": pack_origin,
        },
    }
