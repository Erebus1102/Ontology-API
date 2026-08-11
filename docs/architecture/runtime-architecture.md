# TKOS Ontology Runtime 架构基线

## 产品定位

TKOS Ontology Runtime 将企业经营事实、判断、证据、规则、组织范围和变更历史编译成 Agent 可使用的 Context Pack，并通过受控写入形成持续更新的企业经营本体。

## 运行结构

```text
Agent / 董办 / 项目团队
          │
          ▼
      Runtime API
  ┌───────┼────────┬─────────┐
  │       │        │         │
Context Distill  Lineage  Submission
  │       │        │         │
  └───────┴────┬───┴─────────┘
               ▼
        Application Services
  ┌────────────┼─────────────┐
  │            │             │
Intent      Context       Governance
Resolver    Compiler      Workflow
  │            │             │
  └────────────┼─────────────┘
               ▼
        RDF Store / Indexes
  ┌────────────┼─────────────┐
  │            │             │
Current     Provenance     Derived
Graphs      Graphs         Graphs
```

首期采用一个 API 服务、一个异步 Worker、一个 RDF Store、一个原始文档存储和一个任务审计数据库。模块保持独立契约，达到明确扩容或团队边界后再拆服务。

## 推理运行方式

- 本体 Release 发布时运行 OWL/SWRL 推理并物化派生图。
- 写入确认后对受影响子图增量重算，无法安全增量时创建新 Release 全量重算。
- API 查询读取当前 Release 的当前图和派生图。
- 应用规则实时计算缺失项、用途门禁、状态流转、冲突和升级。
- 每个 Context Pack 固定 `ontology_release_id`、`dataset_revision`、`policy_version`、`query_plan_version` 和 `as_of`。

## 组织作用域

组织范围用于归属、确认与过滤。集团战略议题可以同时覆盖集团、子公司、项目和跨组织关系。

```text
Group Organization
├── 房懂懂
├── AIDC
└── 词元云集

灯塔项目
└── OrganizationalCollaboration
    ├── 房懂懂
    ├── AIDC
    └── 词元云集
```

建议图 IRI 模板：

```text
urn:tkos:graph:{enterprise}:{scope-kind}:{scope-id}:{partition}:{release}
```

其中 `partition` 取值包括 `current`、`candidate`、`provenance`、`sensitive` 和 `derived`。

## 当前项目差距

- 当前真实实例仅存在于候选图与决策溯源图。
- 当前有效企业图和派生 Context 图为空。
- 查询原型会合并命名图，生产实现必须保留图身份。
- 当前 Python 原型重复实现部分规则，生产实现应读取权威派生图或应用规则结果。
- 尚无服务身份、组织范围、权限和 Token 预算实现。
- 尚无 RDF Store、事务提交、文档 Worker 和 Release 发布器。

这些差距构成后续实现清单，不能作为已完成能力出现在产品说明中。
