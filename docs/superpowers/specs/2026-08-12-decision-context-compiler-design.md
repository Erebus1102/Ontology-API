# Decision Context Compiler v1 — Design Spec

> **Grounding boundary (decided):** 确定性编译器**只产出 (A) 类结构化叙事**——议题、目标、进展、依赖、风险、缺口、证据的重排与人类可读化。**不产出 (B) 类条件性判断**（"尚不足以承诺""最可能失败在哪里""应采用并行/主次"）。判断留给消费方（Agent / 人）。这条边界是 v1 不可逾越的 scope 红线，**包括 epistemic_summary**——它只报告可计算的状态分布，不做材料充分性判断。

> **Revision note (r2):** 依评审修订 6 项 P1 + 4 项 P2。最关键者：role 分类改为跨分区 `type_index`（需 `ContextPackMember.rdf_types` 字段）；预算改为扣除固定开销后分配并闭合到 `max_chars`；Gap 用短格式 + 动态借用；LLM 校验器扩展为 section-aware；issue 补全 member 条目。

## 1. 背景与问题

当前渲染链路（`context_renderer.py`）解决了来源与认知状态的可追溯性，但存在六项已确认缺陷：

1. 二层 BFS 返回"相关但不重要"——73 条 Candidate、8 条 Gap、15 条 Provenance 同等粒度输出。
2. 输出是对象清单，缺少经营叙事。
3. 本体 ID 进入阅读正文。
4. 字符预算按遍历顺序消耗——Assignment/Confirmation 占满预算，Gap 全部被省略，正文却显示"没有信息缺口"。
5. Current/Candidate/Gap 只表达认知状态，不表达决策作用。
6. LLM 只能做标点润色，无法重排或聚合。

**根因补充（评审 P1-1）**：`ContextCompiler._to_member` 将 `member.statements = incident`（入边），实体自身 `rdf:type` 是出边（在 `subject_by_partition`），未存入 member。因此 role 无法从 member 现有字段稳定读取——见 §4 与切片 0。

## 2. 目标

在 Structured ContextPack 与 rendered Markdown 之间增加 **Decision Context Compiler**，产出面向一次议题的阅读视图：

```
Ontology Query → Structured ContextPack → Decision Context Compiler → {decision_context, rendered.content} → (可选 LLM 表达优化) → Agent
```

- Structured ContextPack 仍是权威、完整、机器可追溯的查询结果，不动（除 §4 的 `rdf_types` 字段补充）。
- decision_context 是结构化阅读视图，与 rendered.content 并行输出。
- rendered.content 由 decision_context 编译而来。
- LLM 只对已编译好的 (A) 类叙事做表达优化，校验链路见 §10。

**v1 验收目标**：真实 FE 议题（73 Candidate / 8 Gap / 15 Provenance）编译成 ≤ `max_chars`、按决策作用分节、每段保留 member 锚点的决策上下文；8 条 Gap 全部进 `decision_context.gaps` 且 Markdown 中不出现"没有已知信息缺口"；omission 退出正文。

## 3. 不在 v1 范围内（显式排除）

- **(B) 类条件判断** —— 编译器不产出。epistemic_summary 也不产出（见 §7）。
- **DecisionClaimBundle 多 member 段落聚合** —— v1 每段按 member 粒度切句（一句一锚点），只做主题分组。
- **连续 relevance score** —— v1 用分层硬规则 + incident_edges 排序，不用数值评分。
- **LLM 综合判断** —— LLM 只做表达优化。
- **业务质量评测套件** —— v1 不建。
- **Derived 推理产物的 Markdown 叙事** —— v1 derived_claims 不进正文，但进 `decision_context.derived`（不静默丢失，见 §5/§9）。

## 4. Role 分类规则（r2 重写：跨分区 type_index）

### 4.0 前置：`ContextPackMember.rdf_types` 字段（切片 0）

给 `ContextPackMember` 增加字段：

```python
rdf_types: list[str]   # 该实体在所有获准分区中自身 rdf:type 的 class fragment 并集，如 ["Outcome"]
```

由 `ContextCompiler._to_member` 从 `m.subject_by_partition` 跨分区抽取（与 display_name/scope 同一抽取模式）。`pack_to_dict` / `dict_to_pack` 须 round-trip 此字段。这是 role 分类的数据前提。

### 4.1 type_index 与 view_key

