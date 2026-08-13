# MVP 需求澄清与张力消解分析

状态：v3，§5 六个问题已拍板（问题 1 的方案 C 待最终确认）。拍板结果已固化为三个指导工作的核心文档：`docs/mvp/01-unified-language-and-business-loop.md`（统一语言与业务闭环）、`docs/mvp/02-ontology-minimal-design.md`（本体最简设计）、`docs/mvp/03-api-minimal-design.md`（API 最简设计）——后续工作以这三份为权威，本文降级为决策依据存档。输入为 `改进需求.md`、AGENTS.md、当前代码与本体制品的实际状态，以及三份飞书文档**全文**（经 lark-cli 抓取，快照存于 `业务文档/飞书快照/`：《TKOS Glossary + 战略议题时序图》rev25、《TKOS 企业事项与个人决策本体方案》rev517、《1号位Agent产品说明》rev778）。v1 基于转述的推断已全部替换为事实核对结果。

---

## 0. 当前任务与 Mission 的关系

当前 8 月 FE Domain Mission 的验收锚点是两件事：灯塔项目常态化高质量使用 CEO Agent，以及产品 1.0 网页版上线（`data/instances/2026-08-fe-domain-mission-card-candidates.trig`）。本项目（Ontology Runtime）是 FE Domain 交付"企业 Context、追溯和运行能力"的载体。

`改进需求.md` 的最小 MVP 链路（Signal → Issue → Research → Judgement 版本链 → Agreement → Mission）就是 CEO Agent 在灯塔场景中要走通的战略决策回路。因此当前任务的判定标准只有一条：**Runtime 能否支撑 CEO Agent 走完这条回路一次**，而不是 API 本身的完备性。这直接决定了后文所有取舍。

---

## 1. 需求澄清：从模糊表述到可验收需求

### R1 两套本体包与业务可读层级

事实核对（本体方案 §2）：「个人本体 / 公司本体两分」不是视图偏好，而是**两个独立发布、共享公共层、运行时联动的本体包**——企业事项本体（Company Ontology）与个人决策本体（Persona Ontology），各自拥有命名空间、版本号与发布节奏（企业事项变化快、个人画像稳定），可分别校验、发布与回滚。"个人本体"的边界已由方案 §4 明确定义（见 R10）。

公司本体内部的业务分层（改进需求的"战略域/业务域"）与方案 §3.2 的五个对象簇对应：

- 战略域 ≈ 公司宪法簇（CompanyPurpose、CompanyVision、OperatingPrinciple、CoreValue、CompanyPolicy）+ 公司现实簇（CompanyProfile、PerformanceFact、CompanyCapability、OrganizationalUnit、CultureObservation）+ 战略判断簇（Signal / Issue / Research / Judgement / Choice / Decision）
- 业务域 ≈ 结果承诺簇（CompanyOutcome、Domain、DomainOutcome、MissionPortfolio、Mission、MissionOutcome）+ 经营资产簇（Evidence、Artifact、OperatingDecision、Risk、MissionReview、Lesson、ContextGap）

澄清后的需求：

> 本体物理拆分为公共层 + 企业事项本体包 + 个人决策本体包，各有独立 Ontology IRI / Version IRI，共同导入公共层——这是 AGENTS.md 既有模块化路线的第一次真实执行。Protégé 人读视图首层按"公司本体（战略域 / 业务域，内部按五簇展开）/ 个人本体"组织。

现状核对：五簇的叶子类绝大多数已存在于当前 TBox（CompanyPurpose、OperatingPrinciple、CoreValue、PerformanceFact、CompanyProfile、CompanyCapability、MissionPortfolio、StrategicChoice、MissionReview、WorkPattern、Lesson 均已确认在册）；缺的是 Persona 包的主体对象（R10）和物理分包本身。

验收标准：

1. 两个本体包可独立发布与回滚；Release 记录 company / persona 双版本（本体方案接口一响应的 `ontologyRelease: {company, persona}` 即此契约）。
2. 全部既有 IRI 保持不变；机器侧 SHACL、SWRL、Runtime 测试保持通过。
3. Protégé 业务视图首层与两包五簇结构一致。

### R2 多租户 API Key 隔离

原文：不同租户通过不同 TKOS_API_KEY 访问不同的本体空间；词元云集 key 访问词元云集的公司本体和业务本体，灯塔项目 key 访问项目的公司本体和业务本体。

模糊点：

- "本体空间"未区分 TBox 与 ABox。推断：TBox（TKOS 领域层）全租户共享，隔离的是实例数据（ABox）与其命名图。
- 灯塔项目与词元云集的关系未定（平级租户还是子作用域）。现有 ADR-0001 将灯塔定义为跨组织协作项目。
- 跨租户共享事实（灯塔项目里包含词元云集的 Mission）的可见性规则未定。

澄清后的需求：

