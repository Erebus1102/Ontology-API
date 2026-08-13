# src/tkos_runtime/adapters/gram_intent_resolver.py
from __future__ import annotations
import re

from tkos_runtime.domain.models import IntentAssessment, NoMatchError

DISPLAY = "https://ontology.tokenking.ai/tkos#displayName"
SCOPE = "https://ontology.tokenking.ai/tkos#scopeDescription"
OBJECT_ID = "https://ontology.tokenking.ai/tkos#objectId"

# P0 门禁：泛词/品牌词/功能词不独立构成命中。它们只证明"问的是本项目/
# 通用业务"，不能证明知识库覆盖查询主题（"deepresearch 要不要上 bedrock"
# 的 deepresearch/bedrock 才是主题词；"公司现在应该怎么定价"的主题词是
# 定价，不是"公司"）。
STOPWORDS = frozenset({
    # 品牌词：问的是本项目 ≠ 知识库有该主题内容
    "tkos", "tokenking", "agent",
    # 库内最泛的业务词（any-df=30/252 与"产品"42 同类）。
    # 必须列入：否则"公司现在应该怎么定价"唯一命中词就是它
    # （evidence-ceoagent 的 displayName 含"公司现实"），无法识别
    # "知识库没有定价内容"（定价 df=0）。
    "模块", "模型", "研究", "系统", "项目", "产品", "公司",
    # 查询功能词（用户审定清单）：语法词不可能是业务主题词。
    # 要不要 拆为 要不/不要 两个 2-gram；什么（疑问词）与 如何/怎么 同类。
    "现在", "应该", "怎么", "是否", "需要", "可以", "如何",
    "当前", "情况", "要不", "不要", "什么",
})
# 英文完整 token 命中是强信号（+30），使"TokenHub 模块当前进度如何"这类
# 查询的实体词压过字符碎片噪声；中文 2-gram 只作底分、不作加权（加权曾
# 让 gap-product1-mvp-acceptance 反超 capability-tokenhub-runtime-base）。
# 全文命中仍是压倒性优先（100+len）。
ENGLISH_TOKEN_WEIGHT = 30

# 中文功能字：纯语法粒子，永远不可能是业务主题词。含这些字的 gram
# （"论是"来自"结论是"、"价的"来自"定价的"）是已知主题词的跨界碎片，
# 若进入剩余主题集会造成假"未知主题"误拒（评审三审：
# "研究结论是什么"的"论是"全文零出现，但结论/灯塔/交付均为已知知识）。
# 判定放在 gram 级而不是把整字加入 STOPWORDS：避免"是/的"作独立词时的
# 相邻碎片副作用，且只影响含该字的二元组。
FUNCTION_CHARS = frozenset("是的了吗呢")

_ENGLISH_TOKEN = re.compile(r"[a-z][a-z0-9-]*")


def _frag(u): return str(u).rsplit("#", 1)[-1]


