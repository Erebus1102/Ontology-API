# src/tkos_runtime/application/context_renderer.py
"""ContextPack -> NL Markdown 渲染器。

核心设计：
  * DecisionContextCompiler 将 ContextPack 编译为 sectioned RenderedFactUnit 集合，
    然后按 section 组装为 Markdown。
  * deterministic 模式：直接按 section 组装。
  * LLM 模式：对整体 Markdown 文本润色，然后 section-aware 逐 view_key 校验。
  * 字符预算：在编译阶段按 slot 分配，超预算单元进入 render_omissions。
  * grounding_status: structurally_validated (never validated/unverified_input).
  * semantic_preservation: always not_proven.
"""
from __future__ import annotations

import dataclasses
import os
import re
from typing import Any, Optional

from tkos_runtime.domain.models import ContextPack, ContextPackMember
from tkos_runtime.domain.ports import TextPolisher
from tkos_runtime.domain.render_units import (
    RenderedFactUnit, RenderBudgetTooSmall, DECISION_INCIDENT_PREDICATES,
    SECTION_ORDER, SECTION_TITLES, ROLE_TO_SECTION, RENDERER_VERSION,
    RENDER_SCHEMA_VERSION,
)
from tkos_runtime.application.decision_context_compiler import DecisionContextCompiler

__all__ = [
    "RenderedFactUnit", "RenderBudgetTooSmall", "DECISION_INCIDENT_PREDICATES",
    "SECTION_ORDER", "SECTION_TITLES", "ROLE_TO_SECTION", "RENDERER_VERSION",
    "render",
]

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
# RenderedFactUnit is imported from tkos_runtime.domain.render_units (re-exported
# there to avoid import cycles). The grounding principle is unchanged; the
# structure is extended with ``expected_section`` and ``view_key`` (ER2).


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
    """Extract http(s) URIs, stopping at ASCII and CJK punctuation.

    Without the CJK exclusions, a URL immediately followed by Chinese
    punctuation (e.g. ``https://x.example/；首批场景……``) gets greedily
    captured together. When the LLM later trims surrounding brackets, the
    two "URI strings" diverge and trigger a false positive.
    """
    # Exclude ASCII whitespace/brackets/quotes AND common CJK punctuation.
    return set(re.findall(
        r"""https?://[^\s\]\[<>"'，。；！？、（）【】《》“”‘’]+""",
        text,
    ))


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


# ── section-aware Markdown assembly (DCC v1) ─────────────────────────────────

def _assemble_sectioned_markdown(compiled, pack: ContextPack) -> str:
    """Render compiled sections as decision-oriented Markdown."""
    lines: list[str] = []
    query_text = pack.query or "(无查询)"
    lines.append(f"# 决策上下文：{query_text}")
    lines.append("")

    # Epistemic summary
    lines.append(f"> {compiled.decision_context.get('epistemic_summary', '')}")
    lines.append("")

    for section in SECTION_ORDER:
        title = SECTION_TITLES.get(section, f"## {section}")
        lines.append(title)
        lines.append("")
        units = compiled.units_by_section.get(section, [])
        if not units:
            lines.append("（无）")
        else:
            for u in units:
                short = (section == "gaps")
                lines.append(u.to_markdown_line(short=short))
        lines.append("")

    # Omission summary
    if compiled.omissions:
        lines.append("### 被省略的条目")
        for o in compiled.omissions:
            lines.append(f"- `{o.member_id}` ({o.role}) — {o.reason}")
        lines.append("")

    lines.append("---")
    lines.append(
        f"pack_id: `{pack.pack_id}`  |  "
        f"ontology: {pack.ontology_release_id}  |  "
        f"renderer: {RENDERER_VERSION}"
    )
    lines.append("")
    return "\n".join(lines)


# ── section-aware validator helpers ───────────────────────────────────────────

def _split_sections(polished: str) -> dict[str, str]:
    """Split polished Markdown into {section: body_text} by SECTION_TITLES headers."""
    sections: dict[str, str] = {}
    # Build a regex that matches any section title
    titles = [(sec, title) for sec, title in SECTION_TITLES.items()]
    pattern = "|".join(re.escape(t) for _, t in titles)
    parts = re.split(f"({pattern})", polished, flags=re.MULTILINE)
    # parts: [before_first_title, title1, body1, title2, body2, ...]
    i = 1
    while i < len(parts) - 1:
        title_text = parts[i]
        body = parts[i + 1] if i + 1 < len(parts) else ""
        for sec, t in titles:
            if title_text == t:
                sections[sec] = body
                break
        i += 2
    return sections


