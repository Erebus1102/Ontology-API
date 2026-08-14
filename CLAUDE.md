# TKOS Ontology Runtime 协作规则

> 本文件是 Agent 协作的权威工作规则，随会话加载。**MVP 设计权威是 `docs/mvp/01-04`**（统一语言 / 本体 V3.0 / API v1 / 2.0 基座迭代）；本文件与其冲突时以 `docs/mvp` 为准并回改本文件。

## 项目目标与当前状态

构建可部署的企业 Ontology Runtime，支撑一号位 Agent 走完战略闭环：`Signal → Issue → Research → Judgement 版本链 → Agreement → Mission`，每环可提交、可确认、可追溯、可反馈。MVP 验收载体是**产品 1.0 + 灯塔同季交付**（验收清单见 `docs/mvp/01` §6）。

**当前进度（Runtime 2.0 基座完成，分支 `runtime-2.0-foundation`，tag `pre-v3.0-surgery` 为手术前回退基线；待合并部署，main 仍为 1.0/P1.1 已部署状态）：**

- ✅ **V3.0 本体手术（A）**：`Agreement`/`FeedbackRecord`/`Product` 落地，`StrategicChoice`/`StrategicDecision`/`OperatingDecision` + `selectedAs`/`decidedAs` 物理删除；SHACL/SWRL/query_plan/roles 全链对齐（类数 104 → 104）。删除清单与迁移映射见 `docs/superpowers/plans/runtime-2.0-artifacts/`。
- ✅ **Key 模型（C）**：`Principal{tenant, role(cxo|executor), on_behalf_of, confirmer, default_scenario}`；`TKOS_API_KEYS_JSON`；跨租户 `scopes: []` → 404（不泄漏存在性）。
- ✅ **v1 契约收敛（B）**：resolve 增 `scenario`/`render:true`/`token_budget`；purpose 由 scenario/Key default 推导；版本固定块 + `request_id` 中间件；旧字段（`enterprise_id`/`organization_scope`/`purpose`/`actor_id`/`persona_id`、独立 `:render`）标 deprecated、过渡期仍接受（不 422），物理删除在迭代 1。
- ✅ 读路径：`POST /v1/context-packs:resolve`（P1.1 起 409 歧义 `type`+`matched_evidence` / 404 候选建议 / `intent_facets`；v1 起 `render:true` 并入、版本块齐备）；运维 `GET /health` `/ready` `/version`；authN（Bearer）+ authZ（purpose 门禁 + Key 作用域推导）。
- ✅ 契约同步：`docs/api/tkos-runtime-openapi.yaml`（v0.2.0，deprecated 标注）+ Apifox 项目 `8708985`（AI 分支，17 用例 v1 双轨 + 指南文档 v1 收敛）。
- ⏳ 待实现：`lineage` 端点（迭代 1，含旧字段物理删除）、`submissions` 写入闭环（迭代 2）、在线推理、异步蒸馏 Worker、生产 RDF Store 替换、真实 Agent 端到端联调、Persona 个人决策本体包。

> 文档、占位目录或单元测试不得被描述为已部署能力。当前能力以本节"✅"项为准。

## 已确认的架构决策

- **本体收敛到 V3.0 核心集**（`docs/mvp/02`）：约 47 类，非必要不增类；`Agreement` 是唯一战略结论落盘类（`StrategicChoice`/`StrategicDecision` 物理删除）；Task 用 `RoleAssignment`、会议用 `DecisionRecord`、决策不作本体类。
- **API 收敛到 v1**（`docs/mvp/03`）：3 业务端点（resolve / lineage / submissions）+ 3 运维端点，不再多。薄请求、厚响应；**Key 即租户/角色/Persona 锚点**，作用域由 Key 推导（请求不带 `enterprise_id`/`purpose`/`persona_id`）。
- **四段式写入**：一切写入先候选、后确认、再物化；调用方不得直接写当前有效视图。
- **认知诚实**：`omissions` / `context_gaps` 必须如实返回；LLM 失败不阻断结构化结果；事实查询失败不得用 LLM 补偿；禁止为填满类或 Shape 补造实例。
- **SWRL** 只承载单调、稳定、经 Openllet 回归验证的推导；缺失判断、工作流、权限、超时、升级由应用规则处理。
- **慢变客观事实**（宪法/公司现实/产品/方法簇）走蒸馏 + git 通道，不进 submissions 高频路径。
- 首个端到端场景为"是否在本季度同时完成产品 1.0 上线和灯塔项目交付"。

