# P0-1 设计：TKOS 运行时最小只读栈

日期：2026-08-11
状态：修订稿 v2（按 spec 评审 4×P1 + 4×P2 修订，待复审）
关联：P0-1（审查报告 `~/.claude/plans/compressed-toasting-music.md`）、AGENTS.md、`docs/architecture/runtime-architecture.md`、`docs/api/api-contracts-v1.md`

## 目标

证明 TKOS 的**只读闭环**能跑通真实数据，且**逐三元组保留命名图身份**——修复本地原型 `scripts/resolve_issue_context.py` 合并命名图的短板。本轮交付可被测试与脚本驱动的**进程内 Python 运行时**，覆盖 API 1（Context Pack）与 API 3（Assertion Lineage）。

成功标志：FE 议题「是否在本季度同时完成产品 1.0 上线和灯塔项目交付」穿过 意图解析 → 带图身份取数 → 准入判定 → 结构化 Context Pack，**每条进入 Pack 的三元组都可追溯到来源命名图**；具有稳定 objectId 的断言可展开可遍历的 Lineage。

## 已锁定决策

1. **RDF Store**：`rdflib.Dataset`（四元组/命名图），零新依赖；adapters 可日后替换为 Oxigraph 而不动上层契约。
2. **交付形态**：进程内库（`src/tkos_runtime/`），本轮不挂 HTTP。
3. **切片结构**：端口与适配器（hexagonal）——`domain/` 端口与纯策略、`application/` 用例编排、`adapters/` rdflib 实现。

## 架构（只读路径）

```text
application/   ContextPackResolver（API 1 编排）、ContextCompiler（消费领域对象）、
               LineageResolver（API 3 编排）、ProofBuilder（组装 Proof/Lineage）
    uses ↓
domain/        models.py（领域对象）、ports.py（typing.Protocol 能力端口）、
               policies.py（纯函数准入策略）
    implemented by ↓
adapters/      rdflib_dataset_store.py、rdflib_graph_retriever.py、
               rdflib_lineage_repository.py、gram_intent_resolver.py
```

分层原则（修订 P2.5）：`adapters/` 只负责 RDF↔领域对象的翻译（返回 `GraphStatement` 或领域查询结果）；`application/` 的 ContextCompiler/ProofBuilder **只消费领域对象，不依赖 rdflib**；`policies.py` 的 `AdmissionPolicy` 是无状态纯函数。`ports.py` 用 `typing.Protocol` 定义端口，便于 Fake/Stub 测试。

## 数据流（API 1）

```text
Query(text, purpose, organization_scope, as_of)
 → AdmissionPolicy.allowed_graphs(purpose)        → allowed_graph_ids        [查询前；敏感图不进入内存]
 → GramIntentResolver(query)                      → IntentAssessment(root, alternatives)
 → RdfGraphRetriever(root, allowed_graph_ids)     → GraphStatement[]          [BFS over TRAVERSAL；保留图身份；不按时间/状态删]
 → AdmissionPolicy.decide(statements, purpose, as_of) → AdmissionDecision[]   [accept | omit(stage, reason)]
 → ContextCompiler(accepted, omissions, scope, intent, metadata)
                                                  → ContextPack
```

**准入两段式（修订 P1.1）**：图策略在**查询前**执行（生成 `allowed_graph_ids`，敏感图内容不进入运行时内存）；有效时间与确认状态在**查询后**由 `AdmissionPolicy.decide` 判定，**产出带阶段与理由的 `Omission`**。Retriever 只保留图身份与关系展开，不做任何时间/状态删除——因此被准入拒绝的成员都能进入 `omissions`。

API 3 Lineage：
```text
assertion_id（具有稳定 objectId 的 AttributedAssertion 或关系对象）
 → RdfLineageRepository(assertion_id)  → 原始四元组（带来源图）
 → ProofBuilder                         → Lineage
```

## 领域模型（修订 P1.3）

