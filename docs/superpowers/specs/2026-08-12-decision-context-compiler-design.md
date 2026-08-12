# Decision Context Compiler v1 — Design Spec

> **Grounding boundary (decided):** 确定性编译器**只产出 (A) 类结构化叙事**——议题、目标、进展、依赖、风险、缺口、证据的重排与人类可读化。**不产出 (B) 类条件性判断**（"尚不足以承诺""最可能失败在哪里""应采用并行/主次"）。判断留给消费方（Agent / 人）。这条边界是 v1 不可逾越的 scope 红线。

## 1. 背景与问题

当前渲染链路（`context_renderer.py`）解决了来源与认知状态的可追溯性，但存在六项已确认缺陷：

1. 二层 BFS 返回"相关但不重要"——73 条 Candidate、8 条 Gap、15 条 Provenance 同等粒度输出。
2. 输出是对象清单，缺少经营叙事。
3. 本体 ID（`dependency-product1-lighthouse-synchronous-delivery`）进入阅读正文。
4. 字符预算按遍历顺序消耗——Assignment/Confirmation 占满预算，Gap 全部被省略，正文却显示"没有信息缺口"。
5. Current/Candidate/Gap 只表达认知状态，不表达决策作用（同一条 Candidate 可能是进度/风险/方案）。
6. LLM 只能做标点润色，无法重排或聚合。

## 2. 目标

在现有 Structured ContextPack 与 rendered Markdown 之间，增加一层 **Decision Context Compiler**，产出面向一次议题的阅读视图：

```
Ontology Query → Structured ContextPack → Decision Context Compiler → {decision_context, rendered.content} → (可选 LLM 表达优化) → Agent
```

- Structured ContextPack 仍是权威、完整、机器可追溯的查询结果，不动。
- decision_context 是针对一次议题的结构化阅读视图，与 rendered.content 并行输出。
- rendered.content 由 decision_context 编译而来（不再按 member 平铺）。
- LLM 只对已编译好的 (A) 类叙事做表达优化，校验链路不变。

**v1 验收目标**：将当前 73 条 Candidate、8 条 Gap、15 条 Provenance，编译成 ≤4000 字、按决策作用分 6–8 节、每段保留 member 锚点的一号位决策上下文，且 Gap 必进、omission 退出正文。

## 3. 不在 v1 范围内（显式排除）

- **(B) 类条件判断** —— 编译器不产出，不标记 inferred，不留 hook。这是 grounding 红线。
- **DecisionClaimBundle 多 member 段落聚合** —— v1 每段仍按 member 粒度切句（一句一锚点），只做主题分组。聚合留待 v1 之后用真实样本评估是否需要。
- **连续 relevance score（+30/+25 权重）** —— v1 用分层硬规则（必进 / 可进 / 仅锚点），不用数值评分。评分需真实样本定标，放 v2。
- **LLM 综合判断** —— LLM 仍只做表达优化，不做事实综合。
- **业务质量评测套件** —— v1 不建。

## 4. Role 分类规则

每个 member 的决策作用由其 `rdf:type`（在 `statements` 中，predicate = `http://www.w3.org/1999/02/22-rdf-syntax-ns#type`）决定。分类函数：`classify_role(member) -> Role`。

一个 member 可能有多个 type；按**决策重要性优先**取第一个命中（顺序：required > secondary > trace_only）。无命中 → `other`。

### 4.1 Role 映射表（grounded in `ontology/schema/tkos-ontology.ttl`）