## 五层架构

模块化单体，通过稳定契约连接各层（逻辑分层不等于服务拆分）。

```text
Layer 5  Agent & Application        企业 Agent、董办应用、项目团队工具
Layer 4  Context & Reasoning Runtime 意图解析、查询规划、推理、冲突检测、Context 编译与渲染
Layer 3  Ontology & Policy Model     OWL、SHACL、SWRL、场景 Profile、策略与查询模板
Layer 2  Governed Knowledge Graph    Current、Candidate、Provenance、Sensitive、Derived 命名图
Layer 1  Enterprise Source           飞书、文档、会议、业务系统、人工提交与 Agent 运行记录
```

两类治理贯穿全层：**Identity/Security/Organization Scope** 与 **Provenance/Version/Audit/Observability**。上层不得依赖下层的存储结构、推理器命令、自由形式 SPARQL 或模型供应商接口。

## 稳定运行制品

层间稳定契约，内部技术可替换、制品语义与兼容规则保持稳定。

| 制品 | 用途 | 状态 |
|---|---|---|
| `OntologyReleasePackage` | 向 Runtime 发布本体模块/Shape/规则/Profile/图清单/兼容信息 | TBox 已发；Release Package Manifest 待补 |
| `AssertionEnvelope` | 统一表达事实或判断及其作用域/来源/时间/确认/修订 | 断言信封字段在模型中落地 |
| `CandidateAssertionBatch` | 承接蒸馏与提交的候选知识 + 校验结果 | 待实现（submissions） |
| `ContextPack` | API 1 权威结果：current/candidate/derived/proof/gaps/omissions + 可选 rendering | ✅ 已实现 |

`Context Pack` 的结构化数据是权威结果；`Rendering` 只引用 Pack 成员 ID、不产生新事实；渲染失败时 `degraded/unavailable`，结构化 Pack 照常返回。

## 运行时组合边界

Layer 4 通过能力接口组合；API 处理器不得直接绑定具体数据库、推理器或 LLM SDK。

```text
IntentResolver      自然语言 → 意图、根对象、备选匹配        ✅ GramIntentResolver
GraphRetriever      Query Plan → 保留图身份的事实子图          ✅ RdfGraphRetriever
SemanticReasoner    Release + 数据图 → 单调派生与解释          ⏳ 离线 Openllet；在线待实现
ApplicationRuleEngine 用途门禁/状态流转/冲突/超时/升级          ⏳
ConflictDetector    互斥断言、版本冲突、证据挑战                ⏳
ContextCompiler     过滤后子图 → 结构化 Context Pack           ✅
ProofBuilder        派生结论 → 来源/规则/确认链                 ⏳
ContextRenderer     Context Pack → 可选自然语言表达             ✅ DecisionContextCompiler
SourceAdapter       外部材料 → SourceSnapshot                   ⏳（蒸馏 CLI）
ReleasePublisher    已确认事件 → Current/Derived 图与新 Release ⏳（submissions）
```

每个能力接口：领域对象出入参；实现可经 Adapter 替换；确定的超时/失败/降级语义；记录输入/实现/输出版本与调用状态；具备契约测试（推理器替换须过同一推导基准集）。

## 语义职责边界

- **OWL** 定义类、关系、继承、互斥、基数、稳定语义。
- **SWRL** 定义少量单调推导，发布时物化到派生图。
- **SHACL** 定义场景 Profile、写入门禁、数据完整性（Layer 3 定义、Layer 4 校验）。
- **SPARQL** 确定性查询与图模式匹配。
- **IntentResolver** 自然语言→本体对象/查询模板。
- **ContextCompiler** 组织、用途、时间、确认状态、相关性、预算控制。
- **LLM** 非结构文档候选抽取、有限语义消歧、可选自然语言渲染。
- **应用规则** 权限、状态流转、确认、冲突、超时、升级。

