# src/tkos_runtime/adapters/gram_intent_resolver.py
from __future__ import annotations
import re

from tkos_runtime.domain.models import (
    AmbiguousMatchError, IntentAssessment, IntentFacets, NoMatchError,
)
from tkos_runtime.domain.roles import classify_role

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

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

# P1 角色触发词（原文子串匹配，首个命中生效；顺序即优先级——风险
# constrain 排在 prefer 之前，如"灯塔项目有哪些风险"命中的是 constrain）。
# "进展/进度"只 prefer 不 constrain：constrain 会把 capability-tokenhub
# 整个排除，破坏既有契约（"TokenHub 模块当前进度如何"必须保持 root=
# capability-tokenhub-runtime-base）。
ROLE_TRIGGERS = [("风险", "risk", "constrain"),
                 ("进展", "progress", "prefer"),
                 ("进度", "progress", "prefer"),
                 ("议题", "issue", "prefer")]
# prefer 加成：6+B>8 → B≥3、8+B>8 → B≥1，B=5 两边 margin 3；且
# TokenHub 进度 9+5=14 远低于 capability 39（契约 #5 安全，margin 25）。
PREFERENCE_BOOST = 5

# 中文疑问模板：整段移除（模板是语法不是主题）。"进展如何/有哪些/
# 有没有/是不是"整体不属于业务内容——其中"进展/哪些"等词若逐字保留
# 会产出"有哪/些风/线进"式跨界碎片（评审四审误拒案例：产品 1.0
# 上线进展如何 / 灯塔项目有哪些风险 / FE 当前有哪些风险）。
STOP_PHRASES = ("有哪些", "进展如何", "有没有", "是不是")

# 中文功能字/语助字：纯语法粒子，永远不可能是业务主题词。它们按单字
# **切断**连续主题片段（span）——"论是"（"结论是"跨界碎片）、"价的"
# （"定价的"）因此不会形成 span，不会造成假"未知主题"误拒；"要/不"
# （要不要/不要 拆解）、"在/和/与/及/或/等"（介词/连词/语助）同样只
# 作 span 边界，不可能是业务内容。
SPAN_BREAK_CHARS = frozenset("是的了吗呢要不和在与及或等")

_ENGLISH_TOKEN = re.compile(r"[a-z][a-z0-9-]*")


def _frag(u): return str(u).rsplit("#", 1)[-1]


def _cn_spans(query: str) -> list[str]:
    """Extract continuous Chinese topic spans (R4 admission).

    Per maximal CJK run: strip question templates (STOP_PHRASES) wholesale,
    cut 2-char stopwords, skip single break chars — the leftover fragments
    are continuous business-topic spans (length >= 2). Cross-boundary
    artifacts like 线进/有哪 can only exist *inside* a span, where the
    coverage rule (see resolve) tolerates them.
    """
    runs: list[str] = []
    cur: list[str] = []
    for c in query:
        if "一" <= c <= "鿿":
            cur.append(c)
        else:
            if cur:
                runs.append("".join(cur))
                cur = []
    if cur:
        runs.append("".join(cur))
    spans: list[str] = []
    for run in runs:
        for p in STOP_PHRASES:
            run = run.replace(p, "")
        i, start = 0, 0
        buf: list[str] = []
        while i < len(run):
            if run[i:i + 2] in STOPWORDS or run[i] in SPAN_BREAK_CHARS:
                if i > start:
                    buf.append(run[start:i])
                i += 2 if run[i:i + 2] in STOPWORDS else 1
                start = i
            else:
                i += 1
        if start < len(run):
            buf.append(run[start:])
        spans.extend(s for s in buf if len(s) >= 2)
    return spans


