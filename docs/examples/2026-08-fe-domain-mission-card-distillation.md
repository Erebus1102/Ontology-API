# 8 月 FE Domain Mission Card 蒸馏记录

## 蒸馏结论

已从 CEO 对齐版 v2.0 提取一条完整的候选经营链：共同 Company Outcome、FE Domain、Domain Outcome、一个 Mission Portfolio、三条 Mission、三位一体的 DRI 承担、Mission Outcome、成功标准、关键路径、里程碑、依赖、风险和三个 Context Gap。

候选实例写入 [2026-08-fe-domain-mission-card-candidates.trig](../../data/instances/2026-08-fe-domain-mission-card-candidates.trig) 的 `tkos:graph-candidate-and-dispute`。DRI 于 2026-08-11 对卡片结构作出初步确认，确认事件记录在 [2026-08-fe-domain-mission-card-preliminary-confirmation.trig](../../data/instances/2026-08-fe-domain-mission-card-preliminary-confirmation.trig) 的 `tkos:graph-decision-provenance`。三个运行 Gate 保持候选状态；本轮不向 `tkos:graph-confirmed-enterprise` 写入任何三元组。

## 可直接进入候选图的内容

| 层级 | 提取对象 | 数量 | 来源位置 |
|---|---:|---:|---|
| 公司 | Company Outcome | 1 | “共同的 Company Outcome” |
| 领域 | FE Domain、Domain Outcome、Mission Portfolio | 3 | 文首和 “Mission Portfolio” |
| 业务运行 | Mission、Mission Outcome、DRI 承担 | 3、3、3 | FE-M1、FE-M2、FE-M3 卡片 |
| Mission Card | 缘由、边界、成功标准、关键路径 | 各 3 | 各 Mission 的同名章节 |
| 节奏 | Milestone | 12 | 各 Mission 的里程碑表 |
| 运行约束 | Dependency、Risk | 3、12 | 各 Mission 的依赖、风险与升级 |
| 知识缺口 | ContextGap | 3 | “组合运行与承诺 Gate” |

“Green 成功证据”被建模为 `SuccessCriterion`。它描述验收门槛，不能被当作已经发生的 `Evidence`。卡片预期形成的真实 Decision、调用日志、业务增益记录、确认记录与迁移结论也保留为空位，等待运行材料进入后再蒸馏。

## FE-M1 真实议题材料补充

飞书《TKOS 企业事项与个人决策本体方案》第 508 版已作为第二份 `SourceRecord` 进入候选图。文档提出的渠道扩张投入场景保留为历史验证场景。DRI 于 2026-08-11 提供的真实议题为“是否在本季度同时完成产品 1.0 上线和灯塔项目交付”，对象标识为 `issue-product1-lighthouse-synchronous-delivery`，所属 Domain 为 FE，并通过 `supersedes` 替代先前的渠道扩张示例。

当前 8 月 Outcome 为“让灯塔项目常态化高质量使用 CEO Agent”，对象标识为 `outcome-lighthouse-ceo-agent-routine-use-2026-08`。议题和 Outcome 均保持 `Candidate`，并附带 `gap-product1-lighthouse-synchronous-delivery-facts`，等待补齐产品 1.0 与灯塔交付的完成定义、资源与依赖、当前进展、可选节奏、风险、Decision 主体、事实确认人与验收口径。

## 业务文档补齐结果

本轮补读《2026 年 8 月 Outcome-Mission 展开纲领 v1.1》与《灯塔项目工作计划 v10》。两份材料明确了以下事实边界：

- 灯塔 8 月阶段要求一号位与至少一位关键角色进入真实使用，并形成采用、ACT 或闭环改善证据；一号位 Application 需要在真实会议和经营事项中持续使用、调用统一 Context 并回写结果。
- 灯塔总体交付覆盖模块 3-7，包含目标组织与运行机制方案、一号位 Agent、管理者网络、任务推进与督导 Agent、Agent Foundry、TokenHub 和三类培训。它是分阶段交付，不是一个单点上线动作。
- 灯塔计划中的“原生 Agent 1.0 上线”位于一号位 Agent MVP 部署与陪跑之后。DRI 已明确产品 1.0 为网页版本的 CEO Agent、CO Agent、Ontology 与 TokenHub 联合上线；`gap-product1-name-scope-confirmation` 已归档，并保留既有计划表述以便后续建立版本演进关系。
- 同步交付的资源冲突应进入公司级 Mission Portfolio Review。8 月基线要求新增事项说明支持 Outcome、替代 Mission、DRI 与资源；FE 卡片要求优先保护真实业务闭环，未被消费的能力范围可被削减。

因此，事项以 FE 为责任锚点，同时连接 Agents、Transformation 与 FE 三个责任空间。`risk-product1-lighthouse-resource-conflict` 与 `dependency-product1-lighthouse-synchronous-delivery` 已写入候选图。现阶段缺失的是实际进展、确定资源量、产品版本边界、项目授权人、Decision 主体与复审条件。

## Week 1 运行证据补充

《0810 TKOS Domain DRI 复盘会议 Week 1》已蒸馏为 [2026-08-10-week1-review-distillation.trig](../../data/instances/2026-08-10-week1-review-distillation.trig)。会议补充了以下当前状态：