def _validate_llm_output_sections(
    compiled, polished: str, deterministic_text: str = "",
) -> tuple[bool, list[str]]:
    """Section-aware LLM output validation keyed by view_key.

    Eight checks:
      1. exact once per view_key
      2. in expected section
      3. partition anchor preserved
      4. status tags preserved
      5. section set + order unchanged
      6/7. phantom/missing (via occurrences)
      8. numbers/URIs unchanged from baseline
    """
    warnings: list[str] = []

    # Build view_key → unit lookup from compiled (sectioned)
    selected: dict[tuple[str, str], RenderedFactUnit] = {}
    for sec_units in compiled.units_by_section.values():
        for u in sec_units:
            selected[u.view_key] = u

    sections = _split_sections(polished)

    # 5. section set + order unchanged
    expected_sections = [s for s in SECTION_ORDER
                         if s in compiled.units_by_section and compiled.units_by_section[s]]
    actual_sections = list(sections.keys())
    if actual_sections != expected_sections:
        warnings.append(f"section set/order changed: {actual_sections} vs {expected_sections}")

    for vk, unit in selected.items():
        anchor_member = f"[member:{unit.member_id}]"
        anchor_partition = f"[partition:{unit.partition}]"

        # 1. exact once per view_key
        occurrences = sum(1 for b in sections.values()
                         if anchor_member in b and anchor_partition in b)
        if occurrences != 1:
            warnings.append(f"view_key {vk} appears {occurrences} times (expected 1)")

        # 2. in expected section
        found_section = next((s for s, b in sections.items()
                             if anchor_member in b), None)
        if found_section and found_section != unit.expected_section:
            warnings.append(
                f"view_key {vk} in section {found_section}, expected {unit.expected_section}"
            )

        # 3. partition anchor preserved
        if found_section and anchor_partition not in sections.get(found_section, ""):
            warnings.append(f"partition anchor changed for {vk}")

    # 4. status tags preserved
    for unit in selected.values():
        if unit.confirmation_status and unit.confirmation_status not in ("Confirmed",):
            tag = f"[{unit.confirmation_status}]"
            if tag in unit.canonical_claim and tag not in polished:
                warnings.append(f"status tag lost: {tag} (member {unit.member_id})")

    # 8. numbers/URIs unchanged from baseline (reuse existing extractors against
    #    the full deterministic text as baseline)
    baseline_numbers: set[str] = set()
    if deterministic_text:
        baseline_numbers.update(_extract_numbers(deterministic_text))
    for unit in selected.values():
        baseline_numbers.update(_extract_numbers(unit.canonical_claim))
    polished_numbers = _extract_numbers(polished)
    new_numbers = polished_numbers - baseline_numbers
    if new_numbers:
        warnings.append(f"new numbers injected: {new_numbers}")

    # URIs
    baseline_uris: set[str] = set()
    if deterministic_text:
        baseline_uris.update(_extract_uris(deterministic_text))
    orig_sources: set[str] = set()
    for unit in selected.values():
        baseline_uris.add(unit.member_id)
        orig_sources.update(unit.source_graphs)
    baseline_uris.update(orig_sources)
    polished_uris = _extract_uris(polished)
    new_uris = polished_uris - baseline_uris
    if new_uris:
        warnings.append(f"new URIs injected: {new_uris}")

    # Forged source check
    polished_sources = _extract_sources(polished)
    forged_sources = polished_sources - orig_sources
    if forged_sources:
        warnings.append(f"forged source anchors: {forged_sources}")

    return len(warnings) == 0, warnings


# ── backward-compat wrapper ───────────────────────────────────────────────────
# Existing tests call _validate_llm_output with a flat list of RenderedFactUnit.
# We keep the original function but delegate to section-aware when passed a
# CompiledDecisionContext-like object.


