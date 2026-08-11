# TKOS Ontology Runtime

TKOS Ontology Runtime 面向企业 Agent、董办和项目团队，提供经营本体查询、业务文档蒸馏、判断溯源和受控知识更新。

当前版本包含 V2.4 OWL 本体、SHACL 约束、SWRL 推理测试、真实业务候选实例和本地 Context Resolver 原型。HTTP API、RDF Store、异步 Worker、生产身份权限与事务写入仍待实现。

## 目标能力

1. 根据议题或意图生成版本化 Context Pack。
2. 从业务文档生成可追溯的候选实例批次。
3. 查询候选判断的来源、案例、推理规则、确认记录与替代版本。
4. 受理 Evidence、DecisionCase、DecisionLearning 和 ContextGap，经校验与确认后更新当前有效视图。

完整协作与实现规则见 [AGENTS.md](AGENTS.md)。

## 五层架构

```text
Layer 5  Agent & Application
                    ↓
Layer 4  Context & Reasoning Runtime
                    ↓
Layer 3  Ontology & Policy Model
                    ↓
Layer 2  Governed Knowledge Graph
                    ↓
Layer 1  Enterprise Source
```

- Agent & Application 通过业务 API 使用 Context Pack、溯源结果和 Submission Action。
- Context & Reasoning Runtime 执行意图解析、查询规划、推理、冲突检测、Context 编译和可选渲染。
- Ontology & Policy Model 发布 OWL、SHACL、SWRL、场景 Profile 和策略定义。
- Governed Knowledge Graph 保存 Current、Candidate、Provenance、Sensitive 和 Derived 命名图。
- Enterprise Source 包括飞书、文档、会议、业务系统、人工提交和 Agent 运行记录。

身份、安全与组织作用域，以及来源、版本、审计与可观测性贯穿五层。首期采用一个 API 服务、一个异步 Worker 和一个 RDF Store，各模块通过稳定领域契约协作；未来可以按容量、故障域和团队边界拆分部署。

## 稳定制品与组合方式

运行时围绕四类版本化制品组合：

| 制品 | 用途 |
|---|---|
| `OntologyReleasePackage` | 向 Runtime 发布本体模块、Shapes、规则、Profiles、图清单和兼容信息 |
| `AssertionEnvelope` | 统一表达事实或判断及其作用域、来源、时间、确认与修订链 |
| `CandidateAssertionBatch` | 承接文档蒸馏和人工/Agent 提交的候选知识与校验结果 |
| `ContextPack` | 向 Agent 提供当前事实、候选材料、派生结论、案例、冲突、缺口和 Proof |

四个 API 保持业务语义稳定，内部推理器、图数据库、向量检索、文档解析器和 LLM 通过 Adapter 替换：

```text
API 1  Query / Intent       → ContextPack
API 2  SourceSnapshot       → CandidateAssertionBatch
API 3  Assertion ID         → Lineage / Proof Graph
API 4  Submission / Action  → Candidate / Confirmation / Release Receipt
```

结构化 Context Pack 是 API 1 的权威输出。自然语言 Rendering 可以降级或缺失，并逐项引用 Pack member ID。LLM 不可用时仍返回结构化结果。

## 项目结构

```text
Ontology-API/
├── AGENTS.md
├── pyproject.toml
├── ontology/
│   ├── schema/       OWL / JSON-LD
│   ├── shapes/       SHACL
│   ├── datasets/     命名图与运行契约
│   ├── views/        Protégé 人读制品
│   └── catalog/      本体目录
├── data/
│   └── instances/    真实业务候选实例与确认事件
├── src/tkos_runtime/
│   ├── api/
│   ├── application/
│   ├── domain/
│   └── adapters/
├── scripts/          本地原型与维护脚本
├── tests/            SHACL、Context Pack 与 Openllet 测试
└── docs/
    ├── architecture/
    ├── api/
    ├── decisions/
    ├── audits/
    └── examples/
```

## 架构文档

- [Runtime 架构基线](docs/architecture/runtime-architecture.md)
- [文档蒸馏与冷启动](docs/architecture/distillation-and-cold-start.md)
- [四个 API 契约草案](docs/api/api-contracts-v1.md)
- [组织作用域 ADR](docs/decisions/ADR-0001-organization-scope.md)
- [当前经营本体视图](docs/examples/TKOS-current-operating-view-2026-08-11.md)

## 规范制品

