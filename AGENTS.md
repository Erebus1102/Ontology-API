# TKOS Ontology Runtime 协作规则

## 项目目标

本项目构建可部署的企业 Ontology Runtime。Agent、董办和项目团队通过受控 API 查询、蒸馏、解释和更新企业经营本体。

首期必须支持四类能力：

1. 根据议题或已识别意图生成版本化 Context Pack。
2. 从业务文档生成可追溯的候选实例批次。
3. 查询候选判断的来源、案例、规则、确认记录与修订链。
4. 提交 Evidence、DecisionCase、DecisionLearning 和 ContextGap，经校验与确认后进入当前有效视图。

## 已确认的架构决策

- 集团、子公司和项目使用组织作用域。集团议题可以同时展开集团共享事实、多个子公司事实、项目事实和获准的跨组织关系。
- 决策准备用途允许读取候选材料。每项候选内容必须保留 `Candidate` 标记、来源和待确认边界。
- `DecisionCase` 是聚合对象，包含议题、当时上下文、选项、Decision、Evidence、结果和 DecisionLearning。
- SWRL 保留在项目中，只承载单调、稳定、经过 Openllet 回归验证的推导。缺失判断、工作流、权限、超时和升级由应用规则处理。
- 首个端到端场景为“是否在本季度同时完成产品 1.0 上线和灯塔项目交付”。

## 五层架构

项目按五个逻辑层设计。逻辑分层不要求首期拆成五个服务；首期采用模块化单体，通过稳定契约连接各层。

```text
Layer 5  Agent & Application
         企业 Agent、董办应用、项目团队工具
                    ↓
Layer 4  Context & Reasoning Runtime
         意图解析、查询规划、推理、冲突检测、Context 编译与渲染
                    ↓
Layer 3  Ontology & Policy Model
         OWL、SHACL、SWRL、场景 Profile、策略与查询模板
                    ↓
Layer 2  Governed Knowledge Graph
         Current、Candidate、Provenance、Sensitive、Derived 命名图
                    ↓
Layer 1  Enterprise Source
         飞书、文档、会议、业务系统、人工提交与 Agent 运行记录
```

两类治理能力贯穿全部层级：

- Identity / Security / Organization Scope：身份、用途、组织、项目、敏感级别和允许动作。
- Provenance / Version / Audit / Observability：来源、有效时间、记录时间、确认、Release、调用链、日志和回执。

各层通过版本化制品或接口协作。上层不得依赖下层的存储结构、推理器命令、自由形式 SPARQL 或模型供应商接口。

## 稳定运行制品

以下四类制品构成层间稳定契约。内部技术可以替换，制品语义和兼容规则保持稳定。

### Ontology Release Package

Layer 3 向 Layer 4 发布的完整版本包，至少包含：

- `release_id`、`schema_version`、生成时间和内容哈希
- 本体模块、Ontology IRI、Version IRI 和 imports 闭包
- SHACL Shapes、SWRL 规则、场景 Profile 和查询模板
- 图清单、策略绑定、迁移说明和兼容性声明
- 构建、解析、SHACL、推理与契约测试结果

Runtime 只加载已通过发布门禁的 Release Package。每次 Context Pack 和推导结果固定其 `ontology_release_id`。

### Assertion Envelope

所有正式或候选知识使用统一断言信封，至少表达：

- `assertion_id` 与 subject / predicate / object 或等价关系对象
- 组织或项目作用域
- 当前状态和确认状态
- 有效时间、记录时间与确认时间
- 来源、原文定位、形成主体和生成 Activity
- 本体 Release、规则输入和推导方式
- 修订、替代、撤销、挑战或失效关系

业务类可以扩展断言内容，不得绕过信封中的治理字段。

### CandidateAssertionBatch

API 2 文档蒸馏与 API 4 人工/Agent 提交共用候选批次，至少包含：

- SourceSnapshot 与 ExtractionRun
- 候选断言和实体匹配结果
- 原文定位、置信说明和组织定位
- SHACL Validation Report
- 重复、冲突与 ContextGap
- 所需确认主体与后续动作

候选批次保持不可变。确认、拒绝和替代通过新事件表达。

### Context Pack

API 1 的权威结果，至少包含：

- `pack_id` 与全套版本固定信息
- query understanding、matched root 与 alternative matches
- scope resolution
- current facts 与明确标记的 candidate context
- derived claims、关联 DecisionCase 和 Proof
- conflicts、context gaps、omissions 与降级状态
- 可选 rendering 及其引用的 Pack member IDs

结构化 Context Pack 在渲染失败时仍须返回。Renderer 不得产生 Pack 中不存在的新事实。

## 运行时组合边界

Layer 4 通过能力接口组合，禁止让 API 处理器直接绑定具体数据库、推理器或 LLM SDK。

