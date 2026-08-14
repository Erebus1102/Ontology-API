# V3.0 手术删除清单（Task A3 交付物）

> 本文件是 Runtime 2.0 基座 Task A3 的审计落盘制品（Execution Discipline 2）。逐项记录被删术语的实例数 / SHACL / SWRL / query_plan / roles.py 引用与裁定，供 INT 与后续任务消费，不靠会话记忆。
>
> 权威依据：`docs/superpowers/plans/2026-08-13-runtime-2.0-foundation.md` Task A3 审计块 + Spec Reconciliation #8。

## 执行摘要

A3 物理删除 5 个声明（3 个 owl:Class + 2 个 owl:ObjectProperty），全部位于 `ontology/schema/tkos-ontology.jsonld`（人工编辑源）。派生制品 `tkos-ontology.ttl` 与 `views/tkos-ontology-protege-view.ttl` 经 `make generate` 自动同步。删除前 A4 已迁移唯一 `StrategicDecision` 实例 → `Agreement`，故本轮删除零孤儿。

类数变化：104（V2.4.1 `bce5ab8` 基线）− 3 删 + 3 增（A1）= **104 具名类**。

> **类数口径**：`owl:Class` 具名声明数——`tkos-ontology.jsonld` @graph 中带 `@id` 且 `@type: owl:Class` 的节点；属性 domain/range 内嵌套的匿名 unionOf 闭包不计。基线（`bce5ab8`）与当前均实测为 **104**（含 3 个无 `rdfs:subClassOf` 的顶层类：`BusinessEntity`/`LifecycleStatus`/`ReviewConclusion`）。此前报告写作「103 命名类」系旧口径误计；两侧 Δ=0 结论不受影响。

## 逐项审计（裁定 = 删除）

### 1. `tkos:StrategicChoice`（owl:Class）— **删**

| 维度 | 结论 |
|---|---|
| 实例数 | 0 |
| SHACL 引用 | 0（无 Shape 靶向或 sh:class 指向） |
| SWRL 引用 | 0（7 条 SWRL 规则均不含） |
| query_plan.py 引用 | 0 |
| roles.py 引用 | `roles.py:20` decision 桶字面量（A5 同步清理） |
| scripts 引用 | `scripts/resolve_issue_context.py:147` candidate_decisions 集合（A5 同步清理） |
| **裁定** | **删**（仅 schema；代码引用是分桶字面量，零实例无语义损失，A5 清理） |

### 2. `tkos:StrategicDecision`（owl:Class）— **删**

| 维度 | 结论 |
|---|---|
| 实例数 | 1（`decision-ceo-agent-priority-dual-scenario-validation`，A4 已迁移为 `Agreement`，见 `migration-map.md`） |
| SHACL 引用 | 0 |
| SWRL 引用 | 0 |
| query_plan.py 引用 | 0 |
| roles.py 引用 | `roles.py:20` decision 桶字面量（A5 同步清理） |
| scripts 引用 | `scripts/resolve_issue_context.py:147` candidate_decisions 集合（A5 同步清理） |
| **裁定** | **删**（实例先迁移，见 A4；执行顺序：A4 → A3 已满足） |

### 3. `tkos:OperatingDecision`（owl:Class）— **删**

| 维度 | 结论 |
|---|---|
| 实例数 | 0 |
| SHACL 引用 | 0 |
| SWRL 引用 | 0 |
| query_plan.py 引用 | 0 |
| roles.py 引用 | `roles.py:20` decision 桶字面量（A5 同步清理） |
| scripts 引用 | `scripts/resolve_issue_context.py:147` candidate_decisions 集合（A5 同步清理） |
| **裁定** | **删**（roles.py 引用是分桶，零实例无语义损失） |

### 4. `tkos:selectedAs`（owl:ObjectProperty）— **删（仅 schema）**

