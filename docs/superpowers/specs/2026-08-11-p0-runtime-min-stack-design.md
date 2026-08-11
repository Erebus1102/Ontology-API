# P0-1 设计：TKOS 运行时最小只读栈

日期：2026-08-11
状态：修订稿 v3（按第二轮 spec 评审 3×P1 + 2×P2 + 文字修正修订，待复审）
关联：P0-1（审查报告 `~/.claude/plans/compressed-toasting-music.md`）、AGENTS.md、`docs/architecture/runtime-architecture.md`、`docs/api/api-contracts-v1.md`

## 目标

证明 TKOS 的**只读闭环**能跑通真实数据，且**逐三元组保留命名图身份**——修复本地原型 `scripts/resolve_issue_context.py` 合并命名图的短板。本轮交付可被测试与脚本驱动的**进程内 Python 运行时**，覆盖 API 1（Context Pack）与 API 3（Assertion Lineage）。

成功标志：FE 议题「是否在本季度同时完成产品 1.0 上线和灯塔项目交付」穿过 意图解析 → 带图身份取数 → 准入判定 → 结构化 Context Pack，**每条进入 Pack 的三元组都可追溯到来源命名图，且敏感图内容永不进入 application/domain 层**；具有稳定 objectId 的断言可展开可遍历的 Lineage。

## 已锁定决策

1. **RDF Store**：`rdflib.Dataset`（四元组/命名图），零新依赖；adapters 可日后替换为 Oxigraph。
2. **交付形态**：进程内库（`src/tkos_runtime/`），本轮不挂 HTTP。
3. **切片结构**：端口与适配器（hexagonal）。

## 架构（只读路径）

```text
application/   ContextPackResolver（API 1 编排）、ContextCompiler（消费领域对象）、
               LineageResolver（API 3 编排）、ProofBuilder（组装 Proof/Lineage）
    uses ↓
domain/        models.py（领域对象）、ports.py（typing.Protocol 端口）、
               policies.py（无状态纯函数：AdmissionPolicy + 分类规则）
    implemented by ↓
adapters/      rdflib_dataset_store.py（RdfDatasetStore）、rdflib_graph_retriever.py、
               rdflib_lineage_repository.py、gram_intent_resolver.py
```

分层原则：`adapters/` 只做 RDF↔领域翻译（返回 `RetrievedMember`/`GraphStatement` 或领域查询结果）；`application/` 的 ContextCompiler/ProofBuilder **只消费领域对象，不依赖 rdflib**；`policies.py` 是纯函数；`ports.py` 用 `typing.Protocol` 定义端口，便于 Fake/Stub 测试。

## 数据流（API 1）

```text
Query(text, purpose, organization_scope, as_of)
 → AdmissionPolicy.allowed_graphs(purpose)        → allowed_graph_ids        [查询前；sensitive 永不进入]
 → GramIntentResolver.resolve(query, allowed_graph_ids)  → IntentAssessment(root, alternatives)  [只索引允许图]
 → RdfGraphRetriever.retrieve(root, allowed_graph_ids)   → RetrievedMember[]      [确定性 BFS；保留图身份；不按时间/状态删]
 → AdmissionPolicy.decide(member, purpose, as_of)        → AdmissionDecision      [逐成员；accept | omit(stage, reason)]
 → ContextCompiler(accepted, omissions, intent, scope, metadata)
                                                  → ContextPack
```

**准入两段式**：图策略在**查询前**算 `allowed_graph_ids`（敏感图内容不进入运行时内存，也不进入意图索引）；有效时间与确认状态在**查询后**由 `AdmissionPolicy.decide` 判定，产出带阶段与理由的 `Omission`。Retriever 只保留图身份与关系展开。

**Resolver 与 Retriever 都接收 `allowed_graph_ids`（修订 P1.1）**：`GramIntentResolver` 只在允许图上建索引/匹配，`RdfGraphRetriever` 只在允许图内遍历。否则敏感对象（如 fixture 中 `mission-growth informedBy assertion-sensitive`）会经匹配或双向 `informedBy` 遍历泄漏为 root/alternative/member。

API 3 Lineage：
```text
assertion_id（具有稳定 objectId 的 AttributedAssertion 或关系对象）
 → RdfLineageRepository(assertion_id, allowed_graph_ids)  → 原始四元组（带来源图）
 → ProofBuilder                                           → Lineage
```

## 查询计划（确定性，修订 P1.3）

`RdfGraphRetriever.retrieve` 实现一个固定、可复现的 BFS 计划，对应 `query_plan_version = bfs-2gram/p0-v1`：