```text
IntentResolver      自然语言 → 意图、根对象和备选匹配
GraphRetriever      Query Plan → 保留图身份的事实子图
SemanticReasoner    Release + 数据图 → 单调派生与解释
ApplicationRuleEngine
                    用途门禁、状态流转、冲突、超时和升级
ConflictDetector    互斥断言、版本冲突和证据挑战
ContextCompiler     过滤后子图 → 结构化 Context Pack
ProofBuilder        派生结论 → 来源、规则和确认链
ContextRenderer     Context Pack → 可选自然语言表达
SourceAdapter       外部材料 → SourceSnapshot
ReleasePublisher    已确认事件 → Current/Derived 图与新 Release
```

每个能力接口必须满足：

- 使用领域对象作为输入输出。
- 实现可通过 Adapter 替换。
- 具有确定的超时、失败和降级语义。
- 记录输入版本、实现版本、输出哈希和调用状态。
- 具有契约测试；推理器替换还必须通过同一推导基准集。

新增子公司通常扩展 Layer 2 数据图；新增领域扩展 Layer 3 模块；新增 Agent 扩展 Layer 5 的 Purpose/Profile；替换推理器、检索器或 LLM 只替换 Layer 4 Adapter。

## 语义职责边界

- OWL 定义类、关系、继承、互斥、基数和稳定语义。
- SWRL 定义少量单调推导，发布时物化到派生图。
- SHACL 定义场景 Profile、写入门禁和数据完整性。
- SPARQL 负责确定性查询和图模式匹配。
- Intent Resolver 负责自然语言到本体对象或查询模板的映射。
- Context Compiler 负责组织、用途、时间、确认状态、相关性和预算控制。
- LLM 负责非结构化文档候选抽取、有限语义消歧和可选自然语言渲染。
- 应用规则负责权限、状态流转、确认、冲突、超时和升级。

不得在 Python、Prompt 和 SWRL 中重复维护同一条业务规则。规则必须有唯一权威实现和对应测试。

SHACL 定义位于 Layer 3，校验执行位于 Layer 4。SWRL 和 OWL 推理在 Release 发布或受影响子图更新时执行，结果物化到 Layer 2 Derived 图。在线 API 优先读取固定 Release 的已物化结果；实时推理必须显式记录原因和版本。

## 数据治理

所有正式或候选断言都必须具备：

- 稳定对象标识
- 组织或项目作用域
- 来源与原文定位
- 记录时间和有效时间
- 确认状态
- 提交或形成主体
- 本体 Release ID
- 修订、替代或失效关系

原始来源、候选断言、确认事件和修订事件保持不可变。当前有效图由这些记录物化生成。

调用方不得直接执行自由形式 SPARQL Update。所有写入经 Submission / Confirmation Action 完成，并带幂等键和审计记录。

## API 契约与兼容性

四个业务 API 保持稳定：

1. Context Pack Resolution
2. Distillation Job
3. Assertion Lineage
4. Submission / Confirmation Action

推理器、图数据库、向量索引、文档解析器和 LLM 属于内部实现，不直接暴露为 Agent 业务接口。

所有请求和响应统一携带或返回：

- `api_version`
- 对应制品的 `schema_version`
- `request_id`
- `enterprise_id` 与解析后的组织作用域
- `ontology_release_id`
- `dataset_revision`
- `policy_version`
- 涉及查询时的 `query_plan_version` 和 `as_of`

兼容规则：

- 同一 API 大版本内允许新增可选字段和新的 `extensions` 命名空间。
- 删除字段、改变字段含义、收紧合法枚举或改变默认过滤规则需要新 API/Schema 大版本。
- 服务必须校验调用方声明的版本；无法支持时返回稳定错误码和可用版本信息。
- API 响应不得泄漏内部图数据库查询、模型私有推理过程或未经授权的候选内容。
- OpenAPI/JSON Schema、示例请求、正反契约测试与实现同步更新。

API 1 的 Rendering 具有 `completed`、`degraded`、`unavailable` 状态。LLM 失败不阻断结构化 Context Pack；事实查询或硬过滤失败时不得用 LLM 补偿。

API 2 使用异步 Job。Source Adapter、解析器或 LLM 失败时保留已完成阶段、失败原因和可重试位置，不发布不完整候选批次。

API 3 返回可遍历的 Proof/Lineage 图，并区分来源支持、证据挑战、规则派生、人工确认与版本替代。

API 4 使用幂等键和乐观并发控制。确认请求必须指明候选版本和基础 `dataset_revision`，防止覆盖并发修订。

## 多组织规则