class GramIntentResolver:
    def __init__(self, store):
        self._store = store

    def resolve(self, query: str, allowed_graph_ids: list[str]) -> IntentAssessment:
        text, name_text, names, type_index = self._index(allowed_graph_ids)
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

        # ── P1：角色触发词检测（原文子串，首个命中生效）────────────────
        # 顺序即优先级：风险（constrain）排在 prefer 触发词之前——
        # "灯塔项目有哪些风险" 命中的是 constrain；"产品 1.0 上线进展
        # 如何" 命中 prefer（进展只优先、不排除非 ProgressSnapshot）。
        trigger: tuple[str, str, str] | None = None
        for word, role, mode in ROLE_TRIGGERS:
            if word in q:
                trigger = (word, role, mode)
                break

        # ── P1：baseline 候选池（先评分后否决，所有 raise 携带候选）──
        # 候选只来自 _index 遍历的 allowed_graph_ids 语句 → 构造上不
        # 可能含敏感图节点（仍有结构断言测试）。exact_match 标记全文
        # 精确命中（100+len(q)，压倒性优先）；name_evidence =
        # |{grams} ∩ name_text[node]|——名称证据压 scope 噪声（"灯塔
        # 项目有哪些风险" constrain 后 name-evidence 1 vs 0 →
        # resource-conflict，压制 scope 噪声的灯塔风险）。
        baseline: list[dict] = []
        for node, hay in text.items():
            exact = bool(q and q in hay)
            if exact:
                base = 100 + len(q)  # 全文命中：压倒性优先
            else:
                base = sum(1 for g in grams if g in hay)
                base += ENGLISH_TOKEN_WEIGHT * sum(
                    1 for t in high_info_eng
                    if t in node_name_tokens.get(node, ()))
            if base > 0:
                name_ev = sum(1 for g in grams
                              if g in name_text.get(node, ""))
                baseline.append({"node": node, "exact": exact, "base": base,
                                 "name_ev": name_ev, "eff": base})

        def _rank_key(e):
            # 统一排序键（评审收紧 #1）：全文精确命中恒压过名称片段多
            # 的候选；name 证据压 scope 噪声；与 409 歧义判定共用同一
            # 组有效维度（评审收紧 #3）。
            return (-int(e["exact"]), -e["name_ev"], -e["eff"], e["node"])

        def _amb_key(e):
            return (e["exact"], e["name_ev"], e["eff"])

        def _cands(entries):
            return [(e["eff"], _frag(e["node"]),
                     names.get(e["node"], _frag(e["node"])))
                    for e in entries]

        baseline_ranked = sorted(baseline, key=_rank_key)

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
                candidates=_cands(baseline_ranked[:5]),
            )

        # ── 中文主题跨度准入（评审四审，条件不变）──────────────────────
        # 只认"业务主题片段"（span）：疑问模板整段移除、停用词按 2-字
        # 词切断、功能字按单字跳过，剩余为连续中文片段。旧的"任一剩余
        # 2-gram 未在全库出现即否决"把自然语言边界碎片（"上线|进展"→
        # 线进、"哪些|风险"→些风）误判为未知主题，误拒 4 条合法查询。
        # 跨界碎片现在只可能出现在 span 内部，由下方覆盖率规则容忍。
        # 注：覆盖判定用全文而非仅 name 字段——"产品 1.0 当前进度如何"
        # 的"进度"在 displayName/objectId 零覆盖、但作为已知知识存在于
        # scopeDescription（四审误拒案例必须 200）；而"定价/收费"全文
        # 0 处，才是真正的未知主题。
        cn_spans = _cn_spans(q)
        all_grams: set[str] = set()
        for hay in text.values():
            all_grams.update(hay[i:i+2] for i in range(max(0, len(hay)-1)))
        unknown_grams: list[str] = []
        for span in cn_spans:
            sgrams = [span[i:i+2] for i in range(len(span) - 1)]
            uncovered = [g for g in sgrams if g not in all_grams]
            if len(uncovered) * 2 > len(sgrams):
                unknown_grams.extend(uncovered)
        if unknown_grams:
            unknown_grams = sorted(set(unknown_grams))
            raise NoMatchError(
                f"知识库未覆盖查询主题：{query!r}（剩余中文主题 "
                f"{unknown_grams} 未在知识库全文获得覆盖）",
                unmatched_terms=unknown_grams,
                match_reasons=[(
                    f"剩余中文主题未在知识库全文获得覆盖："
                    f"{unknown_grams}"),
                    f"未知关键实体: {unmatched_terms or '（无）'}"],
                candidates=_cands(baseline_ranked[:5]),
            )

        if not baseline_ranked:
            raise NoMatchError(
                f"未匹配到对象：{query!r}", unmatched_terms=unmatched_terms,
                candidates=[])

        # ── P1：角色约束/优先（第二候选池 role_ranked）────────────────
        # 正常 root / 409 / 强命中门 404 建议 → role_ranked；
        # constrain 池空 404 建议 → baseline_ranked[:5]。
        role_ranked = baseline_ranked
        if trigger is not None:
            _w, role, mode = trigger
            if mode == "constrain":
                role_ranked = [e for e in baseline_ranked
                               if classify_role(e["node"], type_index) == role]
                if not role_ranked:
                    raise NoMatchError(
                        f"知识库未覆盖该角色主题：{query!r}（角色约束 "
                        f"{role} 无候选实体）",
                        match_reasons=[f"角色约束 {role} 无候选实体"],
                        candidates=_cands(baseline_ranked[:5]))
            else:  # prefer：给 preferred 角色且 base>0 的节点 +boost
                role_ranked = [
                    {**e, "eff": e["base"] + PREFERENCE_BOOST}
                    if classify_role(e["node"], type_index) == role else e
                    for e in baseline_ranked
                ]
            role_ranked = sorted(role_ranked, key=_rank_key)

        # ── P0 门禁：top1 必须至少有一个非泛词强命中（条件不变）────────
        # 无强命中 = 得分全部来自字符碎片巧合（"bedrock"→13 分案例）。
        # 知识不足必须显式拒绝（→ 404 knowledge gap），不得强制选最接近。
        # 英文强命中只认 name 字段 token（scope 提及不构成命中——评审
        # 三审：assertion-* 靠 scope 里的 "TokenHub" 拿 +30 穿透门禁）。
        # 中文准入已由上方 span 覆盖率完成：span 通过 = 主题在知识库有
        # 覆盖，不再要求 top1 name 字段命中（"进度"只在 scope 出现、
        # name 零覆盖——四审误拒案例）。查询既无英文强命中、也无任何
        # 中文主题 span（如"模型现在应该怎么选择"）→ 碎片巧合 → 拒绝。
        top_node = role_ranked[0]["node"]
        strong_hits = [t for t in high_info_eng
                       if t in node_name_tokens.get(top_node, ())]
        if not strong_hits and not cn_spans:
            reasons = [
                f"top1={_frag(top_node)} 无主题词强命中",
                f"未知关键实体: {unmatched_terms or '（无）'}",
            ]
            raise NoMatchError(
                f"知识库未覆盖查询主题：{query!r}（缺失关键词 "
                f"{unmatched_terms or '（无）'}）",
                unmatched_terms=unmatched_terms, match_reasons=reasons,
                candidates=_cands(role_ranked[:5]),
            )

        # ── P1：歧义规则（409 严格规则，在完整 role_ranked 上判定）───
        # 仅当 top1/top2 的有效维度（exact_match, name_evidence,
        # effective_score）完全并列 → 拒绝猜测（无 IRI 兜底）；候选 =
        # **全部并列节点**（不设上限——当前数据规模可控；alternative_
        # matches 与 404 alternatives 才限制为五项）。单候选不 409。
        if (len(role_ranked) >= 2
                and _amb_key(role_ranked[0]) == _amb_key(role_ranked[1])):
            tied = [e for e in role_ranked
                    if _amb_key(e) == _amb_key(role_ranked[0])]
            raise AmbiguousMatchError(
                f"查询意图存在歧义：{query!r}（多个候选对象在得分与"
                f"名称证据上并列，无法唯一确定）",
                candidates=_cands(tied))

        return IntentAssessment(
            root=top_node,
            alternatives=_cands(role_ranked[1:5]),
            intent_facets=_build_facets(query, top_node, trigger, name_text),
        )

    def _index(self, graph_ids):
        text, names = {}, {}
        name_text: dict[str, list[str]] = {}
        # P1：同一次遍历加收 rdf:type 索引——角色约束（constrain）按
        # classify_role(node, type_index) 过滤（252 主体中 248 有直接
        # rdf:type；其余 4 个 classify "other"，不可进 constrain 池）。
        type_index: dict[str, set[str]] = {}
        for s in self._store.statements_in(graph_ids):
            v = str(s.object)
            if s.predicate in (DISPLAY, SCOPE, OBJECT_ID):
                text.setdefault(s.subject, []).append(v)
            if s.predicate in (DISPLAY, OBJECT_ID):
                # 主题词只认 displayName/objectId（schema 暂无 alias 谓词）
                name_text.setdefault(s.subject, []).append(v)
            if s.predicate == DISPLAY:
                names.setdefault(s.subject, v)
            if s.predicate == RDF_TYPE:
                type_index.setdefault(s.subject, set()).add(v)
        return (
            {n: " ".join(v).lower() for n, v in text.items()},
            {n: " ".join(v).lower() for n, v in name_text.items()},
            names,
            type_index,
        )