- `type_index[member_id]` = 同一 member ID 在**所有获准分区**的 `rdf_types` 并集（一个实体一个 role）。
- `view_key = (member_id, partition)` —— 输出层仍区分具体分区 view（保 source_graph、epistemic_status 的图身份）。
- `classify_role(member_id)` 读 `type_index[member_id]`，**不读 per-view statements**。

效果：同一 Mission 的 Candidate view（有 rdf:type）与 Provenance view（只有入边）得到**相同业务 role**，同时各自的 source_graph / epistemic_status 独立保留。

### 4.2 Role 映射表（grounded in `ontology/schema/tkos-ontology.ttl`）

按**决策重要性优先**取第一个命中（required > secondary > trace_only）。无命中 → `other`。

| Role | 层级 | 本体 class |
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
| `responsibility` | secondary | `RoleAssignment`, `DirectlyResponsibleRole`, `DirectlyResponsibleIndividual`（DRI 重要时显式启用，不靠模糊例外） |
| `source_record` | trace_only | `SourceRecord` |
| `confirmation` | trace_only | `Confirmation`, `ConfirmationEvent`, `RevisionEvent` |
| `other` | — | 其余（status enum / module / partition / condition 类） |

### 4.3 trace_only 规则（r2 简化：无例外）

- `SourceRecord`、`Confirmation`、`ConfirmationEvent`、`RevisionEvent` **不独立进入 Markdown 正文**，v1 不设任何例外。
- 它们的名称可通过关系短语**附着**到 required member（如"……（确认记录：confirmation-xxx）"）。
- 它们完整保留在 `decision_context.render_omissions`（含 role/tier/reason/incident_edges）。
- DRI 若对某决策场景重要 → 走 `responsibility` secondary role 显式进入，不通过"被 required 引用即放行"的模糊规则。
- 移除原"唯一作用""无其他 required 覆盖"等无机器定义的条件。

## 5. ID → 人类可读名 解析（r2：覆盖 derived）

- 编译时扫 Pack 全部 member（current + candidate + provenance + gap + **derived**），建 `name_index: dict[str, str]`，键 = member.id（fragment），值 = `display_name or scope or id`。
- 渲染关系短语时，object fragment 命中 name_index → 输出名称；否则保留 fragment（不臆造）。member ID 退到行尾锚点。
- 冲突（同 id 不同名）以 display_name 为准并记 warning。
- object 为字面值（非 `https://` 开头）原样输出。
- **Derived 处理（P2-3）**：derived member 进 name_index（可被其他 member 的关系短语引用），但其自身在 v1 不进 Markdown 叙事，只进 `decision_context.derived`（带 rule/proof 信息）。不静默丢失。

## 6. 分层预算（r2 重写：闭合到 max_chars）

### 6.1 预算闭合公式

```
fixed_text      = render_header + 所有分节标题 + 空节占位 + footer + omission_summary_reserve
usable_budget   = max_chars - len(fixed_text)
slot_budget[s]  = usable_budget * slot_ratio[s]        # s ∈ {issue, outcome_progress, risk_dependency, gap, evidence}
```

**以下全部计入 `max_chars`**：标题、认知状态摘要、分节标题、事实行、omission 计数行、footer、空行与 Markdown 标记。最终 `len(rendered.content) <= max_chars` 是硬断言。

槽位比例（占 `usable_budget`）：

| 槽位 | 占比 |
|---|---|
| issue（议题） | 10% |
| outcome + progress（目标与进展） | 25% |
| risk + dependency（风险与依赖） | 25% |
| gap（信息缺口） | 25% |
| evidence（证据） | 10% |
| secondary（mission/criterion/milestone/capability/rationale/responsibility） | 5% |

（元数据 footer 不占槽位，已在 fixed_text 扣除。）

### 6.2 Gap 短格式 + 动态借用（P1-3）

8 条 Gap 完整行约 2,243 字，远超 gap 槽位。**所有 Gap 全部进 `decision_context.gaps`（完整 claim + scope + 关联）**；Markdown 中 Gap 用**短格式**：

```
1. <display_name> [<confirmation_status>]
   [member:<id>][source:<graph>]
```

短格式只保留 display_name + confirmation_status + member/source 锚点。详细 scope、来源关系、关联对象留结构化层。