- FE 的本体设计初步 Demo 已完成并验证，计划当日推动可供团队使用的版本；正式设计、评测方案、Demo 评审和内外部验证场景需要由 FE、Method、Product 共同确定。
- 月底目标已被明确为：在公司内部和王总侧高质量使用一号位能力，灯塔项目中的 Method、Agents 与 Engine & Ontology 进入持续运行。
- 当前高风险为三周窗口内缺少客户侧场景、数据蒸馏、王总时间和三方验证计划；该风险属于 Method、Product 与 FE 的共同责任。
- 会议提出灰度反馈、单议题端到端追踪、内部与客户双线验证等候选方式，尚未形成正式 Decision。
- 产品 1.0 各组件的实际线上状态、调用日志、客户使用记录、体验和质量评分、ACT 改善数据仍未在纪要中出现，已单列为 `gap-product1-lighthouse-actual-progress`。

## 产品 1.0 与双场景验证更新

DRI 后续更新已写入 [2026-08-11-product1-validation-update.trig](../../data/instances/2026-08-11-product1-validation-update.trig)：

- CEO Agent、CO Agent、Ontology 与 TokenHub 处于 MVP 产出阶段，预计本周产出；组件级验收、联调、线上入口和调用日志仍待产出后写入。
- 王总尚未开始使用 CEO Agent，房懂懂场景的真实事项、材料、会议节点与反馈机制仍是当前缺口。
- 验证路径为 CEO Agent 优先，在词元云集与房懂懂双场景推进，两个场景按灯塔项目工作计划保持一致。
- 该路径当前保存为 `DecisionPendingConfirmation` 的候选战略决策；附上明确复审条件，等待 CEO 确认事件后生效。

## CEO Agent 入口与首批场景

DRI 更新已写入 [2026-08-11-ceoagent-and-scenarios-update.trig](../../data/instances/2026-08-11-ceoagent-and-scenarios-update.trig)：

- CEO Agent 入口为 `https://meeting-green-phi.vercel.app/`，只读 HTTP 检查返回 200，作为网页入口可达的候选 Evidence。
- CO Agent、Ontology、TokenHub 当前尚无可蒸馏的产出材料、入口或运行记录，形成 `gap-product1-other-components-evidence`。
- 首批词元云集场景为“工作方法建设”，连接 FE-M1；首批房懂懂场景为“业务本体设计选择”，连接 FE-M2。

## CEO Agent 产物与反馈补充

文件夹 `业务文档/CEO-Agent产物与反馈` 已蒸馏为 [2026-08-11-ceoagent-artifacts-feedback-distillation.trig](../../data/instances/2026-08-11-ceoagent-artifacts-feedback-distillation.trig)。新增材料分成三种证据性质：

- `反馈.md` 形成一项候选 `Evidence` 与 `EvidenceChallenge`。它表明现有会前、会后产物的结构和思路已基本及格，同时指出它们与公司已有内容、当前现实、本体建设及推理深度的结合尚不足。该反馈不包含反馈人、样本、评分标准和具体案例，因此保留为候选挑战，不能直接判定产品质量。
- 《房懂懂推理 Agent 执行计划》为房懂懂业务本体设计选择提供了任务锚点：房产决策支持、数据与估值、业务本体和规则、好时机 Agent，以及用同一真实决策任务进行架构赛马的评测框架。文中的 90/120/180 天节奏属于计划。
- 《房懂懂重塑传统房产销售行业资本市场报告》提供了业务价值模型：围绕用户买卖与置换问题，把决策报告和行动指令产品化，并以决策模型、房产本体知识图谱、用户决策行为数据闭环作为关键资产。它是战略叙事与设计依据，尚未证明运营效果。

由此新增 `gap-ceoagent-company-context-and-reasoning-depth` 与 `risk-fangdongdong-agent-architecture-unverified`。前者进入词元云集工作方法建设和 FE-M1，后者进入房懂懂业务本体设计选择和 FE-M2。CEO Agent 优先的双场景路径仍为待确认决策，新的材料只丰富其事实基础与复审条件。

## 当前三个确认 Gate

| Gate | 需要确认的事实 | 确认后更新 |
|---|---|---|
| 内部真实议题 | 议题、参与角色、事实确认人、Decision 与承接验收口径 | 写入 `StrategicIssue`、相关 ContextAsset、事实确认事件；关闭 `gap-fe-m1-real-issue` |
| 灯塔真实议题与授权 | 议题、授权人员、材料、数据边界、验收口径 | 写入客户场景 Context、AuthorityBoundary、确认记录；关闭 `gap-fe-m2-client-issue-authorisation` |
| 资源承诺 | 研发负责人、人天、Product 配合窗口、被砍范围 | 更新 M3 依赖和资源约束；关闭 `gap-fe-m3-resource-commitment` |

## 后续的运行时蒸馏路径

```text
Mission Card（候选结构）
  → 场景锁定与事实确认
  → 已确认企业事实图
  → Product 调用日志、研究、判断、Decision、Evidence
  → Decision / Evidence 溯源图
  → Review 与 ConfirmationEvent
  → Openllet 推导 MissionReadyForAcceptance
  → Context Resolver 仅按身份、目的、时间、确认状态取数
  → Context Pack 供 CEO Agent 与承接 DRI 使用
```

每次写入均保存来源、候选或确认状态与有效时间。Context Resolver 只能消费当前有效、允许范围内且达到要求确认状态的事实；候选图用于研究、对比和人工确认。

## 机器校验目标

本轮应验证候选图的 RDF / TriG 语法、核心链路和 Mission Card 完整性。`MissionReadyForAcceptance` 的 SWRL 推导不应在此时触发，因为卡片尚未给出实际 Evidence、Review 和 ConfirmationEvent。真实运行后，按完整条件、缺 Evidence、缺 Review、缺 Confirmation 四组材料再次执行 Openllet 验收测试。