> 每个 API Key 绑定一个租户作用域集合。请求不再自带 `enterprise_id` / `organization_scope`——作用域由 Key 解析得出。命名图带租户维度，硬过滤在 purpose 过滤**之前**执行（与 AGENTS.md 固定过滤顺序一致：身份与用途 → 组织作用域 → 图策略 → 有效时间 → 确认状态）。词元云集 Key 的可见图集合与灯塔 Key 的可见图集合互不相同；跨组织共享事实进入显式的协作作用域图，由双方 Key 均可见。

现状核对：`auth.py` 的 `Principal.allowed_scopes` 字段已存在但从未被任何过滤逻辑消费；五个图分区是全局的，无租户维度；全部现有实例事实上属于词元云集单租户。

验收标准：

1. 用灯塔 Key 查询词元云集私有议题返回 404（知识不可见即不存在），不泄漏存在性。
2. 双方 Key 查询协作作用域内对象均命中，Pack 的 `scope_resolution` 与 `contributing_graphs` 如实记录。
3. 负向测试：Key 无法通过任何请求参数扩权到未授权作用域。

### R3 Judgement 版本链与 Agreement

事实核对（时序图 rev25，唯一被业务确认的材料）：

- Judgement 由**战略会议**形成，并在多轮会议 loop 中更新——版本产生的触发器就是会议轮次（`M→TKOS: 形成 Judgement`，loop 内 `M→TKOS: 更新 Judgement`）。
- Agreement 由 **CEO 确认成熟 Judgement** 形成，且带状态机：`close`（不予推进）或 `go_on`（推进落实 → 创建并指派 Mission → TKOS 下发 Mission Context Pack 与验收标准给 DRI）。"不予推进"也是一次正式落盘，同样需要保留。
- 本体方案 §9 确认：所有修订保留前一版本并用 `supersedes` 连接——与仓库既有 Assertion Envelope 机制完全一致，零新治理机制。

**术语冲突（三文档间最大分歧，需拍板）**：时序图用 `Agreement`；本体方案 §3 主链与对象簇用 `StrategicChoice / StrategicDecision`；Glossary 的 SICO 方法（Signal→Issue→Choice→Outcome）用 `Strategic Choice`，且 **Agreement 一词不在 Glossary 中**。同一个"战略结论落盘"环节存在三个名字。消解建议见 §3。

澄清后的需求：

> Judgement 每个版本是不可变实例，由战略会议轮次驱动产生，经 `supersedes` 成链，`formedIn` 指向承载该轮会议的 `DecisionRecord`。CEO 确认成熟版本后形成 Agreement（新增 `Agreement ⊂ Decision`，同时物理删除 StrategicChoice / StrategicDecision，见 §3），携带 `close | go_on` 状态；`go_on` 触发 Mission 创建。
>
> 时序投影是应用规则（来自 `改进需求.md`，三份飞书文档未涉及，仍需实现）：`cxo` 角色获得完整版本链；`executor` 角色仅获得链头或已确认 Agreement。被裁剪版本进入 `omissions`，阶段标记 `temporal_projection`。

验收标准：

1. 三版 Judgement + 一个 Agreement 的夹具下：cxo Key 的 Pack 含全链及版本边；executor Key 仅含 Agreement，omissions 记录被裁剪版本。
2. 无 Agreement 时 executor 仅见链头版本（语义待 §5 确认）。
3. SHACL 负向用例：Judgement 缺 `assertedBy` / 来源 / 所属议题被拒；Agreement 缺被采纳 Judgement 或缺 `close|go_on` 状态被拒。

### R4 最小 MVP 链路

时序图确认的完整链路与状态语义（全部进 SHACL 枚举与场景 Profile）：

- `StrategicSignal` 来源类型：`external | internal | ceo_personal`；同一 Signal 可被 CEO 持续补充记录。
- `StrategicIssue` 状态：`potential →（CEO 确认）→ confirmed`。
- Research 双路径并行：CEO 独立深度研究 ∥ 可选指派 DRI（Research Task → DRI 提交 Research Result）。
- 会前：TKOS 向战略会议呈现 Research Results、证据与分歧——这就是 API 1 的会议准备用途。
- Judgement 多轮迭代（R3）→ Agreement（`close | go_on`）。
- `go_on` → 创建并指派 Mission → **TKOS 下发 Mission Context Pack 与验收标准**——链路末端回到现有读侧能力，闭环成立。

澄清后的需求：

> MVP 链路复用既有类：`StrategicSignal`、`StrategicIssue`、`StrategicResearch`、`Artifact`、`Judgement`、`Agreement`（V3.0 新增，⊂ Decision）、`Mission`、`DecisionRecord`（承载战略会议，Glossary 明确 Task 不强化为独立本体层，同理不新增会议类）。新增对象属性不超过 4 个（§3）。每个环节实例满足 Assertion Envelope 治理字段，链路支持双向遍历。

验收标准：一条真实业务链路以实例形式完整落库（场景选择见 §5 问题 3），`:resolve` 以 Issue 为根取回整条链，lineage 从 Mission 反向走到 Signal。