```text
GraphStatement
├── subject, predicate, object        # RDF 项
└── source_graph: str                 # 该三元组的来源命名图 IRI

ContextPackMember
├── id, types, display_name, scope
├── statements: list[GraphStatement]  # 该成员的全部三元组，逐条带图
├── source_graphs: list[str]          # statements.source_graph 的去重汇总
├── confirmation_status, lifecycle, valid_from, valid_until, sources
└── admission: AdmissionDecision

AdmissionDecision { accept: bool, stage: HardFilterStage, reason: str|null }
Omission        { subject, stage, reason }
ContextPack     { pack_id, schema_version, as_of, query, purpose,
                  matched_root, alternative_matches,
                  scope_resolution,            # 见下
                  current_facts, candidate_context,
                  context_gaps, conflicts, omissions,
                  derived_claims, reasoning_status,   # 见下
                  contributing_graphs, admission_policy,
                  ontology_release_id, dataset_revision, policy_version, query_plan_version }
```

**图身份是头条正确性属性（修订 P1.3）**：成员级 `source_graphs` 只是必要不变量；只有**逐条 `GraphStatement.source_graph`** 才能证明"类型/状态/来源/确认关系来自哪张图"，防止"先合并再统一补一个图 ID"的伪通过。

## 准入与安全策略（修订 P1.1 / P1.4）

- **AGENTS.md 定序**：身份与用途 → 组织作用域 → 图策略 → 有效时间 → 确认状态。相关性排序与 Token 预算不在本轮（P1）。
- **图策略（查询前）**：由 `AdmissionPolicy.allowed_graphs(purpose)` 基于**图注册表**计算 `allowed_graph_ids`。`graph-confirmed-enterprise` 与 `graph-decision-provenance` 常读；`graph-candidate-and-dispute` 对 `decision_preparation` 可读；`graph-derived-context` 包含但当前为空；**`graph-sensitive-persona` 在 P0 永不出现在 `allowed_graph_ids`**。
- **时间与确认状态（查询后）**：`AdmissionPolicy.decide` 依次判定有效时间（`as_of`）与确认状态，被拒项写入 `Omission(stage, reason)`。
- **候选处理**：`decision_preparation` 下候选成员可见、逐项保留 `Candidate`/`PreliminarilyConfirmed` 标注，**永不进入 `current_facts`**；`admission_policy` 字段声明此策略。
- **组织作用域（显式降级，修订 P1.4）**：P0 不做基于调用方身份的访问控制（auth 不在本轮）。`organization_scope` 仅用于请求回显、已有对象标注与后续接口兼容。Context Pack 必须返回：
  ```json
  "scope_resolution": {
    "requested_scope": [], "resolved_scope": [],
    "enforcement": "not_enforced",
    "reason": "instance_organization_assignment_incomplete"
  }
  ```
  输出文案**不得**表示"已通过组织权限过滤"。调用方传入某个 `purpose` **不能**自行获得敏感图访问能力。

## 推理处理（修订 P1.2）

- **本轮不执行任何 OWL/SWRL 推理**。验收推导 `MissionReadyForAcceptance` 的权威实现是 OWL/SWRL（Openllet 四组用例验证），**不在 Python 中重新计算**，避免双重权威来源（违反 AGENTS.md:146）。
- `domain/policies.py` 只保存硬过滤与读取准入规则。
- 运行时**只读取已存在的 Derived 图**；当前 Derived 图为空，故返回显式状态：
  ```json
  "reasoning_status": "not_available", "derived_claims": []
  ```

## 版本与可复现元数据（修订 P2.8）

不使用模糊占位；本轮低成本生成真实值：
- `ontology_release_id`：读取本体 `owl:versionInfo`（当前 `2.4.0`）。
- `dataset_revision`：对排序后的 `data/instances/*.trig` 内容计算 SHA-256。
- `policy_version`：固定 `read-admission/p0-v1`。
- `query_plan_version`：固定 `bfs-2gram/p0-v1`。
- `schema_version`：固定 `context-pack/1.0-draft`。

