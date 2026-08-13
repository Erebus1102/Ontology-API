# 核心文档二：本体最简设计（V3.0）

状态：v1（依据 2026-08-13 拍板记录构建）
权威范围：**本体类、关系、数据属性与存留判据的唯一权威**。类名与文档一术语表一一对应；API 出入参（文档三）引用的对象不得超出本文核心集。
前提：一切设计以"支持业务闭环（文档一 §1）"为判据，**非必要勿增类和关系；不进核心集的既有类物理删除**。

---

## 1. 三层架构与分包

```text
公共层        上位本体引用（PROV / FOAF / ORG / OWL-Time）+ 治理信封基类
TKOS 领域层   企业事项本体包（Company）＋ 个人决策本体包（Persona）
              各自独立 Ontology IRI / Version IRI，共同导入公共层，全租户共享
租户实例层    每租户独立命名图（{tenant} × {partition} 矩阵），组织级租户：
              词元云集、房懂懂、AIDC（独立 Key、独立图空间）；灯塔为跨组织协作作用域
```

Release 记录 company / persona 双版本（**Persona 包落地前 persona 版本为 null**，字段结构先就位）；合并制品继续生成供 Protégé 与推理器使用。

## 2. 核心类集（存留清单，每类必须支撑闭环某一环）

**主链（9 类，企业事项包）**

| 类 | 支撑闭环环节 |
|---|---|
| `StrategicSignal` | 信号记录（signalSourceType 枚举） |
| `StrategicIssue` | 议题创建与确认（potential/confirmed） |
| `StrategicResearch` | 研究双路径 |
| `Artifact` | Research Result 及各类材料 |
| `Judgement` | 版本化判断（会议轮次驱动） |
| `Agreement`（新增，⊂ `AttributedAssertion`） | 战略结论落盘（close/go_on）。Decision 不作本体类 |
| `DecisionRecord` | 战略会议轮次载体 |
| `Mission` | go_on 后的执行单元 |
| `Evidence` | 判断的支持与挑战 |

**组织与人（4 类，公共层）**：`Person`、`OrganizationalUnit`、`Role`、`RoleAssignment`（DRI 指派、研究任务指派——Task 不建类）。

**治理信封（6 类，公共层）**：`SourceRecord`（来源与原文定位）、`ConfirmationEvent` / `ConfirmationStatus`（候选→确认）、`RevisionEvent`（修订链事件）、`ContextGap`（缺口显式化）、`ContextPack`（API 1 权威结果对象）。

**经营骨架（2 类 + 在用子类，企业事项包）**：`Domain`（Mission 归属，`belongsTo`）、`Outcome`（含实例数据在用的子类，以 V3.0 审计为准）。

**企业客观事实（慢变，13 类 + 1 新增，企业事项包）**——研究与判断引用的背景事实，更新低频、走蒸馏 + git 确认通道：

| 簇 | 类 | 回答的问题 |
|---|---|---|
| 公司宪法簇（6） | `CompanyConstitution`、`CompanyPurpose`、`CompanyVision`、`CoreValue`、`OperatingPrinciple`、`CompanyPolicy` | 为什么存在、遵循什么、什么不可妥协 |
| 公司现实簇（5） | `CompanyProfile`、`BusinessModel`、`CompanyCapability`、`CompetitiveBarrier`、`PerformanceFact` | 我们是谁、靠什么赢、现状如何 |
| 产品（1，**新增**） | `Product`（主数据锚，TBox 现缺此类） | 产品客观描述与版本演进（如产品 1.0） |
| 方法簇（2） | `WorkPattern`、`StrategyContent` | 四场景工作方法与战略方法内容 |

（宪法/现实/方法簇均有真实蒸馏实例在用：2026-08-12 战略、商业模式、方法论三批。）

**反馈（1 类，新增）**：`FeedbackRecord ⊂ ContextAsset`。

**Persona 最小集（8 类，个人决策本体包）**：`DecisionMaker`、`DecisionProfile`、`DecisionPrinciple`、`TradeoffRule`、`DecisionBoundary`、`DecisionCase`、`DecisionLearning`（已存在）、`DisconfirmingCondition`。`ObservedAdvantage` / `OverlookedRisk` 先作为 DecisionLearning 的分类属性，不建类。**8 类的内部关系与数据属性在 Persona 包设计稿（P1 开工制品）中定义**；落地前 render 的 persona 三段（案例/优势/盲区）按文档三 §3.1 降级。