### R5 本体模型架构层级（公共层 → TKOS 领域层 → 词元云集实例层）

澄清后的需求：

> 三层分别对应：上位本体引用（PROV / FOAF / ORG / OWL-Time，已通过 imports 引入）、TKOS 领域 TBox（`ontology/schema`，全租户共享）、租户 ABox（`data/instances`，按租户命名图隔离）。这一分层当前事实上已成立，需要的是**显式化**：为领域层声明独立 Ontology IRI / Version IRI，租户实例文件按租户归目录，文档中固定该术语。

验收标准：新增租户不触碰 TBox；TBox 升级通过 Release 版本对所有租户生效。

### R6 业务文档蒸馏链路（"链路未设计"）

现状纠偏：链路在 `docs/architecture/distillation-and-cold-start.md` 与 AGENTS.md 中**已设计**（SourceSnapshot → 解析定位 → Profile 抽取 → 消歧 → SHACL → 冲突检测 → CandidateAssertionBatch → 确认 → 发布），未实现的是**可执行形态**。现有 9 个蒸馏批次是人工（Agent 辅助）按该链路手写的 trig。

澄清后的需求：

> MVP 不建异步 Worker 服务。将现行"人工+Agent 手写 trig"过程固化为**可重复执行的 CLI 流水线**：输入文档 → LLM 按 MVP Profile 抽取候选 → 生成候选 trig + 原文定位 + ContextGap → 本地 SHACL 校验 → 人工审阅 → 以 git 提交作为确认事件载体（CI SHACL 门禁即写入门禁）。API 2 服务化推迟到出现第二个高频蒸馏租户之后。

验收标准：同一份文档重跑 CLI 产出结构等价的候选批次；无来源字段保持为空并生成 ContextGap；SHACL 不通过的批次无法进入 `data/instances/`。

### R7 六层技术架构与功能归层

原文给出 L6 Agent / L5 Access（TKOS Engine）/ L4 Reasoning / L3 Ontology / L2 Knowledge Graph / L1 Enterprise Data，并注明"意图识别放哪层没想好"、L3/L2 内容不确定。

澄清与映射（现有代码可完整拆解进六层，无需移动代码，只需固定命名）：

| 六层 | 职责 | 现有对应物 |
|---|---|---|
| L6 Agent | CEO/COO/CO Agent、数字员工 | `scripts/agent_harness.py`（模拟）；真实 Agent 待接入 |
| L5 Access（TKOS Engine） | Key→租户/角色解析、purpose 门禁、图作用域硬过滤、时序投影、Token 预算、审计 | `api/auth.py` + `domain/policies.py`（AdmissionPolicy）+ R2/R3 新增的作用域与投影规则 |
| L4 Reasoning | 意图识别、图遍历、Context 编译、SWRL 物化、确定性渲染、LLM 润色 | `adapters/gram_intent_resolver.py`、`rdflib_graph_retriever.py`、`application/*`、Openllet |
| L3 Ontology | TBox、SHACL、SWRL、Profile、业务视图 | `ontology/schema`、`ontology/shapes`、`ontology/views` |
| L2 Knowledge Graph | 租户命名图中的实例断言与事件 | `data/instances/*.trig` + `ontology/datasets` 图契约 |
| L1 Enterprise Data | 原始业务文档、会议记录 | `业务文档/` |

意图识别归层的裁定与理由：**意图识别属于 L4 Reasoning**。它是"自然语言 → 本体对象"的语义计算，输入输出都是领域对象，可被向量检索或 LLM 替换（Adapter 可换是 L4 的定义特征）。L5 Access 只回答"谁、以什么用途、能看哪些图"——它在意图识别**之前**裁剪允许图集合、在编译**之后**执行预算与投影。当前代码恰好如此工作（`allowed_graphs` 先算，`GramIntentResolver.resolve(query, allowed_graph_ids)` 后跑），无需改动。

### R8 存储：trig 是否足够

裁定：**MVP 阶段 trig + git 足够，且优于引入数据库。** 依据：

- 数据量级：全部实例约 3200 行，内存加载毫秒级；读路径无并发瓶颈。
- 治理契合：AGENTS.md 要求事件不可变、当前视图物化生成。append-only trig 文件 + git 历史 + CI SHACL 门禁天然满足不可变、审计和写入门禁，数据库反而要重新实现这三点。
- `dataset_revision` 已经是内容哈希，与 git 提交天然对应。

迁移触发条件（写入 ADR，满足任一才引入 RDF Store）：

1. 出现并发写入方（多个 Agent 同时提交需要事务隔离）。
2. 单租户实例数据超过内存加载可接受阈值（加载 > 10s 或 > 500MB）。
3. 写入-确认-读取回路要求秒级闭环（git 流程做不到）。
4. 租户数量使按文件隔离的运维成本超过运行 Fuseki/Oxigraph 的成本。

### R9 API 清单、边界与出入参简化

原文批评：现在 API 出入参太复杂；各 API 边界和时序图要明确。