| Role（决策作用） | 层级 | 本体 class |
|---|---|---|
| `issue` | required | `StrategicIssue` |
| `outcome` | required | `Outcome`, `CompanyOutcome`, `DomainOutcome`, `MissionOutcome`, `OutcomeContribution` |
| `progress` | required | `ProgressSnapshot`, `DomainProgressSnapshot`, `OutcomeProgressSnapshot`, `PerformanceFact` |
| `risk` | required | `Risk`, `HighRisk` |
| `dependency` | required | `Dependency` |
| `evidence` | required | `Evidence`, `EvidenceSupport`, `EvidenceChallenge`, `AttributedAssertion` |
| `context_gap` | required | `ContextGap` |
| `decision` | required | `Decision`, `StrategicDecision`, `OperatingDecision`, `DecisionRecord`, `StrategicChoice`, `Judgement`, `StrategicResearch`, `StrategicSignal` |
| `mission` | secondary | `Mission`, `MissionScope`, `MissionRationale`, `MissionPortfolio` |
| `criterion` | secondary | `SuccessCriterion` |
| `milestone` | secondary | `Milestone` |
| `capability` | secondary | `CompanyCapability`, `KeyPath` |
| `rationale` | secondary | `LeadershipInsight`, `Lesson`, `ReviewConclusion` |
| `source_record` | trace_only | `SourceRecord` |
| `confirmation` | trace_only | `Confirmation`, `ConfirmationEvent`, `RevisionEvent` |
| `role_assignment` | trace_only | `RoleAssignment`, `DirectlyResponsibleRole`, `DirectlyResponsibleIndividual` |
| `other` | — | 其余（status enum / module / partition / condition 类等结构型） |

### 4.2 显式降权规则（覆盖 type）

- `confirmation_status` 非空的 `AttributedAssertion` 且其唯一作用是"确认某对象" → `trace_only`（除非它本身携带证据内容）。
- `SourceRecord` 永远 `trace_only`，只作锚点。
- `RoleAssignment` / `Confirmation` 永远 `trace_only`，除非被一个 required-role member 直接引用且无其他 required member 覆盖该关系。

## 5. ID → 人类可读名 解析

问题：当前 `_relational_phrases` 输出 object 的 URI fragment（`依赖：dependency-product1-lighthouse-synchronous-delivery`）。

方案：编译时先扫描 Pack 全部 member，建 `name_index: dict[str, str]`，键为 member.id（fragment），值为 `member.display_name or member.scope or member.id`。渲染关系短语时，若 object fragment 命中 name_index，输出其名称；否则保留 fragment（不臆造）。member ID 退到行尾 `[member:...]` 锚点，正文只出现名称。

- name_index 范围：本 Pack 四类 member（current/candidate/provenance/gap）并集。
- 冲突（同 id 不同名）：以 display_name 为准（id 唯一，不应冲突；若冲突记 warning）。
- object 是字面值（非 `https://` 开头）：原样输出。

## 6. 分层预算（替代遍历序先到先得）

预算按**决策作用**分配，不是按认知状态分区先到先得。`max_chars` 按下表切分（头部/尾部固定开销另计）：

| 槽位 | 占比 | 硬规则 |
|---|---|---|
| 议题 + 认知状态说明 | 10% | 根议题必进 |
| 目标（outcome）+ 当前进展（progress） | 25% | 至少 1 个 outcome 必进 |
| 风险（risk）+ 依赖（dependency） | 25% | 高风险对象不能被 trace_only 挤出 |
| 信息缺口（context_gap） | 25% | **只要 Pack 存在 Gap，正文禁显"没有信息缺口"** |
| 证据（evidence） | 10% | — |
| 元数据（footer） | 5% | 固定 |

每个槽位内，member 按 `tier` 优先（required > secondary > trace_only），同 tier 内按 `(incident 边数 desc, id asc)` 排序——incident 边数即 statements 中该 member 作为 object 被引用的次数，从现有 statements 可数。trace_only 默认不占正文槽位，仅当槽位有余且被 required member 直接引用时进入。

**槽位填充**：每个槽位贪心放入完整 member 行（沿用事实单元预算原则：放完整行，放不下进 omission，不做字符截断）。某槽位放不下 → 溢出 member 进 `render_omissions`，并在该槽位末尾写一句计数（见 §8）。

## 7. rendered.content 分节模板

正文按下列固定顺序分节。每节内每条事实仍是一句 + `[member:<id>][source:<graph>]` 锚点（沿用现有锚点格式，校验链路不变）。