| 维度 | 结论 |
|---|---|
| 实例边 | 0（无三元使用此谓词） |
| SHACL 引用 | 0 |
| SWRL 引用 | 0 |
| query_plan.py 引用 | 0（spec §A.2「TRAVERSAL 移除 selectedAs/decidedAs」对代码侧是 no-op —— Plan Reconciliation #2 已核验 `query_plan.py` 不含这两个谓词） |
| roles.py 引用 | 0 |
| **裁定** | **删（仅 schema 三件套）** —— spec §A.2 的"移除"对代码侧是 no-op；照写进删除清单以证已检查，不是漏掉 |

### 5. `tkos:decidedAs`（owl:ObjectProperty）— **删（仅 schema）**

| 维度 | 结论 |
|---|---|
| 实例边 | 0（无三元使用此谓词） |
| SHACL 引用 | 0 |
| SWRL 引用 | 0 |
| query_plan.py 引用 | 0（同 selectedAs —— Reconciliation #2 已核验） |
| roles.py 引用 | 0 |
| **裁定** | **删（仅 schema 三件套）** —— 同 selectedAs，no-op 已核验 |

## 保留项（豁免）

### `tkos:Decision`（owl:Class）— **保留（豁免 ②）**

| 维度 | 结论 |
|---|---|
| 引用方 | `DecisionRecordShape.recordsDecision`（sh:class `Decision`）+ `roles.py:20` decision 桶 + `scripts/resolve_issue_context.py:147` |
| **裁定** | **保留** —— 被 SHACL Shape 靶向 + 代码消费；V3.0 不删 |

### `tkos:DecisionRecord` / `tkos:DecisionStatus`（及其 individuals）/ `tkos:DecisionProvenanceEntity`

均不在删除范围 —— 见 CLAUDE.md「会议用 DecisionRecord、决策不作本体类」。`DecisionStatus` 的 individuals（`DecisionPendingConfirmation` 等）保留为枚举闭包，A4 迁移后该个体不再被任何实例引用，但作为 enum 个体保留不违反"非必要勿增类"（不是类）。

## 审计发现（记录，本轮不阻塞、不修改）

### `DecisionRecordShape.recordsDecision`（minCount 1, sh:class Decision）— **迭代 2 前必须放宽**

**Spec Reconciliation #8**：与 V3.0 语义冲突 —— 战略会议记录的是 `Judgement` / `Agreement` 而非 `Decision`。当前 `DecisionRecord` 零实例不触发违规；但迭代 2 会议记录落盘时，此 Shape 会逼造 `Decision` 实例（违反 CLAUDE.md「禁止为填满 Shape 补造实例」）。

**裁定**：本轮不改；标记为迭代 2 前必须放宽（domain 应覆盖 `Judgement`/`Agreement`，或 minCount 降至 0）。

## 跨批次核验

### `data/instances/2026-08-13-methodology-product-distillation.trig`（V2.4.1 `bce5ab8` 新批次）

- 已核验：**零** `a tkos:StrategicDecision` / `a tkos:StrategicChoice` / `a tkos:OperatingDecision` 类型实例。
- 已核验：**零** `tkos:selectedAs` / `tkos:decidedAs` 断言边。
- 唯一命中：某 `ContextGap` 的 `scopeDescription` 文本提及"V3.0 手术范围"等字样 —— 是字符串字面量，非 RDF 类型三倍或谓词断言。
- **裁定**：无需迁移。

全 `data/instances/` 待迁移的 `a tkos:StrategicDecision` 实例仍只 `2026-08-11-product1-validation-update.trig` 那一个（A4 已处理，见 `migration-map.md`）。

## 验证证据（A3 执行后）

- `python3 tests/run_schema_isomorphism.py`：
  - `jsonld ⇔ ttl: isomorphic (1200 triples)`
  - `jsonld ⇔ protege-view (modulo imports): isomorphic`
- `python3 tests/run_instance_conformance.py`：`real-instances-merged (10 files): conforms=True, violations=0`
- `grep -rn "StrategicChoice\|StrategicDecision\|selectedAs\|decidedAs\|OperatingDecision" ontology/`：**零命中**（class/property 定义从 jsonld/ttl/protege view 三件套彻底消失）。