- `direction`：incoming + outgoing（双向）
- `max_depth`：2
- `visited_key`：节点 IRI（去重）
- `predicate_set`：`TRAVERSAL`（与 `scripts/resolve_issue_context.py` 一致，单一来源）
- `graph_scope`：`allowed_graph_ids`（仅在允许图内遍历）
- `ordering`：结果按节点 IRI 稳定排序（消除 rdflib 迭代顺序的不确定性）

二层双向遍历可从 Issue 到 Mission（1 跳），再到 Confirmation 与 ContextGap（2 跳）。

## 领域模型（修订 P1.2 / P1.3 / P2.4）

```text
GraphStatement { subject, predicate, object, source_graph }   # 逐三元组图身份

RetrievedMember {                                             # Retriever 的输出
  subject,
  statements: list[GraphStatement],
  source_graphs: list[str],                                   # statements.source_graph 去重
  extracted_state: { confirmation_status, lifecycle, valid_from, valid_until, types }
}

AdmissionDecision { accept: bool, stage: HardFilterStage, reason: str|null }
Omission        { subject, stage, reason }

ContextPackMember {                                           # ContextCompiler 的输出
  id, types, display_name, scope,
  statements, source_graphs,
  confirmation_status, lifecycle, valid_from, valid_until, sources,
  admission: AdmissionDecision
}

ContextPack {
  pack_id, schema_version, as_of, query, purpose,
  matched_root, alternative_matches,
  scope_resolution,                  # enforcement=not_enforced（见准入）
  current_facts,                     # 分类规则见下
  candidate_context,
  provenance_context,                # 修订 P1.2：决策溯源图成员
  proof,                             # 修订 P1.2：确认/支持/挑战/supersedes 边
  derived_claims, reasoning_status,  # 当前 derived_claims=[] / reasoning_status=not_available
  context_gaps, conflicts, omissions,
  contributing_graphs, admission_policy,
  ontology_release_id, dataset_revision, policy_version, query_plan_version
}
```

**成员分类规则（修订 P1.2，确定性）**：
| 来源图 | 状态/时间 | 进入 |
|---|---|---|
| `graph-confirmed-enterprise` | Confirmed + 在有效期 | `current_facts` |
| `graph-candidate-and-dispute` | 允许的候选状态 | `candidate_context` |
| `graph-decision-provenance` | — | `provenance_context`（其确认/支持/挑战/supersedes 边汇入 `proof`） |
| `graph-derived-context` | — | `derived_claims`（当前为空） |
| 任一 | 被准入拒绝 | `omissions` |

（备选实现：统一 `members` + 各分区成员 ID 列表以避免内容重复；本轮采用显式分区字段，与 API 契约对齐。）

## 准入与安全策略

- **AGENTS.md 定序**：身份与用途 → 组织作用域 → 图策略 → 有效时间 → 确认状态。相关性排序与 Token 预算不在本轮（P1）。
- **图策略（查询前）**：`AdmissionPolicy.allowed_graphs(purpose)` 基于**图注册表**计算 `allowed_graph_ids`。`graph-confirmed-enterprise`、`graph-decision-provenance` 常读；`graph-candidate-and-dispute` 对 `decision_preparation` 可读；`graph-derived-context` 包含但当前为空；**`graph-sensitive-persona` 在 P0 永不进入 `allowed_graph_ids`**，因而**不进入 Resolver 索引、Retriever 遍历、application/domain 任何查询结果**。
- **时间与确认状态（查询后）**：`AdmissionPolicy.decide(member, purpose, as_of)` 依 `extracted_state` 依次判定有效时间（`valid_time` 阶段）与确认状态（`confirmation` 阶段），被拒项写 `Omission`。Policy 为纯函数，不查 RDF。
- **组织作用域（显式降级）**：P0 不做基于调用方身份的访问控制。`organization_scope` 仅用于请求回显、已有对象标注与后续兼容。Context Pack 返回：
  ```json
  "scope_resolution": {
    "requested_scope": [], "resolved_scope": [],
    "enforcement": "not_enforced",
    "reason": "instance_organization_assignment_incomplete"
  }
  ```
  输出文案不得表示"已通过组织权限过滤"；调用方传入某 purpose 不能自授敏感图访问。

## 推理处理

- **本轮不执行任何 OWL/SWRL 推理**。验收推导 `MissionReadyForAcceptance` 的权威实现是 OWL/SWRL（Openllet 验证），**不在 Python 重新计算**，避免双重权威来源（AGENTS.md:146）。
- `policies.py` 只含硬过滤与读取准入规则。
- 运行时只读已存在 Derived 图；当前为空，返回 `"reasoning_status": "not_available", "derived_claims": []`。

## 版本与可复现元数据（修订 P2.5）