不得在 Python、Prompt、SWRL 中重复维护同一条业务规则——规则必须有唯一权威实现与对应测试。

## 数据治理

所有正式或候选断言必须具备：稳定对象标识、组织/项目作用域、来源与原文定位、记录/有效时间、确认状态、提交或形成主体、本体 Release ID、修订/替代/失效关系。原始来源、候选断言、确认事件、修订事件保持不可变；当前有效图由这些记录物化生成。调用方不得直接执行自由形式 SPARQL Update；所有写入经 submissions / 确认动作完成，带幂等键与审计记录。

## API 契约与兼容性

**三个业务端点 + 三个运维端点**（`docs/mvp/03` §1，不再多）：

| 端点 | 功能 | 状态 |
|---|---|---|
| `POST /v1/context-packs:resolve` | 议题→结构化 Context Pack；`scenario`/`render:true`/`token_budget` v1 形态 + 版本块 | ✅（v1 收敛 2.0 基座） |
| `GET /v1/assertions/{id}/lineage` | 断言→版本/来源/确认/挑战/反馈图 | ⏳ 迭代 1 |
| `POST /v1/submissions` | 唯一写入口：候选断言 + 确认/拒绝事件 | ⏳ 迭代 2 |
| `GET /health` `/ready` `/version` | 运维 | ✅ |

**契约权威**：`docs/api/tkos-runtime-openapi.yaml`（可执行 OpenAPI）+ Apifox 项目 `8708985`。`docs/api/api-contracts-v1.md` 与 `context-pack-render-api.md` 为历史草案（已标过时）。

**认证（Key 注册表，2.0 基座已落地）**：`Authorization: Bearer <key>`。`Principal{name, allowed_purposes, allowed_scopes, tenant, role(cxo|executor), on_behalf_of, confirmer, default_scenario}`（单值 `TKOS_API_KEY` 碰撞时优先）。`purpose`/作用域由 Key + scenario 推导（显式旧字段 `purpose` 过渡期仍优先），消除扩权面。

**版本固定块**（v1 收敛起响应统一携带）：`api_version=v1` / `request_id`（响应头 `X-Request-ID` 回显）/ `ontology_release{company, persona:null}` / `dataset_revision`（当前全局哈希，per-tenant 随 submissions 落地）/ `policy_version` / `query_plan_version`。

**错误语义**：401 未认证；403 无确认权；404 无匹配/不可见（知识不可见即不存在，不泄漏存在性）；409 意图歧义（返回 `alternatives`/`candidates`）；422 SHACL 校验失败（附 validation report）。

**兼容规则**：同大版本内允许新增可选字段与新 `extensions` 命名空间；删字段/改含义/收紧枚举/改默认过滤需新大版本；服务须校验调用方版本，无法支持时返回稳定错误码与可用版本；响应不得泄漏内部查询、私有推理或未授权候选内容。移除 `enterprise_id`/`organization_scope`/`purpose`/`actor_id`/`persona_id` 与独立 `:render` 端点：2.0 基座已实施 deprecated 过渡（旧字段仍接受、仅警告），**物理删除在迭代 1（Lineage）执行**，届时旧字段直接 422。

## Context Pack 编译顺序（固定）

1. 解析身份、用途、组织范围、查询时间。
2. 识别意图并匹配唯一根对象；保留备选匹配与分数。
3. 图级权限、组织、时间、确认状态硬过滤。
4. 查询当前图、溯源图、已物化派生图。
5. 展开业务允许的关系路径。
6. 检测冲突、ContextGap、规则阻断。
7. 按相关性与 Token 预算选成员，记录省略原因。
8. 生成结构化 Context Pack、Proof、可选 Rendering。