- 共享 TBox 位于 `ontology/schema`。
- 集团、子公司、项目和跨组织关系使用各自的命名图作用域。
- 组织作用域决定事实归属和确认责任，不限制集团议题跨组织查询。
- Query Scope 由 `organization_scope`、`include_descendants`、`include_projects` 和策略结果共同决定。
- 跨组织关系使用关系对象，记录双方、来源、有效时间和确认状态。
- Person 使用稳定全局标识，通过 Membership 和 RoleAssignment 进入各组织或事项。

## Context Pack 编译顺序

固定顺序如下：

1. 解析身份、用途、组织范围和查询时间。
2. 识别意图并匹配唯一根对象；保留备选匹配及分数。
3. 执行图级权限、组织、时间和确认状态硬过滤。
4. 查询当前图、溯源图和已物化派生图。
5. 展开业务允许的关系路径。
6. 检测冲突、ContextGap 和规则阻断。
7. 按相关性和 Token 预算选择成员，并记录省略原因。
8. 生成结构化 Context Pack、Proof 和可选 Rendering。

Context Pack 的结构化数据是权威结果。自然语言 Rendering 必须引用 Pack 成员 ID，不能新增 Pack 中不存在的事实。

Context Pack 的硬过滤顺序固定为身份与用途、组织作用域、图策略、有效时间、确认状态。相关性排序、案例召回和 Token 预算只处理已通过硬过滤的内容。

## 文档蒸馏规则

文档蒸馏必须经过：

```text
SourceSnapshot
  → 结构解析与原文定位
  → Ontology Profile 候选抽取
  → 实体消歧与组织定位
  → SHACL 校验
  → 重复与冲突检测
  → CandidateAssertionBatch
  → 人工确认
  → Release 发布
```

LLM 输出只能进入候选批次。无法从来源支持的字段保持为空，并生成 `ContextGap`。禁止为了填满类或 Shape 补造实例。

冷启动按场景 Profile 计算覆盖度。资料不足时返回降级 Context Pack，包含已知事实、候选材料、来源摘录、缺口、阻断推导和建议追问。

## 发布与事件链

知识更新使用不可变事件推进：

```text
CandidateCreated
  → ValidationCompleted
  → ConfirmationRecorded / CandidateRejected
  → CurrentViewMaterialized
  → DerivationCompleted
  → OntologyReleasePublished
```

每个阶段记录幂等键、输入版本、输出哈希、执行主体、时间、状态与失败原因。发布失败时保留上一有效 Release；Current 图、Derived 图与 Release 清单必须原子切换或通过可验证的发布指针切换。

事件名称表达业务事实，队列、数据库和任务框架属于可替换 Adapter。未来拆分服务时沿用同一事件 Schema。

## 项目事实边界

- `ontology/` 保存规范本体、Shape、Dataset 契约和人读视图。
- `data/instances/` 保存当前真实业务候选实例和确认事件。
- `scripts/` 保存可执行原型和维护脚本。
- `src/tkos_runtime/` 保存后续可部署服务代码。
- `tests/` 保存语义、约束、API 契约和端到端测试。
- `docs/audits/` 保存历史审计，不作为运行时真源。

当前项目已有本体、SHACL、SWRL 和本地 Context Resolver 原型。HTTP API、RDF Store、异步蒸馏 Worker、事务写入和生产权限尚未实现。文档、占位目录或单元测试不能被描述为已部署能力。

当前本体在语义上包含共享核心、经营、决策溯源和治理概念，物理上仍主要发布为单一本体文件。后续模块化必须保留稳定命名空间，为模块增加独立 Ontology IRI、Version IRI、imports、Shape/Profile 和兼容测试，同时继续生成供 Protégé 与推理器使用的合并发布制品。

## 修改与验证要求

修改本体、Shape、规则、实例或查询行为时：

1. 明确对应的 Competency Question 或 API 契约。
2. 同步检查本体、Shape、推理规则、写入映射和迁移兼容性。
3. 增加正向、缺失条件、冲突和权限负向测试。
4. 运行 SHACL、Context Pack 和 Openllet 回归。
5. 报告解析通过、约束通过、推理通过、服务集成通过和真实业务验收各自状态。

修改层间契约、API 或运行时 Adapter 时还必须：

1. 更新制品 Schema、版本和兼容性说明。
2. 运行旧客户端/新服务与新客户端/旧服务的兼容测试。
3. 验证降级路径不会扩展权限、丢失图身份或把 Candidate 提升为 Current。
4. 固定 Pack、Proof、Validation Report、Release Receipt 和失败回执作为测试证据。

保持用户已有修改。项目空间存在未确认的外部删除或脏工作树时，只修改本项目明确范围内的文件。

## 写作约定

定义应直接、清晰、可验证。质量足够时直接陈述定义，不使用“XXX 是 XXX，不是 XXX”的翻案句式。