- `ontology_release_id`：本体 `owl:versionInfo`（当前 `2.4.0`）。
- `dataset_revision`：对**排序后的 `data/instances/*.trig` 与 `ontology/datasets/tkos-runtime-dataset.trig`** 共同计算 SHA-256（图注册表变化会改变 allowed graphs 与分类结果，须触发新 Revision）。
- `policy_version`：固定 `read-admission/p0-v1`。
- `query_plan_version`：固定 `bfs-2gram/p0-v1`（对应上文确定性 BFS 计划）。
- `schema_version`：固定 `context-pack/1.0-draft`。

`RdfDatasetStore` 同时加载 schema、`tkos-runtime-dataset.trig`（图注册表）与实例图，通过注册表解析分区性质，**不在 Adapter 间硬编码图 IRI**。

## 错误处理

- 无匹配根对象 → 确定性错误，清晰提示。
- 准入后结果为空 → 结构化空 Pack + 已知 gaps（降级但不抛异常）。
- 可选字段缺失 → 留空，不补造。
- Store 装载错误 → 启动即抛。
- 无 LLM 依赖，故无 LLM 失败路径。

## 测试（修订 P1.1 / P1.2）

**端到端契约**（`tests/test_runtime_context_pack.py`），FE 议题驱动 `ContextPackResolver`：
1. `matched_root` 精确等于 `issue-product1-lighthouse-synchronous-delivery`。
2. **图身份**：每个成员 `source_graphs` 非空；**每条 `GraphStatement` 都有 `source_graph`**；精确验证两个已知对象归属——议题 → `graph-candidate-and-dispute`、`confirmation-mission-fe-m2-card` → `graph-decision-provenance`（后者应出现在 `provenance_context` / `proof`，不在 current/candidate）。
3. **current vs candidate vs provenance**：真实议题 Pack 中 `current_facts == []`（confirmed 图为空），`candidate_context` 非空，`Candidate`/`PreliminarilyConfirmed`/`Archived` 未泄漏到 Current；**另用既有 Context Pack 夹具**（`tests/v2.3-context-pack-runtime.trig`，含 Confirmed 对象）验证 Confirmed 对象确实进入 `current_facts`，避免空集假阳性。
4. **ContextGap**：一组必需 ContextGap（含 `gap-product1-lighthouse-synchronous-delivery-facts` 等）是返回结果的子集（不断言总数；实例共 12、二层 BFS 约可达 8）。
5. **omissions**：精确包含一个已连接的 Archived 对象和一个过期夹具项，并记录对应阶段（`confirmation` / `valid_time`）与原因。
6. **scope**：`scope_resolution.enforcement == "not_enforced"`，且 `graph-sensitive-persona` 不在 `contributing_graphs`。

**敏感图隔离测试（修订 P1.1）**：针对 `tests/v2.3-context-pack-runtime.trig`（其中 `mission-growth informedBy assertion-sensitive`）：
- 查询「一号位历史判断偏好」（`assertion-sensitive` 的显示名）**不能**匹配 `assertion-sensitive`；
- `assertion-sensitive` 不得出现在 `matched_root`、`alternative_matches`、任何 `ContextPackMember`、或任一 `GraphStatement` 的 subject/object 中；
- `graph-sensitive-persona` 不进入 Resolver 索引与 application/domain 层结果。

**溯源测试**（`tests/test_runtime_lineage.py`）：对具稳定 objectId 的 AttributedAssertion/关系对象，固定验证——断言节点、所在命名图、`SourceRecord`、`externalSourceIdentifier`、`assertedBy`、确认状态、可用支持/挑战/supersedes 边；无记录分支返回空数组。

**回归与 CI 门禁**：`make test-fast` + runtime pytest 为 P0 必过门禁；Openllet SWRL 回归为具备外部 Openllet 环境时执行的独立门禁（`openllet/` 被 `.gitignore` 排除）。

## API 3 寻址范围

API 3 接受**具有稳定 `objectId` 的 `AttributedAssertion` 或关系对象** ID。查询任意四元组需后续引入基于规范化 quad 的确定性 Statement ID（不在本轮）。

## 本轮范围外

HTTP API；写路径（API 2 / API 4）；在线 OWL/SWRL 推理（只读已存在 Derived 图并返回显式 `reasoning_status`）；NL ContextRenderer；Token 预算与相关性排序；Release Publisher；完整实体消歧；身份认证与正式组织策略。这些构成 P1+。

## 复用与单一来源

- TRAVERSAL 谓词集、2-gram 匹配：以 `scripts/resolve_issue_context.py` 为参照，收敛进 `gram_intent_resolver.py` 与 `rdflib_graph_retriever.py` 的单一实现。
- 准入策略（图注册表、时间、确认状态）与分类规则：单一权威于 `domain/policies.py`。
- 验收推导不重写：读取 OWL/SWRL 已物化结果（当前为空）。
- 既有 `make test-fast`、同构守卫、conformance runner 保持不动并继续守护。