澄清后的 MVP API 面（4 个业务端点 + 3 个运维端点）：

| API | 端点 | 边界 |
|---|---|---|
| API 1 查询 | `POST /v1/context-packs:resolve` | 议题 → 结构化 Context Pack |
| API 1 渲染 | `POST /v1/context-packs:render` | 议题 → 可注入 Prompt 的 Markdown（内部先 resolve） |
| API 3 溯源 | `GET /v1/assertions/{id}/lineage` | 断言 → 版本链 / 来源 / 确认 / 挑战图 |
| API 4 提交 | `POST /v1/submissions` | 幂等提交 Judgement 版本 / Agreement / Evidence / ContextGap 候选 |
| 运维 | `GET /health` `/ready` `/version` | 已实现，保持 |

出入参简化原则：**薄请求、厚响应**。

- 请求最小化：`resolve` 请求收敛为 `{query, purpose?, as_of?}`。`enterprise_id`、`organization_scope` 从请求中**移除**——由 API Key 解析（R2），消除调用方声明作用域再由服务端校验的冗余环节，也消除扩权面。`purpose` 默认 `decision_preparation`，`as_of` 默认服务器当前时间。
- 响应保持厚：版本固定字段（`ontology_release_id`、`dataset_revision`、`policy_version` 等）、omissions、scope_resolution 全部保留在响应里——这是可复现性和审计的承载处，不是复杂度问题。
- 删除 `render` 端点的 `pack`（client-supplied pack）输入路径：它引入了客户端 Pack 授权校验的额外攻击面（文档自己承认是已知门禁缺口），且推荐用法本来就是 `resolve_request` 路径。
- API 2 蒸馏不设 HTTP 端点（R6，CLI 形态）。

新增事实（本体方案 §8.2 接口一）：业务侧期望的请求形态为 `{personaId, decisionIssue, targetEntityIds?, intentHint?, asOf, tokenBudget, responseMode}`，响应含 `intent`（置信度 + alternatives）、自然语言 `persona_context`、`provenanceRefs`、`openGaps`、`validation`、`ontologyRelease{company, persona}`。这与"薄请求、厚响应"方向一致，并新增两个当前 API 没有的维度：**`personaId`**（个人决策本体的检索锚点）与 **`responseMode`**。方案 §7 规定的 persona_context 固定编译顺序（当前事项 → 当前有效事实 → 相关原则 → 相似案例 → 已验证优势 → 历史盲区 → 支持与反证 → 未知与缺口 → 决策边界 → 输出要求）应成为 render 端点的规范段落序。

方案 §8.1 的六个服务组件与现有 Runtime 组合边界一一对应（Ontology Registry→ReleasePublisher、Ontology Store→命名图+GraphRetriever、Reasoning Service→SemanticReasoner、Validation Service→SHACL 执行、Context Resolver→ContextCompiler、Prompt Compiler→ContextRenderer）——业务设计独立收敛到了与工程实现相同的边界，方向获得双向验证。

每个端点的时序图作为独立交付物补齐（resolve/render 一张、lineage 一张、submissions 一张，标注 L5/L4/L2 的职责切面）。

### R10 个人决策本体（三文档对照后发现的最大 TBox 缺口）

本体方案 §4 给出完整对象清单：公共层 `DecisionMaker`、`DecisionProfile`、`DecisionMethod`、`DecisionPrinciple`、`TradeoffRule`、`DecisionBoundary`、`DecisionCase`、`DecisionLearning`、`ObservedAdvantage`、`OverlookedRisk`、`DisconfirmingCondition`；接入层 `No1DecisionMaker`、`No1DecisionProfile`、`EnterpriseDecisionCase`、`DecisionMethodApplication`、`EnterpriseDecisionLearning`；附录 B 关系集（`usesMethod`、`producesJudgement`、`updates`、`hasDisconfirmingCondition`、`confirmedBy`、`compiledFrom` 等）。

现状核对：当前 TBox 只有 `DecisionLearning`、`DecisionProfileView`、`LeadershipInsight`、`CultureObservation` 四个边缘类；**`DecisionCase` 在 AGENTS.md 中被描述为聚合对象但从未建模**；其余 Persona 对象全部缺失。这一缺口远大于 Agreement。

澄清后的需求：

> Persona 本体作为独立包落地（R1）。MVP 最小集八类：`DecisionMaker`、`DecisionProfile`、`DecisionPrinciple`、`TradeoffRule`、`DecisionBoundary`、`DecisionCase`、`DecisionLearning`、`DisconfirmingCondition`；`ObservedAdvantage` / `OverlookedRisk` 可先作为 DecisionLearning 的分类属性延后成类。Persona 实例进 sensitive-persona 分区；确认主体是决策者本人（方案 §9：候选学习须经本人确认才进当前有效画像）；DecisionProfile 版本演化复用 `supersedes`。

验收标准：方案 §4.3 的波特五力案例可完整落为实例（Method → Case → Judgement → 后验 → Learning → Profile 更新），且 `personaId` 检索可召回相关原则、案例与改判条件。

