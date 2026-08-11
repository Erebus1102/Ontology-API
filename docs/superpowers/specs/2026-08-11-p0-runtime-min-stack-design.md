# P0-1 设计：TKOS 运行时最小只读栈

日期：2026-08-11
状态：已批准（待 spec 复审）
关联：P0-1（审查报告 `~/.claude/plans/compressed-toasting-music.md`）、AGENTS.md、`docs/architecture/runtime-architecture.md`、`docs/api/api-contracts-v1.md`

## 目标

证明 TKOS 的**只读闭环**能跑通真实数据，且**保留命名图身份**——这是当前本地原型 `scripts/resolve_issue_context.py` 的已知短板（它合并命名图）。本轮交付一个可被测试与脚本驱动的**进程内 Python 运行时**，覆盖 API 1（Context Pack）与 API 3（Assertion Lineage）。

成功标志：FE 议题「是否在本季度同时完成产品 1.0 上线和灯塔项目交付」穿过 意图解析 → 带图身份取数 → 定序硬过滤 → 结构化 Context Pack，每个成员可追溯到来源命名图；任一断言可展开可遍历的 Proof/Lineage。

## 已锁定决策

1. **RDF Store**：`rdflib.Dataset`（四元组/命名图），零新依赖，数据量（6 份 trig、数百三元组）足够；adapters 可日后替换为 Oxigraph 而不动上层契约。
2. **交付形态**：进程内库（`src/tkos_runtime/`），本轮不挂 HTTP。
3. **切片结构**：方案 A——`domain/` 能力接口 + `adapters/` rdflib 实现 + `application/` 编排，GraphRetriever 保留图身份。

## 架构（只读路径）

```text
application/   ContextPackResolver（API 1 编排）、LineageResolver（API 3 编排）
    uses ↓
domain/        能力接口 + 纯领域对象 + 硬过滤规则（框架无关）
    implemented by ↓
adapters/      rdflib 实现：RdfGraphStore、GramIntentResolver、RdfGraphRetriever、
               RdfContextCompiler、RdfProofBuilder
```

`RdfGraphStore` 包装 `rdflib.Dataset`，装载 `ontology/schema/tkos-ontology.jsonld` + `data/instances/*.trig`，**永不合并命名图**：每次取数返回带来源图的三元组/成员。

## 组件

### `domain/`（框架无关）
- `interfaces.py`：`IntentResolver`、`GraphRetriever`、`ContextCompiler`、`ProofBuilder`、`RuleEngine`（抽象基类）。
- `models.py`：`Query`、`IntentAssessment`(root, alternatives, scores)、`ContextPackMember`(subject, types, displayName, scope, **`source_graphs: list[str]`**, confirmationStatus, lifecycle, validFrom, validUntil, sources)、`ContextPack`、`Lineage`、`Omission`(entity, reason)、`HardFilterStage`(枚举)。
- `rules.py`：定序硬过滤 + `MissionReadyForAcceptance` 验收规则。**单一权威来源**——从 `tests/run_instance_conformance.py` 与原型的等价逻辑收敛而来，消除"规则在 Python 多处重复"。

### `adapters/`（rdflib）
- `rdf_store.py` → `RdfGraphStore`：装载 Dataset，提供 `quads()`、`graphs()`、按图查询；图身份在源头保留。
- `gram_intent_resolver.py` → `GramIntentResolver`：透明 2-gram + 精确子串匹配（移植自 `scripts/resolve_issue_context.py` 的 `score`/`matching_seeds`），返回排序后的根对象候选。无 embedding 依赖。
- `rdf_graph_retriever.py` → `RdfGraphRetriever`：以根对象为起点按 TRAVERSAL 谓词集做 BFS（谓词集与原型一致，单一来源），**返回带 `source_graphs` 的成员**，遍历中按 `validUntil`/`Archived` 剪枝过期项。
- `rdf_context_compiler.py` → `RdfContextCompiler`：执行定序硬过滤，分组（missions/outcomes/issues/risks/gaps/evidence/research/sources），标注 candidate vs current，记录硬过滤 omissions，组装结构化 `ContextPack`。无自然语言渲染。
- `rdf_proof_builder.py` → `RdfProofBuilder`：按断言展开来源记录、支持/挑战证据、确认事件、supersedes/revision 链 → `Lineage`。

### `application/`
- `context_pack_resolver.py` → `ContextPackResolver`：编排 API 1（resolve → retrieve → hard-filter → compile）。测试与脚本调用入口。
- `lineage_resolver.py` → `LineageResolver`：编排 API 3。

## 数据流