def _validate_llm_output(
    original_units, polished: str, deterministic_text: str = "",
) -> tuple[bool, list[str]]:
    """Validate LLM output — accepts both flat list (legacy) and CompiledDecisionContext."""
    # If it looks like a CompiledDecisionContext (has .units_by_section), use v2
    if hasattr(original_units, "units_by_section"):
        return _validate_llm_output_sections(
            original_units, polished, deterministic_text,
        )

    # ── Legacy flat-list path (unchanged) ──────────────────────────────────
    from tkos_runtime.application.decision_context_compiler import CompiledDecisionContext
    if isinstance(original_units, CompiledDecisionContext):
        return _validate_llm_output_sections(
            original_units, polished, deterministic_text,
        )

    warnings: list[str] = []
    units = original_units  # list[RenderedFactUnit]

    orig_by_id: dict[str, RenderedFactUnit] = {
        u.member_id: u for u in units
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

    # 2. sources must be subset of originals
    orig_sources: set[str] = set()
    for u in units:
        orig_sources.update(u.source_graphs)
    polished_sources = _extract_sources(polished)
    forged_sources = polished_sources - orig_sources
    if forged_sources:
        warnings.append(f"forged source anchors: {forged_sources}")

    # 3. partition boundary check
    current_section = re.search(
        r"当前已确认事实.*?(?=## |\Z)", polished, re.DOTALL
    )
    if current_section:
        cur_text = current_section.group(0)
        if "graph-candidate-and-dispute" in cur_text:
            warnings.append(
                "candidate graph source appeared in 当前已确认事实 section"
            )

    # 4. no new numbers
    baseline_numbers: set[str] = set()
    if deterministic_text:
        baseline_numbers.update(_extract_numbers(deterministic_text))
    for u in units:
        baseline_numbers.update(_extract_numbers(u.canonical_claim))
    polished_numbers = _extract_numbers(polished)
    new_numbers = polished_numbers - baseline_numbers
    if new_numbers:
        warnings.append(f"new numbers injected: {new_numbers}")

    # 5. no new URIs
    baseline_uris: set[str] = set()
    if deterministic_text:
        baseline_uris.update(_extract_uris(deterministic_text))
    for u in units:
        baseline_uris.add(u.member_id)
    baseline_uris.update(orig_sources)
    polished_uris = _extract_uris(polished)
    new_uris = polished_uris - baseline_uris
    if new_uris:
        warnings.append(f"new URIs injected: {new_uris}")

    # 6. status tags preserved
    for u in units:
        if u.confirmation_status and u.confirmation_status not in ("Confirmed",):
            tag = f"[{u.confirmation_status}]"
            if tag in u.canonical_claim and tag not in polished:
                warnings.append(f"status tag lost: {tag} (member {u.member_id})")

    return len(warnings) == 0, warnings


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
    """将 ContextPack 渲染为 NL Markdown（DCC v1 sectioned output + Render Schema v2）。

    Args:
        pack: 已解析的 ContextPack。
        mode: deterministic | llm_with_fallback | llm_required。
        max_chars: 输出字符上限。
        polisher: TextPolisher 实例（LLM 模式需要）。
        pack_origin: 记录在 metadata 中，但不影响 grounding_status（v2 固定为 structurally_validated）。
    """
    # ── Decision Context Compiler ───────────────────────────────────────
    compiler = DecisionContextCompiler()
    try:
        compiled = compiler.compile(pack, max_chars=max_chars)
    except RenderBudgetTooSmall:
        raise  # let caller (server) map to 422

    # ── Assemble deterministic content ──────────────────────────────────
    warnings: list[str] = list(compiled.warnings)
    if compiled.omissions:
        warnings.append(
            f"{len(compiled.omissions)} member(s) omitted due to max_chars={max_chars}"
        )
    content = _assemble_sectioned_markdown(compiled, pack)

    # ── Render Schema v2: grounding is always structurally_validated ────
    # NOTE: structural validation cannot detect in-line NL business judgements
    # (e.g. "该风险已可忽略") — semantic_preservation stays not_proven.
    grounding = "structurally_validated"
    mode_used = mode

    # ── LLM polish (optional) ───────────────────────────────────────────
    if mode in ("llm_with_fallback", "llm_required"):
        if polisher is None:
            msg = "LLM mode requires a TextPolisher instance."
            if mode == "llm_required":
                raise ValueError(msg)
            warnings.append(f"{msg}; using deterministic renderer.")
            mode_used = "deterministic_fallback"
        else:
            try:
                polished = _polish_via_llm(content, polisher)
                valid, val_warnings = _validate_llm_output(
                    compiled, polished, deterministic_text=content,
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
            except Exception as exc:
                if mode == "llm_required":
                    raise
                warnings.append(
                    f"LLM unavailable ({exc}); using deterministic renderer."
                )
                mode_used = "deterministic_fallback"

    return {
        "render_schema_version": RENDER_SCHEMA_VERSION,
        "rendered": {
            "format": format,
            "content": content,
            "grounding_status": grounding,
            "semantic_preservation": "not_proven",
            "rendering_status": "completed",
            "mode_requested": mode,
            "mode_used": mode_used,
            "warnings": warnings,
        },
        "decision_context": compiled.decision_context,
        "metadata": {
            "context_pack_id": pack.pack_id,
            "dataset_revision": pack.dataset_revision,
            "ontology_release_id": pack.ontology_release_id,
            "renderer_version": RENDERER_VERSION,
            "pack_origin": pack_origin,
        },
    }