### R11 四个使用场景与反馈回路

产品说明定义四个 Work Pattern——会议督导、战略研究、专家团讨论、任务跟进，外加统一评分机制（结果质量 1–5、使用体验 1–5、差距说明一句话，"是否真的变好只看下一次"）。

对 Runtime 的具体含义：

1. 每个场景 = 一个场景 Profile（SHACL）+ 用途配置；场景"所需准备材料"清单从 Profile 的必填/增强字段**反向导出**（产品说明的"事/人"两栏准备表即雏形）。
2. 会议督导的会后动作是**最高频写入路径**：本次确认的决策、战略共识、待验证风险、下一步与责任人、待落盘战略结论——全部落入 API 4 提交类型；"待一号位确认落盘"就是候选 → 确认事件链的产品化表达。现有事件链设计与产品动线**完全同构**，无需新机制。
3. 评分反馈当前在本体与 API 中完全缺席，是新的最小写入对象（承载方式见 §5 问题 5）。
4. "上次指出的问题有没有再出现"要求反馈与下一次同场景 Pack 可关联追溯——lineage API 的自然用例。

---

## 2. 与现有设计的张力及消解

### T1 治理型类树 vs 业务可读类树

张力（v2 修订后拆为两个不同性质的问题）：

- **公司本体 vs 个人本体：物理分包。** 本体方案 §2 已定案——独立命名空间、独立版本、共享公共层。与 AGENTS.md 既有模块化路线一致；v1 的"仅视图分层"判断对这一半不成立，予以修正。迁移方式：现有单文件 TBox 按五簇 + Persona 归属拆模块，全部既有 IRI 保持不变，合并发布制品继续生成供 Protégé 与推理器使用。
- **战略域/业务域分层：视图问题，不改机器类树。** V2.4 治理五分支保留在规范制品；业务视图制品在人读导出中按两包五簇组织首层，`export_protege_view.py` 机制扩展一个业务视图导出，同构守卫保证零语义漂移。业务人打开视图制品，工程师打开规范制品。

### T2 全局图分区 vs 租户本体空间

张力：五个分区是全局单租户的；多租户要求图带租户维度。AGENTS.md 的图 IRI 模板（`urn:tkos:graph:{enterprise}:{scope-kind}:{scope-id}:{partition}:{release}`）早已预留该设计，只是实现从未落地。

消解：按既有模板落地，分两步。第一步（MVP）：图 ID 从 5 个扩为 `{scope} × {partition}` 矩阵，现有实例整体归入 `tokenking` 作用域，新建协作作用域图承载灯塔跨组织事实；`AdmissionPolicy.allowed_graphs` 增加 scope 参数，`Principal.allowed_scopes` 从"已定义未执行"变为硬过滤第一道。第二步（后续）：`{release}` 维度待 Release 发布器实现时再启用。不引入按租户分库/分进程——单 Store 多命名图即可，与 R8 存储裁定一致。

### T3 读侧完备 vs 写侧缺失（最根本的张力）

张力：现有工程投入几乎全部在 API 1 读侧（严格 409、五维并列、渲染预算 floor、157 项测试），但 MVP 链路的核心是**写**——Judgement 版本迭代、Agreement 形成、Mission 创建都是写事件。一个"自进化 TKOS"没有写路径就不存在进化。`改进需求.md` 对"过度设计"的直觉，实质指向的是**投入方向失衡**，而不是读侧代码本身有错。

消解：**冻结读侧，转投写侧。** 读侧不再追加鲁棒性工程（渲染极端边界等已知缺口标注为"接受的边界"）；下一阶段唯一的大项是 API 4 的薄实现：幂等提交 → SHACL 校验 → 写候选图 trig（append-only 事件文件）→ 确认。MVP 阶段确认动作由"人工审阅 + git 合并 + CI SHACL 门禁"承载（与 R6 蒸馏链路共用同一发布通道），HTTP 确认端点后置。这使 CandidateCreated → ConfirmationRecorded 事件链以最低成本先跑通语义，存储与事务留到 R8 触发条件满足时升级。

### T4 104 类本体 vs "尽可能简单"

张力：业务要求"非必要勿增类"，而 TBox 已有 104 类、76 对象属性，其中大量类服务于 SWRL 推导或从未被实例、Shape、规则引用。

消解（已拍板：**物理删减，V3.0 破坏性迁移，要做得干净**）：

