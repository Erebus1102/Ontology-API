# Decision Context Compiler v1 — Design Spec

> **Grounding boundary (decided):** 确定性编译器**只产出 (A) 类结构化叙事**——议题、目标、进展、依赖、风险、缺口、证据的重排与人类可读化。**不产出 (B) 类条件性判断**。判断留给消费方。epistemic_summary 也只报状态分布。

> **Honesty boundary (r3 P1-5):** 结构校验通过 **≠** 自然语言语义等价证明。编译器/校验器只保证**结构**完整（member、partition、section、source、状态标签、数字、URI）。自然语言层的语义保持始终 `not_proven`。`grounding_status` 收窄为 `structurally_validated`，不再称 `validated`。

> **Revision note (r3):** 依二轮评审修订 5 项 P1 + 4 项 P2。锚点与校验主键升级为 `view_key=(member_id,partition)`；type 抽取改为 Admission 门控两阶段；定义 `mandatory_floor` 与 422；模型移至中立模块避免循环依赖；grounding 声明收窄并拆三状态。

## 1. 背景与问题

当前渲染链路解决了来源与认知状态可追溯性，但有六项缺陷：BFS 不排序、对象清单非叙事、ID 进正文、预算按遍历序、状态维度≠作用维度、LLM 只能改标点。

**根因（P1-1）**：`ContextCompiler._to_member` 将 `member.statements = incident`（入边），实体自身 `rdf:type` 是出边（在 `subject_by_partition`），未存入 member。

## 2. 目标

`Ontology Query → Structured ContextPack → Decision Context Compiler → {decision_context, rendered.content} → (可选 LLM 表达优化) → Agent`

- Structured ContextPack 权威不动（除 §4 的 `rdf_types` 字段）。
- v1 验收：真实 FE 议题（73 Candidate / 8 Gap / 15 Provenance）编译成 ≤ `max_chars`、按决策作用分节、每 view 保留锚点的决策上下文；8 Gap 全进 `decision_context.gaps` 且 Markdown 不出现"没有已知信息缺口"；omission 退出正文。

## 3. 不在 v1 范围内

- (B) 类条件判断（含 epistemic_summary）。
- DecisionClaimBundle 多 member 段落聚合（v1 每段一句一锚点）。
- 连续 relevance score（用分层硬规则 + incident_edges）。
- LLM 综合判断。
- 业务质量评测套件。
- Derived 的 Markdown 叙事（进 `decision_context.derived`，不静默丢失）。
- **自然语言语义等价证明**（始终 `not_proven`，见 §10）。

## 4. Role 分类（r3：Admission 门控两阶段 + 完整 IRI）

### 4.0 前置：`ContextPackMember.rdf_types`（切片 0）

```python
rdf_types: list[str]   # 完整 class IRI 列表，如 ["https://ontology.tokenking.ai/tkos#DomainOutcome"]
```

**两阶段抽取（P1-2，不绕过 AdmissionPolicy）**：
1. 第一阶段：对每个 `(member_id, partition)` 执行 `AdmissionPolicy.decide(part, subj, as_of)`。
2. 第二阶段：`rdf_types` **只从 `accept=True` 的 subject slice** 收集该实体的 `rdf:type`。被拒切片（Archived / 超有效期 / 状态不满足）的类型**不得**影响获准 view 的 role。

存完整 IRI（非 fragment）以避免跨模块/namespace 同名 class 冲突；role 映射时再取 fragment。v1 **不设**"类型可跨状态复用"的治理例外——若未来需要，须显式 spec 修订 + 测试，不由 `_to_member` 隐式读取。

### 4.1 type_index 与 view_key

- `type_index[member_id]` = 该 member 在**所有获准分区**的 `rdf_types` 并集（一个实体一个 role）。
- `view_key = (member_id, partition)` —— 输出与校验的主键（见 §7 锚点、§10 校验）。
- `classify_role(member_id)` 读 `type_index[member_id]`，按 §4.2 表取首个命中（required > secondary > trace_only），无命中 → `other`。

效果：同一 Mission 的 Candidate view 与 Provenance view 得**相同业务 role**，各自 source_graph / epistemic_status / partition 独立保留。

### 4.2 Role 映射表（grounded in `ontology/schema/tkos-ontology.ttl`）

| Role | 层级 | 本体 class（fragment） |
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
| `responsibility` | secondary | `RoleAssignment`, `DirectlyResponsibleRole`, `DirectlyResponsibleIndividual` |
| `source_record` | trace_only | `SourceRecord` |
| `confirmation` | trace_only | `Confirmation`, `ConfirmationEvent`, `RevisionEvent` |
| `other` | — | 其余 |

### 4.3 trace_only 规则（无例外）