class GramIntentResolver:
    def __init__(self, store):
        self._store = store

    def resolve(self, query: str, allowed_graph_ids: list[str]) -> IntentAssessment:
        text, name_text, names = self._index(allowed_graph_ids)
        q = query.lower().strip()
        grams = {q[i:i+2] for i in range(max(0, len(q)-1))}

        # ── P0 门禁：英文完整 token 边界 + hay 侧 token-set 交集 ──────
        # 2-gram 会把 "deepresearch" 的碎片撞到任何含 "research" 的
        # objectId；英文只按完整 token（≥3 字符，非泛词）计强命中。
        # 命中判定按 token-set 交集（"deepresearch" 中的 "research"
        # 子串不构成命中——评审意见：t in hay 子串匹配改为 token-set）。
        # 否决（unmatched_terms）按全文 token-set（术语完全缺席 = 未知
        # 实体）；但强命中与 +30 加权只认 name 字段（displayName/objectId）
        # ——scopeDescription 提到 "TokenHub" 不得构成强命中（评审三审
        # 反例：TokenHub 应该如何定价 → assertion-* 靠 scope 提及穿透）。
        eng_tokens = [t for t in _ENGLISH_TOKEN.findall(q) if len(t) >= 3]
        high_info_eng = [t for t in eng_tokens if t not in STOPWORDS]
        node_tokens = {
            node: {t for t in _ENGLISH_TOKEN.findall(h) if len(t) >= 3}
            for node, h in text.items()
        }
        node_name_tokens = {
            node: {t for t in _ENGLISH_TOKEN.findall(h) if len(t) >= 3}
            for node, h in name_text.items()
        }
        all_tokens: set[str] = set()
        for toks in node_tokens.values():
            all_tokens.update(toks)
        unmatched_terms = [t for t in high_info_eng if t not in all_tokens]

        # ── P0 门禁（评审 B2 反例）：未知关键实体参与否决 ──────────────
        # "TokenHub 要不要上 bedrock 模型"：tokenhub 已知、bedrock 未知。
        # 未知实体本身就是知识缺口 → 立即拒绝，禁止已知实体继续选根
        # （修复前继续选根 → strategy-content-* 编译 500）。
        if unmatched_terms:
            raise NoMatchError(
                f"知识库未覆盖查询主题：{query!r}（未知关键实体 "
                f"{unmatched_terms}）",
                unmatched_terms=unmatched_terms,
                match_reasons=[f"未知关键实体参与否决：{unmatched_terms}"],
            )

        # ── 中文主题词准入（评审 B1 反例 + 三审反例）──────────────────
        # 只认"业务主题词"：功能词/泛词不构成命中；与停用词相邻的碎片
        # gram（"公司现在"→ 司现、"怎么定价"→ 么定）只是字符巧合，不是
        # 主题词。只收纯 CJK 二元组（"品1/0与"这类 ASCII 边界 gram 是
        # 排版噪声）；中文强命中只限 name 字段（displayName/objectId），
        # scopeDescription 只作底分——scope 中单个二元组不能独立放行。
        raw_grams = [q[i:i+2] for i in range(max(0, len(q)-1))]
        cn_grams = [
            g for g in raw_grams
            if all("一" <= c <= "鿿" for c in g)
            and g not in STOPWORDS
            and not any(c in FUNCTION_CHARS for c in g)
        ]
        stopped_positions = {i for i, g in enumerate(raw_grams) if g in STOPWORDS}
        fragment_neighbors: set[str] = set()
        for i in stopped_positions:
            if i > 0:
                fragment_neighbors.add(raw_grams[i - 1])
            if i + 1 < len(raw_grams):
                fragment_neighbors.add(raw_grams[i + 1])
        strong_cn = [g for g in cn_grams if g not in fragment_neighbors]

        scored = []
        for node, hay in text.items():
            if q and q in hay:
                sc = 100 + len(q)  # 全文命中：压倒性优先
            else:
                sc = sum(1 for g in grams if g in hay)
                sc += ENGLISH_TOKEN_WEIGHT * sum(
                    1 for t in high_info_eng
                    if t in node_name_tokens.get(node, ()))
            if sc > 0:
                scored.append((sc, node))
        ranked = sorted(scored, key=lambda x: (-x[0], x[1]))[:5]
        if not ranked:
            raise NoMatchError(
                f"未匹配到对象：{query!r}", unmatched_terms=unmatched_terms)

        # ── P0 门禁（评审三审）：剩余中文主题必须在知识库全文获得覆盖 ──
        # 移除停用词与已匹配实体后，剩余中文主题片段（strong_cn）若在
        # 知识库全文（name + scope）零出现 = 未知主题 → 否决（"TokenHub
        # 应该如何定价"：tokenhub 已知强命中，但"定价"全文 0 处——知识
        # 库不存在任何定价内容）。未覆盖主题计入 unmatched_terms（此前
        # 中文主题从不进入 unmatched_terms，无法否决错误结果）。
        # 注：覆盖判定用全文而非仅 name 字段——"TokenHub 模块当前进度
        # 如何"的"进度"在 displayName/objectId 零覆盖、但作为已知知识
        # 存在于 scopeDescription（保持型回归必须继续命中）；而"定价/
        # 收费/新的"全文 0 处，才是真正的未知主题。
        all_grams: set[str] = set()
        for hay in text.values():
            all_grams.update(hay[i:i+2] for i in range(max(0, len(hay)-1)))
        unknown_cn = [g for g in strong_cn if g not in all_grams]
        if unknown_cn:
            raise NoMatchError(
                f"知识库未覆盖查询主题：{query!r}（剩余中文主题 "
                f"{sorted(set(unknown_cn))} 在知识库全文零出现）",
                unmatched_terms=sorted(set(unknown_cn)),
                match_reasons=[(
                    f"剩余中文主题未在知识库全文获得覆盖："
                    f"{sorted(set(unknown_cn))}"),
                    f"未知关键实体: {unmatched_terms or '（无）'}"],
            )

        # ── P0 门禁：top1 必须至少有一个非泛词强命中 ───────────────────
        # 无强命中 = 得分全部来自字符碎片巧合（"bedrock"→13 分案例）。
        # 知识不足必须显式拒绝（→ 404 knowledge gap），不得强制选最接近。
        # 英文强命中只认 name 字段 token（scope 提及不构成命中——评审
        # 三审：assertion-* 靠 scope 里的 "TokenHub" 拿 +30 穿透门禁）。
        top_node = ranked[0][1]
        top_hay = text[top_node]
        top_name = name_text.get(top_node, "")
        strong_hits = [t for t in high_info_eng
                       if t in node_name_tokens.get(top_node, ())]
        strong_hits += [g for g in strong_cn if g in top_name]
        if not strong_hits:
            reasons = [
                f"top1={_frag(top_node)} 无主题词强命中",
                f"未知关键实体: {unmatched_terms or '（无）'}",
            ]
            raise NoMatchError(
                f"知识库未覆盖查询主题：{query!r}（缺失关键词 "
                f"{unmatched_terms or '（无）'}）",
                unmatched_terms=unmatched_terms, match_reasons=reasons,
            )
        return IntentAssessment(root=top_node,
            alternatives=[(sc, _frag(n), names.get(n, _frag(n))) for sc, n in ranked[1:]])

    def _index(self, graph_ids):
        text, names = {}, {}
        name_text: dict[str, list[str]] = {}
        for s in self._store.statements_in(graph_ids):
            v = str(s.object)
            if s.predicate in (DISPLAY, SCOPE, OBJECT_ID):
                text.setdefault(s.subject, []).append(v)
            if s.predicate in (DISPLAY, OBJECT_ID):
                # 主题词只认 displayName/objectId（schema 暂无 alias 谓词）
                name_text.setdefault(s.subject, []).append(v)
            if s.predicate == DISPLAY:
                names.setdefault(s.subject, v)
        return (
            {n: " ".join(v).lower() for n, v in text.items()},
            {n: " ".join(v).lower() for n, v in name_text.items()},
            names,
        )