**抽象挂载点（3 类）**：`BusinessEntity`、`AttributedAssertion`、`ContextAsset`。V2.4 治理五分支（StrategicEntity 等）按 §5 判据审计：无 SHACL/规则实质依赖即删。

核心集合计约 47 类（现 104 类）。**不在此清单且通不过 §5 豁免的类，V3.0 物理删除。**

## 3. 关系最简集

**新增对象属性（5 个，全部为闭环必需）：**

```turtle
tkos:addressesIssue    # StrategicResearch / Judgement / Agreement → StrategicIssue（挂靠主锚议题）
tkos:adoptsJudgement   # Agreement → Judgement（被采纳的成熟版本）
tkos:producesArtifact  # StrategicResearch → Artifact（研究产出）
tkos:mandatedBy        # Mission → Agreement（go_on 授权）
tkos:evaluatesTarget   # FeedbackRecord → BusinessEntity（被评价对象）
```

**复用既有属性（不新增重复语义）：**

| 属性 | 闭环用法 |
|---|---|
| `informedBy` | Issue → Signal |
| `sourcedFrom` | 任意断言 → SourceRecord；Judgement → DecisionRecord（形成于哪轮会议） |
| `supportedByEvidence` | Judgement → Evidence / Artifact |
| `supersedes`（传递） | Judgement 版本链、DecisionProfile 演化、一切修订 |
| `assertedBy` / `confirmedBy` | 形成主体 / 确认主体 |
| `belongsTo` | Mission → Domain |
| `hasConfirmationStatus`、`validFrom` / `validUntil`、`recordedAt`、`version` | 治理信封字段 |

**删除（V3.0 第一刀）**：`StrategicChoice`、`StrategicDecision`、`selectedAs`、`decidedAs`。唯一 StrategicDecision 实例（`decision-ceo-agent-priority-dual-scenario-validation`）迁移为 `Agreement`；`roles.py` 类型桶同步更新。`Decision`、`OperatingDecision` 进删除候选（按 §5 判据审计）。

**API payload 的本体映射补充**：`mission.dri` 落为 `RoleAssignment`（人 × DRI 角色 × Mission 作用域，复用既有指派谓词）；`mission.acceptance_criteria` 落为 Mission 关联的预期 `Outcome`（以 V3.0 审计既有 Mission–Outcome 谓词为准，缺则新增 `expectsOutcome` 一个）；`research_result.artifact_ref` 落为 `Artifact` + `sourcedFrom` SourceRecord。`evaluatesTarget` 值域需在 V3.0 审计中确认覆盖 `Artifact` / `Agreement` / `Mission` / `ContextPack`（不足则放宽值域，不新增属性）。

**Persona 使用溯源不新增属性**：研究成果“用了谁的个人本体”记录在生成 Activity（公共层 PROV：`prov:wasGeneratedBy` → Activity `prov:used` persona Context Pack）。

## 4. 数据属性最简集

新增 5 个：`agreementStatus`（`close|go_on`）、`signalSourceType`（`external|internal|ceo_personal`）、`qualityScore`（int 1–5）、`experienceScore`（int 1–5）、`gapNote`（string，仅有明显差距时填写）。
`StrategicIssue` 的 `potential|confirmed` 复用既有确认状态机制，**不新增**状态属性。

## 5. 存留判据与删除流程（V3.0 破坏性迁移）

存留 = 进核心集（§2），或满足以下任一豁免且该引用本身仍被需要：

1. 有真实实例引用（`data/instances/`）。
2. 被 SHACL / SWRL / 查询计划 / `roles.py` 引用。
3. 属于上位本体 imports。

豁免不成立即删。迁移作为**一次性联合手术**执行：物理删减 + 本节全部新增 + SHACL/SWRL/实例/测试同步迁移，在同一个破坏性 Release 完成。**分包单列为非破坏性后续**（共享命名空间 `tkos#` 不变，文件/IRI 重组不破坏实例与查询）：随 Persona 迭代与 8 类实体一起落地，避免先造零关系零实例的空包。交付物：删除清单（含逐类豁免核查）、实例迁移映射、前后类数对比、全量回归证据（解析/SHACL/Openllet/Runtime 测试）。