def _build_facets(query: str, root: str,
                  trigger: tuple[str, str, str] | None,
                  name_text: dict[str, str]) -> IntentFacets:
    """P1 意图切面（确定性启发式，仅 200 路径；测试精确锚定）。

    段顺序：1 产品 X.Y artifact（恒保留——覆盖"产品"停用词）→ 2 英文
    token → 3 中文 span（减角色触发词、减含数字段）。过滤：CJK 段仅当
    为 root name 子串保留；英文 token 仅当在 root name token 集保留。
    """
    q = query.lower().strip()
    segments: list[str] = list(re.findall(r"产品\s*\d+(?:\.\d+)*", q))
    name = name_text.get(root, "")
    name_tokens = {t for t in _ENGLISH_TOKEN.findall(name) if len(t) >= 2}
    for t in _ENGLISH_TOKEN.findall(q):
        if len(t) >= 2 and t not in STOPWORDS and t in name_tokens:
            segments.append(t)
    trigger_words = {w for w, _, _ in ROLE_TRIGGERS}
    for s in _cn_spans(q):
        if any(c.isdigit() for c in s):
            continue
        for w in trigger_words:
            s = s.replace(w, "")
        s = s.strip()
        if len(s) >= 2 and s in name:
            segments.append(s)
    return IntentFacets(
        entity=" ".join(segments) if segments else None,
        requested_role=trigger[1] if trigger else None,
        operation="list" if "有哪些" in q
        else ("status" if trigger and trigger[1] == "progress" else None),
    )