**动态借用顺序**（gap 槽位不足时）：
1. 先借 evidence 槽未用预算；
2. 再借 risk/dependency 槽未用预算；
3. 再借 outcome/progress 槽未用预算；
4. 仍不足 → 保证**每条 Gap 至少保留短格式**（即使超出槽位，由全局余额兜底，最后才进 omission）。

硬规则：**只要 `decision_context.gaps` 非空，Markdown 禁显"没有已知信息缺口"。**

### 6.3 根议题短格式（P1-4）

根议题完整事实行约 407 字，可能超过 issue 槽（10%）。issue 槽优先放根议题完整 claim；放不下则用短格式（display_name + status + 锚点），并允许从 outcome/progress 槽借用。根议题**必须进入**（硬规则）。

### 6.4 incident_edges 定义（P2-4）

排序信号，按具体 view 计算：

> 同一 partition 内，`statement.object == member 完整 IRI` 且 `predicate ∈ 业务关系白名单` 的去重数量。

业务关系白名单**排除**结构关系：`rdf:type`、`displayName`、`scopeDescription`、`hasConfirmationStatus`、`hasStatus`、`validFrom`、`validUntil`、`sourcedFrom`。只计真正的业务关系（hasOutcome/hasRisk/dependsOn/hasEvidence/…）。同 tier 内按 `(incident_edges desc, id asc)` 排序。

## 7. rendered.content 分节模板（r2：移除 B 类表述）

```
# 决策议题：<query>
[member:<root_issue_id>][source:<graph>]

> 认知状态：<epistemic_summary>

## 决策目标
<outcome members，按 incident_edges 排序>

## 当前进展与已有证据
<progress members> + <evidence members>

## 共同依赖与约束
<dependency members> + <capability members>

## 当前最重要的风险
<risk members>

## 拍板前需要补齐的信息
<gaps，短格式编号列表 1./2./3.>

## 决策与判断依据
<decision members> + <rationale members>（如有）

<各槽位 omission 计数行>

---
<footer：pack_id / ontology / renderer>
```

### 7.1 epistemic_summary（P1-2：只报状态分布）

**只输出可计算的状态分布**，不做任何充分性/承诺判断：

```
本次 Context Pack 包含：已确认事实 0 项、初步确认 14 项、
候选材料 59 项、信息缺口 8 项、溯源记录 15 项。
以下内容按原确认状态呈现。
```

计数由 Pack 各分区 member 数 + confirmation_status 分布确定性生成。**删除**"适合形成条件性判断""尚不足以形成正式承诺"等表述——它们是 (B) 类判断，违反 §1 红线。

## 8. omission 退出正文

正文不罗列逐条 omission。每个有溢出的槽位末尾写一行计数：

`> 另有 N 项 <role 中文名> 未展开，可通过结构化 Context Pack 查询。`

完整 omission 列表进 `decision_context.render_omissions`，每条：`{member_id, partition, role, tier, reason, incident_edges}`。`reason ∈ {max_chars_exceeded, trace_only, lower_tier}`。

## 9. decision_context schema（r2：issue 补全 + partition + derived）

```json
{
  "decision_context": {
    "compiler_version": "decision-context/v1",
    "issue": {
      "member_id": "issue-...", "name": "...", "claim": "...",
      "epistemic_status": "Candidate",
      "partition": "graph-candidate-and-dispute",
      "source_graphs": ["graph-candidate-and-dispute"],
      "query": "...", "matched_root": "...", "epistemic_summary": "..."
    },
    "outcomes":   [ <entry> ],
    "progress":   [ <entry> ],
    "dependencies": [ <entry> ],
    "risks":      [ <entry> ],
    "evidence":   [ <entry> ],
    "gaps":       [ <entry_full> ],
    "decisions":  [ <entry> ],
    "secondary":  [ { "member_id": "...", "role": "mission|criterion|milestone|capability|rationale|responsibility", ... <entry> } ],
    "derived":    [ { "member_id": "...", "claim": "...", "rule": "...", "proof": [...] } ],
    "render_omissions": [ { "member_id": "...", "partition": "...", "role": "...", "tier": "...", "reason": "...", "incident_edges": N } ]
  }
}
```

`entry`（常规）：`{member_id, name, claim, epistemic_status, partition, source_graphs}`。
`entry_full`（Gap）：在 entry 基础上增加 `scope`、关联 member_ids、来源关系（Markdown 用不到，结构化消费用）。