硬过滤顺序固定：身份与用途 → 组织作用域 → 图策略 → 有效时间 → 确认状态。相关性排序、案例召回、Token 预算只处理已通过硬过滤的内容。

## 文档蒸馏规则

蒸馏**不是 API**（收原始文档、需解析/抽取/消歧、低频批量异步；MVP 为 CLI 流水线）。流程：`SourceSnapshot → 结构解析/原文定位 → Profile 候选抽取 → 实体消歧/组织定位 → SHACL 校验 → 重复/冲突检测 → CandidateAssertionBatch → 人工确认 → Release 发布`。LLM 输出只能进候选批次；来源无法支持的字段保持为空并生成 `ContextGap`。冷启动按场景 Profile 算覆盖度，资料不足返回降级 Pack。

## 发布与事件链

知识更新用不可变事件推进：`CandidateCreated → ValidationCompleted → ConfirmationRecorded/CandidateRejected → CurrentViewMaterialized → DerivationCompleted → OntologyReleasePublished`。每阶段记幂等键、输入版本、输出哈希、执行主体、时间、状态、失败原因。发布失败保留上一有效 Release；Current 图、Derived 图、Release 清单必须原子切换或经可验证发布指针切换。事件名表达业务事实，队列/数据库/任务框架属可替换 Adapter。

## 项目事实边界

```text
docs/mvp/            MVP 权威设计（01 统一语言 / 02 本体 V3.0 / 03 API v1 / 04 2.0 基座迭代）
docs/api/            OpenAPI 契约（权威）+ 历史草案（过时）
docs/architecture/   架构与部署设计
docs/decisions/      ADR
docs/audits/         历史审计（非运行时真源）
docs/examples/       人读经营视图与蒸馏示例
ontology/            规范本体（schema/shapes/datasets/views/catalog）
data/instances/      真实业务候选实例与确认事件
src/tkos_runtime/    可部署服务代码（api/application/domain/adapters）
tests/               语义、约束、API、端到端测试（197 pytest + 5 门禁脚本 + Openllet）
scripts/             原型与维护脚本
deploy/ecs/          ECS 单节点部署（systemd + docker-run）
```

`ontology/schema/tkos-ontology.jsonld` 为人工编辑源；`tkos-ontology.ttl` 与 `views/tkos-ontology-protege-view.ttl` 为派生制品（`make generate` 重生成）。`tests/run_schema_isomorphism.py` 守卫 JSON-LD ⇔ Turtle ⇔ Protégé 视图三者同构。

## 修改与验证要求

修改本体/Shape/规则/实例/查询行为时：

1. 明确对应的 Competency Question 或 API 契约。
2. 同步检查本体、Shape、推理规则、写入映射、迁移兼容性。
3. 增加正向、缺失条件、冲突、权限负向测试。
4. 运行 SHACL、Context Pack、Openllet 回归（`make test`）。
5. 报告解析/约束/推理/集成/业务验收各自状态。

修改层间契约、API 或 Adapter 时还必须：更新制品 Schema/版本/兼容说明；跑新旧兼容测试；验证降级不扩权、不丢图身份、不把 Candidate 提升为 Current；固定 Pack/Proof/Validation Report/Release Receipt/失败回执为测试证据。

## 工作约定

- **Think before coding**：先陈述假设，不确定就问；多解先呈现不默选；有更简方案直说。
- **Surgical changes**：只动必须动的；不顺手"改进"相邻代码；匹配既有风格；发现无关死代码只提示不删；每行改动都能追溯到需求。
- **Goal-driven**：把任务转成可验证目标（先写复现/失败测试，再修到通过）；多步任务先给"步骤→验证点"计划。
- **诚实报告**：测试失败就如实报输出；跳过的步骤直说；完成且经验证才平铺直叙，不夸大不对冲。
- **保持用户已有修改**：工作树存在未确认的外部删除/脏状态时，只改本项目明确范围内的文件。
- **不提交敏感**：`.env`、API Key、ECS 凭据、Apifox token 永不写入仓库；仅按显式 `git add <paths>` 暂存。