`SourceRecord`、`Confirmation`、`ConfirmationEvent`、`RevisionEvent` 不独立进 Markdown 正文（v1 无例外）。名称可经关系短语附着到 required member。完整保留在 `decision_context.render_omissions`。DRI 重要时走 `responsibility` secondary 显式进入。

## 5. ID → 人类可读名（r3：确定性优先级 + 含 derived）

- `name_index` 扫 current + candidate + provenance + gap + **derived**。
- **名称优先级（P2-3，确定性）**：真实 `displayName` → `scope` → `fragment`。"真实 displayName"判定：`display_name != member.id fragment`（ContextCompiler 在无 displayName 时用 fragment 兜底，故相等即非真实）。
- **同 ID 跨 view 冲突优先级**：`Confirmed > Candidate > Provenance > Derived > IRI 字典序`；冲突记入 `decision_context.warnings`。
- object fragment 命中 name_index → 输出名称；否则保留 fragment（不臆造）。object 为字面值原样输出。member ID 退到锚点。
- derived 进 name_index（可被引用）但 v1 不进 Markdown 叙事，只进 `decision_context.derived`。

## 6. 分层预算（r3：mandatory_floor + 422 + 两遍装配）

### 6.1 mandatory_floor 与 422（P1-3）

```
mandatory_floor =
    最小标题 + 根议题短格式 + 状态摘要 + 每个 Gap 最小短格式
  + 必要 section 标题 + footer
```

`mandatory_floor` 随实际内容动态计算（Gap 数 0 时更低）。当 `max_chars < mandatory_floor`：**返回 HTTP 422**，不放松"全部 Gap 进 Markdown"契约：

```json
{ "code": "render_budget_too_small",
  "requested_max_chars": 500,
  "minimum_required_chars": 1378 }
```

API 字段 `max_chars` 的静态下限可保留，但动态 `mandatory_floor` 是真正的硬门。

### 6.2 闭合预算公式

```
fixed_text      = render_header + 所有分节标题 + 空节占位 + footer + omission_summary_reserve
usable_budget   = max_chars - len(fixed_text)
slot_budget[s]  = usable_budget * slot_ratio[s]
```

槽位比例（占 `usable_budget`）：issue 10% / outcome+progress 25% / risk+dependency 25% / gap 25% / evidence 10% / secondary 5%。

### 6.3 两遍精确装配（P2-4）

- **第一遍**：按槽位贪心选择完整 view 行，计算各槽 omission。
- **第二遍**：生成精确 omission 计数行 + 完整 fixed_text，重算 `len`。
- **超限回收**：从最低优先级可选项开始回收（secondary → evidence → 非 root outcome…）。
- **不可回收项**：根议题、至少 1 个 Outcome、每条 Gap 短格式。

### 6.4 Gap 短格式 + 动态借用（P1-3）

全部 Gap 进 `decision_context.gaps`（完整）。Markdown 用短格式：

```
1. <display_name> [<confirmation_status>]
   [member:<id>][partition:<graph>][source:<graph>]
```

gap 槽不足 → 借 evidence → risk/dependency → outcome/progress → 全局余额兜底，保证每条 Gap 至少短格式。硬规则：`decision_context.gaps` 非空时 Markdown 禁显"没有已知信息缺口"。

### 6.5 incident_edges（P2-2：单一常量）

排序信号，按 view 计算：同一 partition 内 `statement.object == member 完整 IRI` 且 `predicate ∈ DECISION_INCIDENT_PREDICATES` 的去重数量。

```python
# domain/render_units.py —— 唯一定义处，无省略号
DECISION_INCIDENT_PREDICATES = frozenset(TRAVERSAL)
```

`TRAVERSAL` 复用 `domain/query_plan.py` 的现有业务关系集（P0-1 已收敛为单一源）。结构性谓词（`rdf:type`、`displayName`、`scopeDescription`、`hasConfirmationStatus`、`hasStatus`、`validFrom`、`validUntil`、`sourcedFrom`）本就不在 `TRAVERSAL` 中，故不计入。同四元组去重；跨分区关系不计入当前 view。

## 7. rendered.content 分节模板（r3：view-aware 锚点）

```
# 决策议题：<query>
[member:<root_issue_id>][partition:<graph>][source:<graph>]

> 认知状态：<epistemic_summary>

## 决策目标
<outcome members>
... (进展与证据 / 依赖与约束 / 风险 / Gap 短格式编号 / 决策与依据) ...

<各槽位 omission 计数行>

---
<footer：pack_id / ontology / renderer>
```

**锚点格式（P1-1）**：每个事实行/短格式行尾三段锚点 `[member:<id>][partition:<graph>][source:<graph>]`。`partition` 锚点使同 ID 的 Candidate/Provenance view 各自可区分，校验主键升级为 `view_key`。

### 7.1 epistemic_summary（P1-2/P2-1：按 view 计数，Gap 是 Candidate 子集）