新增门禁（迁移后生效）：任何新类必须回答"进不进核心集、支撑闭环哪一环、哪条 Competency Question 需要它"。

## 6. 关键 SHACL 约束（进 MVP Core Profile）

- `Judgement`：必须有 `addressesIssue`、`assertedBy`、`version`、来源；被 supersede 的版本必须 `validUntil` 封口。
- `Agreement`：必须有 `adoptsJudgement`、`agreementStatus`、确认事件；同一 Issue 同时最多一个有效 Agreement（冲突进冲突集）。
  - **MVP 例外（2.0 基座）**：`adoptsJudgement` minCount 0——数据中零 Judgement 实例，强制 minCount 1 会逼造实例（违反认知诚实）；submissions（迭代 2）引入真实 Judgement→Agreement 边后收紧至 1。`mandatedBy` 同理待 Mission 落盘后激活。
- `FeedbackRecord`：必须有 `evaluatesTarget` 与至少一个评分；分值超出 1–5 被拒。
- `StrategicSignal`：必须有陈述与 `signalSourceType`。
- `StrategicIssue`：必须有陈述与至少一条 `informedBy`；同租户不重复建锚（主数据唯一性门禁）。
- `Mission`：必须有 `mandatedBy`（且目标 Agreement 为 `go_on`）与 DRI 指派。
- 确认事件：目标候选必须存在且未被确认/拒绝/替代。
- 枚举门禁：非法 `agreementStatus` / `signalSourceType` 被拒。
- Persona 实例限定 sensitive-persona 分区，确认主体为决策者本人。

## 7. 命名图与租户

图 IRI 沿用既有模板 `urn:tkos:graph:{enterprise}:{scope-kind}:{scope-id}:{partition}:{release}`。MVP 落地 `{tenant scope} × {partition:5}` 矩阵；现有实例整体归 `tokenking`；灯塔跨组织事实进协作作用域图；`{release}` 维度留待 Release 发布器。TBox 升级经 Release 对全租户生效，新增租户零 TBox 改动。

## 8. 数据分类与主数据（对齐传统数据治理）

| 数据治理分类 | 本体对应 | 实例 |
|---|---|---|
| **主数据**（稳定锚，被反复引用） | 聚合根对象 + 稳定 IRI + SHACL 唯一性门禁 | `StrategicIssue`（业务主锚：Research / Judgement / Agreement 经 `addressesIssue` 挂靠，Context Pack 以其为根）、`Person`、`Domain`、`Product`、`OrganizationalUnit` |
| 事件/事务数据（只增不改） | 不可变断言与事件 | Signal、Judgement 版本、Agreement、确认事件、FeedbackRecord |
| 参考数据（受控枚举） | SHACL 管控枚举 | `agreementStatus`、`signalSourceType`、`ConfirmationStatus` |
| **慢变客观事实**（低频更新的企业事实） | confirmed 图 + supersedes 演化 + 按 §9 加载 | 宪法簇、公司现实簇、`Product`、方法簇 |

主数据三件套：稳定 IRI 命名规范（锚对象建后不改名，内容演化走 `supersedes`）；唯一性门禁（蒸馏管道实体消歧 + SHACL，同一议题不重复建锚）；主数据目录（固定查询模板列出租户全部 confirmed 议题，作为 Agent 的议题台账）。

## 9. 慢变客观事实的加载（三种模式）

慢变事实更新低频，检索与加载按簇分三种模式，全部可按 (tenant, dataset_revision) 缓存（内容哈希不变零成本加载，变更自动失效；演化走 supersedes，宪法修订本身是重大决策事件）：

| 模式 | 适用簇 | 机制 |
|---|---|---|
| **常驻**（不走意图检索） | 公司宪法簇 | 场景 Profile 声明 always-include，固定查询模板直读 confirmed 图，跳过 BFS 与相关性排序；有 token floor，裁剪不得触碰，`omissions` 中不允许出现宪法条目；渲染进“相关原则”与“决策边界”段 |
| **锚定检索** | 公司现实簇、`Product` | 议题提及产品/能力/商业模式时经主数据锚一跳带出（Product 与 Domain 同为主锚），参与相关性排序但因慢变可长缓存 |
| **场景绑定** | 方法簇（`WorkPattern`、`StrategyContent`） | WorkPattern 与四场景 Profile 一一绑定，选定场景即加载对应方法内容，不参与检索 |