- MVP Core Profile 从"视图圈定"升级为**存留判据**：进 Core（MVP 链路 + Envelope 治理 + Outcome/Domain 骨架 + Persona 最小集 + FeedbackRecord）的类保留，其余进入删除候选。
- 删除候选的保留豁免只有三条硬证据：有真实实例引用、被 SHACL/SWRL/查询计划/`roles.py` 引用且该引用本身仍被需要、属于上位本体 imports。豁免不成立即删。
- 三步链收敛（§3 方案 C）是第一刀：`StrategicChoice`、`StrategicDecision`、`selectedAs`、`decidedAs` 删除，唯一 StrategicDecision 实例迁移为 `Agreement`。
- V3.0 作为**一次性联合手术**执行：物理删减 + 分包（T1）+ MVP 链路扩展 + Agreement + FeedbackRecord 在同一个破坏性 Release 内完成，SHACL/SWRL/实例/测试同步迁移，避免多次破坏性变更。
- 迁移交付物：删除清单（含每类的豁免核查记录）、实例迁移映射、前后类数对比、全量回归证据。
- "非必要勿增"的门禁保留：新增类必须回答"进不进 Core、哪条 Competency Question 需要它"。

### T5 角色化时序访问 vs 单一 purpose 门禁

张力：R3 要求按 Agent 角色（CXO / 执行层 DRI）投影时序数据，现有 L5 只有 purpose 一个维度。

消解：`Principal` 增加 `role` 维度（Key 配置声明 `"role": "cxo" | "executor"`），时序投影作为 AdmissionPolicy 的新阶段（`temporal_projection`）在确认状态过滤之后执行。规则实现一处（应用规则层），不进 OWL、不进 SWRL、不进 Prompt——符合 AGENTS.md"同一规则唯一权威实现"。purpose 与 role 正交：purpose 决定能看哪些分区，role 决定分区内能看版本链的哪个切面。

### T6 五层文档 vs 六层公司架构

张力：仓库全部文档使用五层模型，公司架构已改用六层（Access 独立成层）。

消解：采纳六层为规范命名——它更准确，现有代码里 auth+policy 与 reasoning 本来就是两组独立模块。更新 AGENTS.md / README / runtime-architecture.md 的分层图，纯文档重构，代码零改动。旧五层的"两条贯穿治理能力"表述保留，其中 Identity/Scope 部分实体化为 L5。

### T7 "要不要用 API 提供能力"的根本质疑

分析与裁定：**API 边界应该保留，消费形态可以多样。** 保留理由：多租户隔离、审计、版本固定、认知诚实标记都要求受控边界；进程内库或直接图访问会把治理责任泄漏给调用方，违反"上层不得依赖下层存储结构"。可以增加的：在 API 之上包一层 MCP Server（工具形态：`resolve_context` / `submit_judgement` / `trace_lineage`），Agent 以工具调用而非裸 HTTP 客户端接入——这是 L6 的接入适配，不改变 L5/L4 边界。

"本体理解是否根本就错"——对照公开实践（Palantir Foundry Ontology 的对象/链接/动作模型 + 时间序列对象、企业语义层实践），"共享 TBox + 租户实例命名图 + 受控读写动作 + 版本化制品"的方向与业界一致。真正偏离常态的不是方向，是读侧先于写侧做到了这个深度（T3）。方向不需要推倒，需要再平衡。

### T8 三份文档之间的事实性 gap（v2：已读全文，推断替换为核对结果）

1. **术语三分裂**：时序图用 `Agreement`（状态 close/go_on）；本体方案主链用 `Choice / Decision`（StrategicChoice、StrategicDecision）；Glossary 的 SICO 方法用 `Strategic Choice`，且没有 Agreement 词条。同一个"战略结论落盘"环节三个名字。消解（方案 C，待最终确认）：时序图是唯一业务确认材料且只有 Agreement；Glossary 无 Strategic Decision 词条；TBox 三步链（Judgement→selectedAs→StrategicChoice→decidedAs→StrategicDecision）属过度建模（StrategicChoice 零实例、两属性零使用）。V3.0 新增 `Agreement ⊂ Decision` 并物理删除 StrategicChoice / StrategicDecision；Strategic Choice 保留为 SICO 方法论阶段用语不建类；Agreement 补进 Glossary。
2. **首个验证场景冲突**：AGENTS.md 与仓库现有实例锚定"产品 1.0 与灯塔同季交付"；本体方案 §10 与产品说明锚定"房懂懂"（渠道扩张投入 / 第 2 版产品方案讨论）。两者组织作用域不同，直接影响 R2 图矩阵与首批蒸馏材料选择，需拍板（§5 问题 3）。
3. **Persona 本体设计完备但 TBox 未实现**（R10）：本体方案 §4 + 附录 B 是三文档中最完整的静态模型，当前 TBox 只落了 4 个边缘类。静态模型实现优先级应提到与 Agreement 同级甚至更高——`personaId` 是接口一请求的第一个字段。
4. **Glossary 与 TBox 双向覆盖差**：Glossary 概念（五大上下文资产 Decision/Evidence/Artifact/Risk/Lesson、Task 明确不建类、ACT、Method Layer 1-3）部分在 TBox；反向 TBox 104 类大量不在 Glossary——印证 T4 Core Profile 的必要性。Glossary 应从 Core Profile 的 label/comment 自动导出，成为三文档共享的唯一权威词表。
5. **评分反馈机制在本体与 API 设计中完全缺席**（R11）。
6. **一致处（无需动作，双向验证）**：方案 §8.1 六组件 ≈ 现有 Runtime 组合边界；§6.3 意图识别（置信度 + alternatives + 越界先确认）≈ 现有 409 与备选匹配设计；§7 persona_context 编译 ≈ 现有 render 端点；§9 supersedes 修订链 ≈ 现有信封机制；§6.4"三种误用"批评 ≈ AGENTS.md 数据治理红线。业务设计与工程实现**架构方向高度一致，分歧集中在对象层命名与投入优先级**。