**只输出可计算的状态分布，按 view 计数**：

```
候选视图 73 项（其中信息缺口 8 项），溯源视图 15 项。
已确认 0、初步确认 14、候选（含缺口）73。
以下内容按原确认状态呈现。
```

计数规则（确定性）：
- 按 **view**（非去重对象）计数；同 ID 的 Candidate/Provenance view 分别计入各自分区。
- Gap 是 Candidate 子集，显式标注"其中"，不让读者误以为 73+8+15 互斥。
- `confirmation_status=None` 的 Candidate view 计为候选。
- Derived 单列（若非空）。
- 被 Admission 拒绝的 view 排除（已在 §4.0 门控）。
- **不含**"适合判断/不足以承诺/最可能失败"等 (B) 类表述。

## 8. omission 退出正文

每个有溢出的槽位末尾写计数行：`> 另有 N 项 <role 中文名> 未展开，可通过结构化 Context Pack 查询。` 完整列表进 `decision_context.render_omissions`，每条 `{member_id, partition, role, tier, reason, incident_edges}`，`reason ∈ {max_chars_exceeded, trace_only, lower_tier}`。

## 9. decision_context schema（r3：三状态 + view_key + partition）

```json
{
  "decision_context": {
    "compiler_version": "decision-context/v1",
    "issue": { "view_key": ["<id>","<partition>"], "member_id":"...", "name":"...", "claim":"...",
               "epistemic_status":"Candidate", "partition":"...", "source_graphs":[...],
               "query":"...", "matched_root":"...", "epistemic_summary":"..." },
    "outcomes": [ <entry> ], "progress": [ <entry> ], "dependencies": [ <entry> ],
    "risks": [ <entry> ], "evidence": [ <entry> ],
    "gaps": [ <entry_full> ], "decisions": [ <entry> ],
    "secondary": [ { "view_key":[...], "role":"mission|criterion|...", ...<entry> } ],
    "derived": [ { "member_id":"...", "claim":"...", "rule":"...", "proof":[...] } ],
    "render_omissions": [ { "member_id":"...", "partition":"...", "role":"...", "tier":"...",
                            "reason":"...", "incident_edges": N } ],
    "warnings": [ "..." ]
  }
}
```

`entry` = `{view_key, member_id, name, claim, epistemic_status, partition, source_graphs}`（`epistemic_status` 可 null）。`entry_full`（Gap）增 `scope`、关联 member_ids、来源关系。每个 entry 固定含 `partition` 与 `source_graphs`。

### 9.1 输出三状态（P1-5，收窄 grounding 声明）

```json
{
  "rendered": {
    "content": "...",
    "grounding_status": "structurally_validated",
    "semantic_preservation": "not_proven",
    "rendering_status": "completed",
    "mode_used": "deterministic | deterministic_fallback | llm_polished"
  },
  "metadata": { "pack_origin": "server_resolved | client_supplied", ... }
}
```

- `grounding_status`：仅 `structurally_validated`（member/partition/section/source/状态标签/数字/URI 已过结构校验）。**不再用 `validated`**。deterministic 链路结构有效是构造保证；LLM 链路仅在 §10 八条全过时为 `structurally_validated`，否则回退到 deterministic（仍 `structurally_validated`，`mode_used=deterministic_fallback`）。
- `semantic_preservation`：v1 恒为 `not_proven`——自然语言语义等价未证明。
- `pack_origin`：表**输入信任**（server_resolved vs client_supplied），替代旧 `grounding_status=unverified_input` 的混淆用法。
- `rendering_status`：`completed`（成功产出，含 fallback）。

旧测试中 `grounding_status == "validated"` / `"unverified_input"` 的断言须迁移（计划层处理）。

## 10. 与现有渲染器的关系（r3：中立模块 + view_key 校验 + 收窄声明）

### 10.1 模块布局（P1-4：消除循环依赖）

新增中立领域模型 `domain/render_units.py`（**不**用 `render_models.py`，避免与 `api/render_models.py` Pydantic 请求模型混淆）：

```
domain/render_units.py
├── RenderedFactUnit        # 移自 context_renderer.py
├── DecisionContextEntry
├── RenderOmission
├── CompiledDecisionContext
└── DECISION_INCIDENT_PREDICATES
```

依赖方向单向：`decision_context_compiler → domain.render_units ← context_renderer`。`context_renderer.py` 临时 `from tkos_runtime.domain.render_units import RenderedFactUnit` re-export，保旧测试/调用方不破。

### 10.2 校验器扩展（P1-1/P1-5：view_key 主键 + 收窄声称）

`_validate_llm_output` 升级为 **view-aware section 校验**。每个 `RenderedFactUnit` 携带 `view_key` 与 `expected_section`（由 role 派生）。LLM 输出后按 `view_key` 验证八条：