`RdfGraphStore` 同时加载 `ontology/datasets/tkos-runtime-dataset.trig`，通过**图注册表**解析分区性质（哪张图敏感、用途许可等），**不在多个 Adapter 中硬编码图 IRI**。

## 错误处理

- 无匹配根对象 → 确定性错误，清晰提示。
- 准入后结果为空 → 返回结构化空 Pack + 已知 gaps（降级但不抛异常）。
- 可选字段缺失 → 留空，不补造（认知诚实）。
- Store 装载错误 → 启动即抛（fail loud）。
- **本轮无 LLM 依赖**，故无 LLM 失败/降级路径。

## 测试（修订 P2.6）

**端到端契约**（`tests/test_runtime_context_pack.py`），FE 议题驱动 `ContextPackResolver`：
1. `matched_root` 精确等于 `issue-product1-lighthouse-synchronous-delivery`。
2. **图身份**：每个成员 `source_graphs` 非空；**每条 `GraphStatement` 都有 `source_graph`**；并精确验证两个已知对象归属——议题 → `graph-candidate-and-dispute`、`confirmation-mission-fe-m2-card` → `graph-decision-provenance`。
3. **current vs candidate**：真实议题 Pack 中 `current_facts == []`（confirmed 图为空），`candidate_context` 非空，且 `Candidate`/`PreliminarilyConfirmed`/`Archived` 均未泄漏到 Current。**另用既有 Context Pack 夹具**（`tests/v2.3-context-pack-runtime.trig`，含 Confirmed 对象）验证 Confirmed 对象确实能进入 Current，避免空集假阳性。
4. **ContextGap**：一组必需 ContextGap（含 `gap-product1-lighthouse-synchronous-delivery-facts` 等）是返回结果的**子集**（不断言总数；实例中 ContextGap 共 12 个、二层 BFS 约可达 8 个）。
5. **omissions**：精确包含一个已连接的 Archived 对象和一个过期夹具项，并记录对应过滤阶段（`valid_time` / `confirmation`）与原因。
6. **scope_resolution.enforcement == "not_enforced"`，且 `graph-sensitive-persona` 不在 `contributing_graphs` 集合中。**

**溯源测试**（`tests/test_runtime_lineage.py`）：对具有稳定 objectId 的 AttributedAssertion 或关系对象，固定验证——断言节点、所在命名图、`SourceRecord`、`externalSourceIdentifier`、`assertedBy`、确认状态、可用的支持/挑战/supersedes 边；无记录分支返回空数组。

**回归与 CI 门禁（修订 CI 说明）**：
- `make test-fast` + 新 runtime pytest 测试构成 P0 必过门禁。
- Openllet SWRL 回归作为**具备外部 Openllet 环境时**执行的独立门禁（`openllet/` 被 `.gitignore` 排除，干净 clone 中不存在，`make test` 在 CI 不可依赖）。

## API 3 寻址范围（修订 P2.7）

API 3 接受**具有稳定 `objectId` 的 `AttributedAssertion` 或关系对象** ID。当前实例只为部分对象建立稳定 ID，大量 RDF 三元组无独立断言 ID；查询任意四元组需后续引入基于规范化 quad 的确定性 Statement ID（不在本轮）。

## 本轮范围外

HTTP API；写路径（API 2 蒸馏 / API 4 提交确认）；**在线 OWL/SWRL 推理**（本轮不执行推理，只读取已存在 Derived 图并返回显式 `reasoning_status`）；NL ContextRenderer；Token 预算与相关性排序；Release Publisher；完整实体消歧；身份认证与正式组织策略。这些构成 P1+。

## 复用与单一来源

- TRAVERSAL 谓词集、2-gram 匹配：以 `scripts/resolve_issue_context.py` 为参照，收敛进 `gram_intent_resolver.py` 与 `rdflib_graph_retriever.py` 的单一实现。
- 准入策略（图注册表、时间、确认状态）：单一权威实现于 `domain/policies.py`。
- **验收推导不重写**：读取 OWL/SWRL 已物化结果（当前为空）。
- 既有 `make test-fast`、同构守卫、conformance runner 保持不动并继续守护。