**API 1 Context Pack**
```text
query + purpose + as_of + organization_scope
 → GramIntentResolver           → IntentAssessment(root, alternatives)
 → RdfGraphRetriever(root)      → 带来源图的成员（BFS + valid-time 剪枝）
 → RuleEngine.hard_filter       → 定序：身份/用途 → 组织 → 图策略 → 时间 → 确认状态
 → RdfContextCompiler           → ContextPack{
       pack_id, as_of, query, purpose, matched_root, alternative_matches,
       current_facts(已确认+在有效期), candidate_context(候选,逐项标注),
       context_gaps, conflicts, omissions, proof_refs,
       admission_policy,
       ontology_release_id, dataset_revision  # v0 占位
     }
```

**API 3 Lineage**
```text
assertion_id
 → RdfGraphStore 取数 → RdfProofBuilder → Lineage{
       assertion, 当前版本与状态, 来源记录 + 原文定位,
       supporting_evidence, challenging_evidence, 关联 DecisionCase,
       ConfirmationEvent, supersedes/RevisionEvent 链
     }
```

## 硬过滤与图身份规则

- **定序硬过滤**（AGENTS.md「Context Pack 编译顺序」）：身份与用途 → 组织作用域 → 图策略 → 有效时间 → 确认状态。相关性排序与 Token 预算不在本轮（P1）。
  - **组织作用域在本轮的范围**：流水线保留该阶段并按对象已有的组织归属标注/分段，但当前实例数据未对每个对象显式打组织标签，故该阶段本轮主要起透传与占位作用；**基于调用方身份的访问控制（auth）明确不在本轮**（见"范围外"）。
- **图策略**（读侧）：`graph-confirmed-enterprise` 与 `graph-decision-provenance` 常读；`graph-candidate-and-dispute` 对 `decision_preparation` 可读；`graph-sensitive-persona` 仅授权用途；`graph-derived-context` 本轮基本为空（无物化派生图）。
- **图身份是头条正确性属性**：每个 `ContextPackMember.source_graphs` 非空；`ContextPack` 记录贡献了内容的分区集合。这是对原型合并行为的直接修复，也是端到端测试的核心断言。
- **候选处理**：`decision_preparation` 下候选成员可见、逐项保留 `Candidate`/`PreliminarilyConfirmed` 标注，**永不进入 `current_facts`**；`admission_policy` 字段声明此策略。
- **认知诚实**：可选字段缺失即留空，不补造；未知项由数据中已有的 `ContextGap` 表达。

## 错误处理

- 无匹配根对象 → 确定性错误，清晰提示（移植原型行为）。
- 硬过滤后结果为空 → 返回结构化空 Pack + 已知 gaps（降级但不抛异常）。
- 可选字段缺失 → 留空，不补造。
- Store 装载错误 → 启动即抛（fail loud）。
- **本轮无 LLM 依赖**，故无 LLM 失败/降级路径。

## 测试

- **单元**：各 adapter 对真实实例与现有夹具测试。
- **端到端契约**（`tests/test_runtime_context_pack.py`）：用 FE 议题驱动 `ContextPackResolver`，断言
  1. `matched_root` = `issue-product1-lighthouse-synchronous-delivery`；
  2. **每个成员 `source_graphs` 非空（未合并）**；
  3. `current_facts` 只含已确认+在有效期成员；候选项标注于 `candidate_context`；
  4. 三个 ContextGap（`gap-product1-lighthouse-synchronous-delivery-facts` 等）出现；
  5. `omissions` 记录硬过滤丢弃项。
- **溯源测试**（`tests/test_runtime_lineage.py`）：查已知断言，断言可遍历 Proof。
- **回归**：`make test` 保持绿；新运行时测试纳入 `test-fast` 与 CI 的 `python-tests` job。

## 本轮范围外

HTTP API、写路径（API 2 蒸馏 / API 4 提交确认）、SemanticReasoner（在线 OWL 推理，本轮 pass-through——无物化派生图可读）、NL ContextRenderer、Token 预算与相关性排序、Release Publisher、实体消歧、真实身份与组织策略强制（`organization_scope` 透传但不强制）。这些构成 P1+。

## 复用与单一来源

- TRAVERSAL 谓词集、2-gram 匹配、定序硬过滤、验收规则：均以 `scripts/resolve_issue_context.py` 与 `tests/run_instance_conformance.py` 为参照，**收敛进 `domain/rules.py` 与 adapters 的单一实现**，消除原型时代"同一规则在 Python 多处"的隐患。
- 既有 `make test` 门禁、同构守卫、conformance runner 保持不动并继续守护。
