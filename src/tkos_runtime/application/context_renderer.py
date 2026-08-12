# src/tkos_runtime/application/context_renderer.py
"""ContextPack -> NL Markdown 渲染器。

确定性编译器（deterministic）是主能力：按分区（Current/Candidate/Gap/Provenance）
生成稳定、可复现的 NL Markdown 文本，每句标注 ``[member:<id>]`` 和
``[source:<graph>]`` 锚点。

LLM 模式（llm_with_fallback / llm_required）是可选语言优化器：
  * deterministic: 模板生成后直接返回。
  * llm_with_fallback: 模板生成后交 LLM 润色；失败或校验不通过则回退确定性版本。
  * llm_required: 同上，但失败时返回错误（不降级）。

无论何种模式，LLM 都不能：
  - 自选或增删事实
  - 改变成员的分区归属（Candidate → Current 等）
  - 新增 Pack 外的实体、数字、时间、因果或建议
  - 修改或删除 [member:<id>] [source:<graph>] 锚点
"""
from __future__ import annotations

import dataclasses
import os
import re
from typing import Any

from tkos_runtime.domain.models import ContextPack, ContextPackMember

RENDERER_VERSION = "context-renderer/p0-v1"

# 关键谓词 → 中文短语映射（确定性编译器使用）
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
    "confirmsEntity": "确认",
    "researchedBy": "调研",
    "sourcedFrom": "来源",
}


def _frag(uri: str) -> str:
    return uri.rsplit("#", 1)[-1] if "#" in uri else uri.rsplit("/", 1)[-1]


def _relational_phrases(member: ContextPackMember) -> list[str]:
    """从 member.statements 提取有语义价值的关系短语。"""
    phrases: list[str] = []
    seen: set[str] = set()
    for stmt in member.statements:
        pred_frag = _frag(stmt.predicate)
        obj_frag = _frag(stmt.object)
        if pred_frag in _PREDICATE_LABELS and stmt.object.startswith("https://"):
            phrase = f"{_PREDICATE_LABELS[pred_frag]}：{obj_frag}"
            if phrase not in seen:
                seen.add(phrase)
                phrases.append(phrase)
    return phrases


def _member_to_sentence(member: ContextPackMember) -> str:
    """将单个 member 编译为一个事实句。"""
    # 主体：display_name（或 scope，或 id fallback）
    label = member.display_name or member.scope or member.id
    parts = [label]

    # 范围补充
    if member.scope and member.scope != label:
        parts.append(f"（{member.scope}）")

    # 关系短语
    phrases = _relational_phrases(member)
    if phrases:
        parts.append("；".join(phrases[:3]))  # 最多 3 条关系

    # 确认状态标签
    status = member.confirmation_status
    if status and status not in ("Confirmed",):
        parts.append(f"[{status}]")

    # 锚点
    main_source = member.source_graphs[0] if member.source_graphs else "unknown"
    parts.append(f"[member:{member.id}][source:{main_source}]")

    return "。".join(filter(None, (parts[0], "，".join(parts[1:])))) + "。"


def _render_section(
    title: str,
    members: list[ContextPackMember],
    empty_message: str,
) -> list[str]:
    """渲染一个分区段落，返回行列表。"""
    lines = [f"## {title}", ""]
    if not members:
        lines.append(empty_message)
        lines.append("")
        return lines
    for m in members:
        lines.append(f"- {_member_to_sentence(m)}")
    lines.append("")
    return lines


def _render_deterministic(pack: ContextPack) -> str:
    """确定性 Markdown 渲染（纯规则，无外部依赖）。"""
    lines: list[str] = []

    # 标题
    query_text = pack.query or "(无查询)"
    lines.append(f"# Context Pack：{query_text}")
    lines.append("")
    lines.append(f"> 查询时间：{pack.as_of}  |  "
                 f"用途：{pack.purpose}  |  "
                 f"数据版本：`{pack.dataset_revision[:12]}…`")
    lines.append("")

    # 当前事实
    lines.extend(_render_section(
        "当前已确认事实", pack.current_facts,
        "当前没有满足准入条件的已确认事实。",
    ))

    # 待确认信息
    lines.extend(_render_section(
        "待确认信息", pack.candidate_context,
        "当前没有待确认的候选信息。",
    ))

    # 信息缺口
    lines.extend(_render_section(
        "信息缺口", pack.context_gaps,
        "当前没有已知信息缺口。",
    ))

    # 决策参考来源
    lines.extend(_render_section(
        "决策参考来源", pack.provenance_context,
        "当前没有决策参考来源记录。",
    ))

    # 推理状态
    lines.append(f"> 推理状态：{pack.reasoning_status}")
    lines.append(f"> 作用域执行：{pack.scope_resolution.enforcement}")
    lines.append("")

    # 尾注：元数据
    lines.append("---")
    lines.append(f"pack_id: `{pack.pack_id}`  |  "
                 f"ontology: {pack.ontology_release_id}  |  "
                 f"renderer: {RENDERER_VERSION}")
    lines.append("")

    return "\n".join(lines)