---

## 3. Judgement 版本链与 Agreement 的最小本体设计（V3.0，按拍板结果）

事实基线：`Judgement` 类已存在（⊂ `AttributedAssertion`）但全库零实例；`supersedes` 已存在（传递属性，仅 1 处使用）；TBox 现有三步链 `Judgement →selectedAs→ StrategicChoice →decidedAs→ StrategicDecision`，其中 StrategicChoice 零实例、StrategicDecision 仅 1 实例、两条属性零使用；时序图确认的流程只有两步：Judgement 版本链 → Agreement。

**方案 C（拍板方向，待最终确认）**：

- 新增 `Agreement ⊂ Decision`（Glossary 通用 Decision："我们决定"），中文 label"共识决议"。
- 物理删除 `StrategicChoice`、`StrategicDecision`、`selectedAs`、`decidedAs`；唯一 StrategicDecision 实例（`decision-ceo-agent-priority-dual-scenario-validation`）迁移为 `Agreement`；`roles.py` 类型桶同步更新。
- Glossary 的 `Strategic Choice` 保留为 SICO 方法论阶段用语，不建类——SICO 的 Choice 环节在本体中由 Judgement 版本链 + Agreement 实现（与"Task 不强化为独立本体层"同一处理哲学）。
- `Agreement` 词条补入 Glossary。

新增对象属性 4 个：

```turtle
tkos:addressesIssue    # Judgement / Agreement → StrategicIssue
tkos:adoptsJudgement   # Agreement → Judgement（被采纳的成熟版本）
tkos:producesArtifact  # StrategicResearch → Artifact（Research Result）
tkos:mandatedBy        # Mission → Agreement（go_on 授权）
```

新增数据属性 2 个：`agreementStatus`（`close|go_on`）、`signalSourceType`（`external|internal|ceo_personal`）；`StrategicIssue` 状态 `potential|confirmed` 复用既有确认状态机制承载。

复用而非新增：版本号用既有 `tkos:version`；版本链用既有 `tkos:supersedes`；Judgement 依据研究成果用既有 `tkos:supportedByEvidence` / `tkos:sourcedFrom`；战略会议轮次用 `DecisionRecord` + 既有 `confirmedBy`；Signal→Issue 用既有 `informedBy`；Research Task 指派复用既有 RoleAssignment 机制，不新增任务类。

**FeedbackRecord（已拍板新增，R11 评分反馈）**：

```turtle
tkos:FeedbackRecord ⊂ tkos:ContextAsset   # 1 类
tkos:evaluatesTarget   # FeedbackRecord → BusinessEntity（被评价的 Pack/材料/结果）
tkos:qualityScore      # xsd:integer 1–5
tkos:experienceScore   # xsd:integer 1–5
tkos:gapNote           # xsd:string，仅在存在明显差距时填写
```

FeedbackRecord 走 API 4 候选提交路径，评价人是确认主体；"是否真的变好只看下一次"由 lineage 关联同场景前后两次结果承载。

配套 SHACL（进 MVP Core Profile）：

- Judgement：必须有 `addressesIssue`、`assertedBy`、`version`、来源；被 supersede 的版本必须 `validUntil` 封口。
- Agreement：必须有 `adoptsJudgement`、`agreementStatus`、确认事件；一个 Issue 同时最多一个有效 Agreement（冲突进 ConflictSet）。
- FeedbackRecord：必须有 `evaluatesTarget` 与至少一个评分；分值 1–5 之外被拒。
- 枚举负向用例：非法 `agreementStatus` / `signalSourceType` 被拒。

时序投影规则（L5 应用规则，唯一权威实现在 `AdmissionPolicy`；executor 无 Agreement 语义已拍板为链头可见）：

```text
role=cxo      → Judgement 全版本 + supersedes 边 + Agreement 全部可见
role=executor → 存在有效 Agreement：仅 Agreement（及其 adoptsJudgement 指向版本的摘要）
                不存在 Agreement：仅版本链头（最新版，标注未落盘）
被裁剪版本    → omissions[stage=temporal_projection]，保持认知诚实
```

`TRAVERSAL` 谓词集增补 `addressesIssue`、`adoptsJudgement`、`producesArtifact`、`mandatedBy`、`evaluatesTarget`（`query_plan.py` 单一来源，版本号递增）。

Persona 包最小集（R10）单列为并行工作项：八类 + 附录 B 关系子集 + sensitive-persona 分区 SHACL，验收用方案 §4.3 波特五力案例。