- `ontology/schema/tkos-ontology.jsonld` —— 人工编辑源（紧凑 @context、多语言 label）
- `ontology/schema/tkos-ontology.ttl` —— 推理器规范 Turtle，由 `scripts/export_schema_ttl.py` 从 JSON-LD 生成（保留 imports）
- `ontology/shapes/tkos-validation-shapes.jsonld`
- `ontology/datasets/tkos-runtime-dataset.trig`
- `ontology/views/tkos-ontology-protege-view.ttl` —— 去 imports 的 Protégé 浏览副本，由 `scripts/export_protege_view.py` 生成

本体命名空间为 `https://ontology.tokenking.ai/tkos#`。

`tests/run_schema_isomorphism.py` 守卫 JSON-LD ⇔ Turtle ⇔ Protégé 视图三者的同构（按结构匹配空白节点），编辑任一后用 `make generate` 重生成派生制品，否则同构测试会失败。

当前共享核心、经营、决策溯源和治理模块主要保存在同一本体发布文件中。后续将为模块建立独立 Ontology IRI、Version IRI、imports、Shape/Profile 和兼容测试，并继续生成合并制品供 Protégé 与推理器使用。

## 真实实例状态

现有实例来自 FE Mission Card、Week 1 复盘、产品 1.0 更新、CEO Agent 场景及房懂懂材料。当前实例位于候选事实图与决策溯源图；当前有效企业图和派生 Context Pack 图尚未物化。

决策准备用途允许读取候选材料，输出必须逐项保留确认状态。正式执行与 Mission 验收使用已确认且当前有效的内容。

## 当前工程边界

已经具备：

- V2.4 OWL/JSON-LD 本体和 Protégé 视图
- SHACL 正向与负向约束测试
- Openllet SWRL 验收推导测试
- RDF Dataset 命名图契约
- 真实业务候选实例和本地议题 Resolver 原型

仍待实现：

- Ontology Release Package Manifest 与四类制品的 JSON Schema
- 保留命名图身份的生产 GraphRetriever
- HTTP API、服务身份、组织策略和 Token 预算
- RDF Store、异步蒸馏 Worker、事务写入与发布指针
- Reasoning Runtime 能力接口及 Adapter
- API 兼容、故障降级、权限和真实业务端到端测试

实现顺序：

1. 固定 Release Package、Assertion、Candidate Batch 和 Context Pack Schema。
2. 为 IntentResolver、GraphRetriever、SemanticReasoner、ContextCompiler、ProofBuilder 和 Renderer 建立接口。
3. 实现 API 1 的结构化 Context Pack 闭环，保留图身份和全部版本信息。
4. 实现 API 2 与 API 4 共用的候选、校验、确认和发布事件链。
5. 实现 API 3 的来源、规则、确认和修订 Proof 图。
6. 通过首个真实议题完成跨组织、候选材料、降级与溯源验收。

## 本地验证

安装 Python 依赖：

```bash
python3 -m pip install -e '.[dev]'
```

聚合运行（推荐）。`make test-fast` 跑四个纯 Python 套件，`make test` 在此基础上追加 Openllet SWRL 验收（首次需 Maven 构建 Openllet CLI）：

```bash
make test-fast    # SHACL + Context Pack + 实例一致性 + 模式同构
make test         # 上述 + Openllet SWRL 验收
make generate     # 从 JSON-LD 重生成 Turtle 与 Protégé 视图派生制品
```

单独运行各套件：

```bash
python3 tests/run_v2_3_shacl.py              # SHACL 正负向用例
python3 tests/run_v2_3_context_pack.py       # Context Pack 读侧过滤
python3 tests/run_instance_conformance.py    # 真实实例硬门禁 + 夹具可见性
python3 tests/run_schema_isomorphism.py      # JSON-LD ⇔ Turtle ⇔ Protégé 视图同构守卫
python3 tests/run_v2_3_swrl_openllet.py      # Openllet SWRL 验收推导
```

`run_instance_conformance.py` 把 `data/instances/*.trig` 合并为生产式装载图并硬断言 SHACL 合规；测试夹具的违例按 `by-design / read-side / legacy` 分类输出，仅作可见性提示。

GitHub Actions（`.github/workflows/ci.yml`）在推送与 PR 时自动运行纯 Python 套件（必过门禁），SWRL 套件作为信息性 job。

运行真实议题查询原型：

```bash
python3 scripts/resolve_issue_context.py \
  --query '是否在本季度同时完成产品 1.0 上线和灯塔项目交付'
```

该脚本用于验证匹配与关系展开。生产实现必须保留命名图身份、组织范围、策略结果、Release 和省略记录。