1. 每个选中 `view_key` 的三段锚点**精确出现一次**（member_id 可跨分区重复，view_key 唯一）；
2. 每个 view 的锚点落在其 `expected_section`（由 Markdown 标题切分）；
3. `member ↔ partition ↔ source` 绑定不变，source 集合不变；
4. confirmation_status 标签不变；
5. section 集合与顺序不变（标题固定，程序重新组装）；
6. 无 phantom view_key；
7. 无 missing view_key；
8. 数字/URI 不新增（基线 = 完整 deterministic 文本）。

**能力边界（P1-5，必须写入 Spec）**：八条是**结构**校验。它**不能**检测同一事实行内新增的纯文本业务判断（如"该风险已可忽略""公司应暂停灯塔项目"——无新数字/URI/member ID）。因此：
- `grounding_status` 仅声明 `structurally_validated`，不声称语义等价；
- `semantic_preservation` 恒 `not_proven`；
- 更安全的润色路径是**逐单元结构化润色**（LLM 返回 `{view_key, original_claim, polished_claim}`，程序重组 section 与锚点）——即便如此，纯文本语义等价仍是未证明边界。v1 可先用整段润色 + 八条结构校验，逐单元结构化润色列为 v1 可选增强。

**保留不动**：RenderedFactUnit 数据结构（迁址不改结构）、gap 去重、Literal 约束、TextPolisher 端口、数字/URI/member-ID 提取器。

### 10.3 前置改动（切片 0）

`ContextPackMember.rdf_types`（完整 IRI，Admission 门控两阶段抽取）+ `pack_to_dict`/`dict_to_pack` round-trip + `RenderedFactUnit` 迁至 `domain/render_units.py` + re-export。

## 11. 实施切片（r3）

0. **领域模型搬迁 + rdf_types**：`domain/render_units.py`（RenderedFactUnit 等迁入 + `DECISION_INCIDENT_PREDICATES`）；`ContextPackMember.rdf_types`（完整 IRI，两阶段 Admission 门控抽取）；serializer round-trip；re-export；单测。
1. **type_index + classify_role**：跨分区（仅 accept 切片）type_index + role 映射 + 单测（Candidate 有 type / Provenance 无 type → 同 role；图身份独立；被拒切片类型不泄漏）。
2. **build_name_index**（含 derived + 确定性优先级）+ 关系短语人类可读化 + 单测。
3. **预算**：`mandatory_floor` + 422 + 两遍装配 + Gap 短格式 + 动态借用 + incident_edges + 单测（Gap 必进、闭合 max_chars、422 在 floor 下、trace_only 不占槽）。
4. **decision_context_compiler.compile**：组装 decision_context（issue 补全、view_key、partition、derived、warnings、render_omissions）+ 按 §7 分节 units（含 view_key、expected_section）。
5. **render() 接线**：分节模板 + view-aware 三段锚点 + epistemic_summary 按视图计数 + 三状态输出（§9.1）+ decision_context 并行。
6. **校验器扩展**：view_key section 八条（§10.2）+ 收窄声称 + 对抗测试（member 移错 section / 同 ID 跨分区 / 新增纯文本判断 → 前两者回退，后者标注 not_proven 不回退）。
7. **端到端测试**：真实 FE 议题（§12 全部断言）。

## 12. 端到端测试断言（真实 FE 议题）

1. 根议题 view 必进 Markdown，三段锚点齐全。
2. `outcome-native-agent-1-0-launch-2026-08`（或对应 Outcome）必进。
3. 8 个 Gap **全部**进 `decision_context.gaps`。
4. Markdown 不存在"当前没有已知信息缺口"。
5. `risk-product1-lighthouse-resource-conflict` 必进。
6. SourceRecord/Confirmation/RoleAssignment 不独立占正文行（除非 `responsibility` secondary）。
7. `len(rendered.content) <= max_chars`。
8. omission 完整列表只在 `decision_context.render_omissions`。
9. Markdown 只出现各槽位 omission 计数行。
10. LLM 将 view 移到错误 section → 校验失败 → 回退（`mode_used=deterministic_fallback`）。
11. 同 ID 的 Candidate/Provenance view 各自保留 partition/source_graph/epistemic_status，且 `view_key` 各精确出现一次。
12. deterministic 与 LLM 输出的**已选 view_key 集合、出现次数、role section**完全相同。
13. epistemic_summary 不含 (B) 类表述。
14. `max_chars < mandatory_floor` → HTTP 422 `render_budget_too_small`。
15. `grounding_status == "structurally_validated"` 且 `semantic_preservation == "not_proven"`（任何成功渲染）。
16. `pack_origin=client_supplied` 时输入信任体现在 metadata，而非 `grounding_status`。