---

## 4. 实施优先级（按拍板结果修订）

**P0（V3.0 联合手术 + 走通 MVP 回路）**

1. **V3.0 破坏性迁移（一次做干净）**：物理删减（T4 存留判据）+ 分包（公共层 / 企业事项包 / 个人决策包，T1/R1）+ §3 本体扩展（Agreement、4 对象属性、2 数据属性、FeedbackRecord）+ SHACL/SWRL/实例/测试同步迁移 + 同构重生成。交付删除清单、实例迁移映射、前后类数对比、全量回归证据。
2. 多租户图作用域落地（T2 第一步）+ Key 绑定 scope/role 的执行（R2/T5），含负向扩权测试。租户模型：组织级租户（词元云集、房懂懂、AIDC 各自独立 Key 与图空间；灯塔按 ADR-0001 保持跨组织协作作用域）。
3. API 4 薄写入：`POST /v1/submissions`（幂等键、SHACL 门禁、候选 trig 落盘），确认走 git+CI 通道（T3）；提交类型覆盖会议督导会后五项产出 + FeedbackRecord（R11）。
4. API 请求参数简化（R9，对齐接口一形态），API 大版本内以新增可选默认值方式兼容过渡。
5. 验收场景（已拍板：**产品 1.0 + 灯塔同季交付**）落一条完整 Signal→…→Judgement 版本链→Agreement→Mission 实例链（R4），executor/cxo 双 Key 投影验收（R3）。

**P1（消费与可读性）**

6. Persona 包最小八类实例化验证（R10；分包结构已在 P0-1 建立）。房懂懂/AIDC 作为独立租户接入时升优先级——届时"人"的材料蒸馏依赖此包。
7. 时序投影（R3）接入读路径 + lineage 端点输出版本链与反馈追溯（R11-4）。
8. render 段落序对齐 persona_context 规范（R9）；业务可读 Protégé 视图 + Glossary 从 Core Profile 导出（R1/T8-4，补 Agreement 词条）。
9. 蒸馏 CLI 流水线固化（R6），首批材料 = 验收场景既有 9 批蒸馏的规范化重放。
10. 六层架构文档重写 + 三个端点时序图（R7/R9）；MCP Server 接入层（T7，视 Agent 接入方式定）。

**P2（触发条件驱动，不主动做）**

11. RDF Store / 事务写入（R8 触发条件）。
12. API 2 服务化异步 Worker。
13. Release 发布器与图 IRI 的 `{release}` 维度。

**明确不做清单**

- 读侧渲染的进一步鲁棒性工程（client-supplied pack 路径按 R9 直接删除，不再投入加固）。
- ODRL 策略引擎、JWT/OIDC（Key 模式够用到租户 > ~10）。
- 五/六服务拆分、消息队列（方案 §8.1 的六组件是职责边界，首期仍是模块化单体）。
- 为填满类或 Shape 补造实例（AGENTS.md 红线，方案 §6.4 同样明确批评）。

---

## 5. 拍板记录（2026-08-13）

| # | 问题 | 拍板结果 |
|---|---|---|
| 1 | Agreement 承载 | **方案 C（待最终确认）**：新增 `Agreement ⊂ Decision`，物理删除 `StrategicChoice` / `StrategicDecision` / `selectedAs` / `decidedAs`。依据：时序图只有 Agreement；Glossary 无 Strategic Decision 词条；StrategicChoice 零实例、两属性零使用，三步链属过度建模 |
| 2 | executor 无 Agreement 时可见性 | **只见版本链头（最新版）**，标注未落盘；被裁剪版本进 omissions |
| 3 | MVP 验收场景 | **产品 1.0 + 灯塔同季交付**（复用既有 9 批蒸馏数据；房懂懂链路留待其租户接入） |
| 4 | 房懂懂 / AIDC 作用域形态 | **独立组织租户**（独立 Key、独立图空间）；灯塔保持 ADR-0001 跨组织协作作用域 |
| 5 | 评分反馈承载 | **新增 `FeedbackRecord` 最小类**（1 类 + evaluatesTarget + 双评分 + gapNote） |
| 6 | 类树精简力度 | **物理删减，V3.0 破坏性迁移，做干净**；Core Profile 从视图圈定升级为存留判据（T4） |

修订（2026-08-13 之后）：**T3 部分修订**——确认动作 API 化进 MVP（产品确认交互：Agent 产出候选 → 界面按钮/口头确认 → 统一写入口 submissions 承载确认（inline confirmed 或 type=confirmation 事件）→ 自动物化）。git 通道降级为冷启动批量导入专用。事务写入与物化（单写者 + append-only trig + revision 原子推进）随之进入 P0 范围。详见 `docs/mvp/03-api-minimal-design.md` §3.6。

已解决（v1 遗留问题）：个人本体边界 → 本体方案 §4 完整定义；三份飞书文档 → 已抓取入库 `业务文档/飞书快照/`。