```
# 决策议题：<query>

> 认知状态：<epistemic_summary>

## 决策目标
<outcome members，按 incident 边数排序>

## 当前进展与已有证据
<progress members> + <evidence members>

## 共同依赖与约束
<dependency members> + <capability members>

## 当前最重要的风险
<risk members>

## 拍板前需要补齐的信息
<context_gap members，编号列表 1./2./3.>

## 决策与判断依据
<decision members> + <rationale members>（如有）

<omission 计数行>

---
<footer 元数据：pack_id / ontology / renderer>
```

`<epistemic_summary>` 是唯一允许的"半判断"文本，但仅描述**材料状态**（如"本次材料主要处于 Candidate/PreliminarilyConfirmed 状态，适合形成条件性判断，尚不足以形成正式承诺"），由 Pack 的 confirmation_status 分布确定性生成——不涉及任何具体业务结论。模板化短语，非自由生成。

## 8. omission 退出正文

正文不再罗列 67 条 omission。每个溢出槽位末尾写一行：

`> 另有 N 项 <role 中文名> 未展开，可通过结构化 Context Pack 查询。`

完整 omission 列表进 `render_omissions`（见 §9），每条含 `{member_id, role, tier, reason, incident_edges}`。`reason` 取值：`max_chars_exceeded` / `trace_only` / `lower_tier`。

## 9. decision_context schema（结构化并行输出）

Render API 响应增加 `decision_context` 字段，供 Agent 直接消费（无需解析 Markdown）：

```json
{
  "decision_context": {
    "compiler_version": "decision-context/v1",
    "issue": { "query": "...", "matched_root": "...", "epistemic_summary": "..." },
    "outcomes": [ { "member_id": "...", "name": "...", "claim": "...", "epistemic_status": "Candidate", "source_graphs": ["..."] } ],
    "progress": [ <同上> ],
    "dependencies": [ <同上> ],
    "risks": [ <同上> ],
    "evidence": [ <同上> ],
    "gaps": [ <同上> ],
    "decisions": [ <同上> ],
    "secondary": [ { "member_id": "...", "role": "mission|criterion|milestone|capability|rationale", "name": "...", "claim": "..." } ],
    "render_omissions": [ { "member_id": "...", "role": "...", "tier": "...", "reason": "...", "incident_edges": N } ]
  }
}
```

每个 entry 的 `claim` 即现有 `RenderedFactUnit.canonical_claim`（已人类可读化，§5）。`epistemic_status` 取自 member.confirmation_status。LLM 模式下 LLM 接收 `rendered.content`（Markdown），不接收 decision_context 原始结构——保持单一润色入口。

## 10. 与现有渲染器的关系

- 新增 `src/tkos_runtime/application/decision_context_compiler.py`，输入 `ContextPack`，输出 `(decision_context: dict, units: list[RenderedFactUnit ordered by section>, omissions: list)`。
- `context_renderer.render()` 改为先调 Decision Context Compiler 得到分节 units + omissions，再走现有 `_assemble_markdown`（扩展为按 §7 模板分节）+ LLM 润色 + 校验。
- `RenderedFactUnit`、`_validate_llm_output`、gap 去重、事实单元预算、Literal 约束、TextPolisher 端口——**全部保留不动**。v1 是在其上加一层分节+排序+预算策略，不改 grounding 校验。
- 现有 30+ renderer 测试不能回归。新增测试覆盖：role 分类、name_index 解析、分层预算（Gap 必进 / omission 退出正文 / trace_only 降权）、decision_context schema、epistemic_summary 模板。

## 11. 实施切片建议（供 plan 参考）

1. `classify_role(member)` + role 映射表 + 单测（纯函数，无 IO）。
2. `build_name_index(pack)` + 关系短语人类可读化 + 单测。
3. 分层预算（`allocate_budget(units, max_chars, role, tier)`）+ 槽位硬规则 + 单测（Gap 必进、omission 退出正文）。
4. `decision_context_compiler.compile(pack)` 组装 decision_context dict + 按 §7 分节 units。
5. `render()` 接线 + `rendered.content` 分节模板 + decision_context 并行输出。
6. 端到端测试：FE 议题 → ≤4000 字 / 6–8 节 / Gap 进正文 / omission 退出正文。