**每个 entry 固定含 `partition` 与 `source_graphs`**；`epistemic_status` 可为 null（Provenance view 常见）。issue 现在是完整 member 条目（P1-6）。

## 10. 与现有渲染器的关系（r2：校验器扩展为 section-aware）

新增 `src/tkos_runtime/application/decision_context_compiler.py`，输入 `ContextPack`，输出 `(decision_context, units_by_section, omissions)`。`render()` 先调它，再走分节组装 + LLM 润色 + 校验。

**保留不动**：RenderedFactUnit 数据结构、gap 去重、事实单元预算原则、Literal 约束、TextPolisher 端口、数字/URI/member-ID 提取器。

**扩展（P1-5，原"校验器不动"不成立）**：`_validate_llm_output` 扩展为 **section-aware 校验契约**。每个 RenderedFactUnit 携带 `expected_section`（由 role 派生：outcome→决策目标，risk→风险，context_gap→缺口，…）。LLM 输出后验证：

1. 每个选中 member 的锚点在输出中**精确出现一次**；
2. 每个 member 的 `[member:...]` 锚点落在其 `expected_section` 内（section 由 Markdown 标题切分）；
3. member 与 `[source:...]` 绑定不变，source 集合不变；
4. confirmation_status 标签不变；
5. **section 集合与顺序不变**（标题文本固定，程序重新组装）；
6. 不出现未知 member（phantom）；
7. 不丢失选中 member（missing）；
8. 数字/URI 不新增（沿用现有基线 = 完整 deterministic 文本）。

grounding **职责**不变（仍保证：锚点齐全、分区/作用不变、无注入、无丢失）；**实现**扩展为按 section 校验。这覆盖了"LLM 把 Risk 移进决策目标""把 Gap 移进已有证据"等原校验器漏检的情形。

**前置改动（切片 0）**：`ContextPackMember.rdf_types` 字段 + `pack_to_dict`/`dict_to_pack` round-trip + ContextCompiler 抽取。

## 11. 实施切片（r2：增切片 0）

0. **`ContextPackMember.rdf_types`** —— 字段 + ContextCompiler 抽取 + serializer round-trip + 单测。
1. **`classify_role(member_id, type_index)`** + role 映射表 + 跨分区 type_index 构建 + 单测（含 Candidate 有 type / Provenance 无 type → 同 role、图身份独立）。
2. **`build_name_index(pack)`**（含 derived）+ 关系短语人类可读化 + 单测。
3. **分层预算**（`allocate_budget`：fixed_text 扣除 → usable_budget → 槽位；Gap 短格式；动态借用；incident_edges 排序）+ 单测（Gap 必进、闭合到 max_chars、trace_only 不占槽）。
4. **`decision_context_compiler.compile(pack)`** —— 组装 decision_context dict（issue 补全、partition、derived、render_omissions）+ 按 §7 分节 units（含 expected_section）。
5. **`render()` 接线** + 分节模板 + epistemic_summary 状态分布 + decision_context 并行输出。
6. **校验器扩展** —— section-aware 契约（§10 八条）+ 对抗测试（member 移错 section → 回退）。
7. **端到端测试** —— 真实 FE 议题（§12 全部断言）。

## 12. 端到端测试断言（对真实 FE 议题固定）

1. 根议题 member（`issue-product1-lighthouse-synchronous-delivery`）必须进入 Markdown 且带锚点。
2. `outcome-native-agent-1-0-launch-2026-08`（或对应 Outcome）必须进入。
3. 8 个 Gap **全部**进入 `decision_context.gaps`。
4. Markdown 中不存在"当前没有已知信息缺口"。
5. `risk-product1-lighthouse-resource-conflict` 必须进入。
6. `SourceRecord` / `Confirmation` / `RoleAssignment` 不独立占正文行（除非走 `responsibility` secondary）。
7. `len(rendered.content) <= max_chars`（硬断言）。
8. omission 完整列表只在 `decision_context.render_omissions` 出现。
9. Markdown 只出现各槽位 omission 计数行。
10. LLM 将 member 移到错误 role section → 校验失败 → 回退（`mode_used=deterministic_fallback`）。
11. 同一 ID 的 Candidate/Provenance view 不丢失图身份（source_graph、epistemic_status 分别保留）。
12. deterministic 与 LLM 输出的**已选 member 集合、出现次数、role section**完全相同。
13. epistemic_summary 不含"适合判断/不足以承诺/最可能失败"等 (B) 类表述。