def _validate_rendered(
    original: str,
    polished: str,
    pack: ContextPack,
) -> tuple[bool, list[str]]:
    """校验 LLM 输出：member ID 完整、分区边界、无外源实体。"""
    warnings: list[str] = []

    # 1. 所有 member ID 仍存在
    member_ids = {m.id for m in (
        pack.current_facts + pack.candidate_context +
        pack.context_gaps + pack.provenance_context
    )}
    mentioned = set(re.findall(r"\[member:([^\]]+)\]", polished))
    missing = member_ids - mentioned
    if missing:
        warnings.append(f"LLM 输出缺失 member ID: {missing}")

    # 2. 没有幻影 member ID
    phantom = mentioned - member_ids
    if phantom:
        warnings.append(f"LLM 输出包含不存在的 member ID: {phantom}")

    # 3. 没有跨区迁移标记（candidate 不能出现在 current 段落）
    # 简单检查：如果 "已确认事实" 段落下出现 [source:graph-candidate-and-dispute]，警告
    current_section = re.search(
        r"当前已确认事实.*?(?=## |\Z)", polished, re.DOTALL
    )
    if current_section:
        cur_text = current_section.group(0)
        if "graph-candidate-and-dispute" in cur_text:
            warnings.append("LLM 输出在已确认事实段落中包含候选图来源")

    # 4. 分区标签保留
    for tag in ("Candidate", "PreliminarilyConfirmed", "Archived"):
        if tag in original and tag not in polished:
            warnings.append(f"LLM 输出丢失确认状态标签: {tag}")

    return len(warnings) == 0, warnings


def _call_llm(
    deterministic_text: str,
    base_url: str,
    api_key: str,
    model: str,
    max_chars: int,
    language: str,
) -> str:
    """调用 LLM 对确定性文本进行语言润色。"""
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError("LLM mode requires openai package. Install: pip install openai")

    system_prompt = (
        "你是一个严格的文本润色器。你的任务是改善以下结构化事实摘要的语言流畅性和连贯性，"
        "但你必须遵守以下不可破坏的规则：\n\n"
        "1. 不得增删任何事实。\n"
        "2. 不得改变任何 [member:...] 和 [source:...] 锚点的内容或位置。\n"
        "3. 不得将 [source:graph-candidate-and-dispute] 标记的内容移至 "
        "'当前已确认事实' 标题下，反之亦然。\n"
        "4. 不得新增任何 Pack 之外的实体、数字、日期、因果关系或建议。\n"
        "5. 不得删除或修改确认状态标签（如 [Candidate]、[PreliminarilyConfirmed]）。\n"
        "6. 只能改善语言流畅性、连接词和句子结构。\n"
        "7. 保持 Markdown 格式。# ## > - ` 等标记保持不变。\n"
        "8. 保留所有空行分隔。"
    )

    user_prompt = (
        f"请润色以下 {language} 文本，只改善语言流畅性，不改变任何事实、锚点或分区归属：\n\n"
        f"{deterministic_text}"
    )

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        stream=False,
    )
    content = response.choices[0].message.content or ""
    # 截断（按完整句子）
    if len(content) > max_chars:
        truncated = content[:max_chars]
        last_period = max(truncated.rfind("。"), truncated.rfind("\n"))
        if last_period > max_chars // 2:
            content = content[:last_period + 1]
        else:
            content = truncated
    return content


def render(
    pack: ContextPack,
    *,
    mode: str = "deterministic",
    format: str = "markdown",
    max_chars: int = 12000,
    language: str = "zh-CN",
    llm_base_url: str | None = None,
    llm_api_key: str | None = None,
    llm_model: str | None = None,
) -> dict[str, Any]:
    """将 ContextPack 渲染为 NL 文本。

    Returns:
        dict 包含 structured（可选）、rendered（格式/内容/mode信息）、
        metadata（pack_id/revision/版本信息）。
    """
    deterministic = _render_deterministic(pack)

    warnings: list[str] = []
    mode_used = mode
    content = deterministic

    if mode in ("llm_with_fallback", "llm_required"):
        base_url = llm_base_url or os.environ.get("LLM_BASE_URL", "")
        api_key = llm_api_key or os.environ.get("LLM_AUTH_TOKEN", "")
        model = llm_model or os.environ.get("LLM_MODEL", "")
        if not base_url or not api_key:
            msg = "LLM mode requires LLM_BASE_URL and LLM_AUTH_TOKEN"
            if mode == "llm_required":
                raise ValueError(msg)
            warnings.append(f"{msg}; using deterministic renderer.")
            mode_used = "deterministic_fallback"
        else:
            try:
                polished = _call_llm(
                    deterministic, base_url, api_key, model,
                    max_chars, language,
                )
                valid, val_warnings = _validate_rendered(
                    deterministic, polished, pack,
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

    # 最终截断检查
    if len(content) > max_chars:
        truncated = content[:max_chars]
        last_period = max(truncated.rfind("。"), truncated.rfind("\n"))
        if last_period > max_chars // 2:
            content = content[:last_period + 1]
        else:
            content = truncated
        warnings.append(f"Output truncated to {len(content)} chars (max_chars={max_chars}).")

    result: dict[str, Any] = {
        "rendered": {
            "format": format,
            "content": content,
            "mode_requested": mode,
            "mode_used": mode_used,
            "grounding_status": "validated" if not warnings else "validated_with_warnings",
            "warnings": warnings,
        },
        "metadata": {
            "context_pack_id": pack.pack_id,
            "dataset_revision": pack.dataset_revision,
            "ontology_release_id": pack.ontology_release_id,
            "renderer_version": RENDERER_VERSION,
        },
    }
    return result
