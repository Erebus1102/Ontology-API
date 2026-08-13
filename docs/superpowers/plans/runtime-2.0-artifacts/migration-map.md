# Migration Map — `StrategicDecision` instance → `Agreement` (V3.0, Task A4)

> Runtime 2.0 基座的受控实例迁移记录（Execution Discipline 2 制品）。逐字段：原三元组 → 迁移后三元组 → 取值出处。INT 核验消费本文件，不靠会话记忆。

**Scope:** 单实例迁移。`data/instances/2026-08-11-product1-validation-update.trig` 中的 `tkos:decision-ceo-agent-priority-dual-scenario-validation` 是仓库内**唯一**的 `a tkos:StrategicDecision` 实例（A3 审计已核验：全 `data/instances/` 仅此一处类型断言；`2026-08-13-methodology-product-distillation.trig` 零命中）。

**Why migrate:** A1 已建 `tkos:Agreement ⊂ tkos:AttributedAssertion`（spec §A.1 + `docs/mvp/02` 为准）。`StrategicDecision` 即将由 A3 物理删除，其唯一实例必须先迁成 `Agreement`，否则会引用已删类。

**前置：** A1（`Agreement` 类 + `agreementStatus` 数据属性 + `reviewCondition` domain 放宽为 `unionOf(Decision, Agreement)`）、A2（`AgreementShape` + 既有 `AttributedAssertionShape`）已在 HEAD。

**迁移依据总则（认知诚实 / spec §A.5 红线）：**
- 类型迁移与 `hasStatus` 删除由 V3.0 类语义决定（`Agreement ⊄ Decision`，`DecisionStatus` 不再适用）。
- `assertedBy` / `recordedAt` **非杜撰**——取自**同源 DRI** (`tkos:source-dri-product1-validation-update-2026-08-11`) 的姊妹 AttributedAssertion `tkos:assertion-ceo-agent-priority-dual-scenario-2026-08-11`（与本实例同 graph 文件、同 DRI、同一事件同一主体的同一记号）。补这两条仅为让深类靶向的 `AttributedAssertionShape` 满足——其值在数据中已存在，仅是迁移前未在 decision 个体上重复。

---

## 文件

`data/instances/2026-08-11-product1-validation-update.trig`，graph `tkos:graph-candidate-and-dispute`。

迁移后实例位于 **lines 37-48**（迁移前 37-46；净 +2 行：删 1 行 `hasStatus`，加 3 行 `agreementStatus`/`assertedBy`/`recordedAt`）。

姊妹断言 `tkos:assertion-ceo-agent-priority-dual-scenario-2026-08-11`（graph `tkos:graph-decision-provenance`）位于 **lines 81-88**，是 provenance 取值的权威来源。

---

## 逐字段迁移映射

| # | 原三元组（迁移前） | 迁移后三元组 | 取值出处 / 依据 |
|---|---|---|---|
| 1 | `tkos:decision-ceo-agent-priority-dual-scenario-validation a tkos:StrategicDecision ;` (line 37) | `tkos:decision-ceo-agent-priority-dual-scenario-validation a tkos:Agreement ;` (line 37) | **类迁移**：A1 新建 `Agreement ⊂ AttributedAssertion`；A3 将物理删除 `StrategicDecision`。spec §A.1。 |
| 2 | `tkos:objectId "decision-ceo-agent-priority-dual-scenario-validation" ;` | 同上（原样保留，line 38） | 不变。 |
| 3 | `tkos:displayName "采用 CEO Agent 优先..." ;` | 同上（原样保留，line 39） | 不变。 |
| 4 | `tkos:scopeDescription "验证优先以 CEO Agent..." ;` | 同上（原样保留，line 40） | 不变。 |
| 5 | `tkos:informedBy tkos:issue-product1-lighthouse-synchronous-delivery, tkos:research-product1-lighthouse-validation-options-week1 ;` | 同上（原样保留，line 41） | 不变。`informedBy` 已在 `query_plan.TRAVERSAL`，迁移后实例仍经此挂入议题链。 |
| 6 | `tkos:reviewCondition "产品 1.0 MVP 未按本周产出..." ;` | 同上（原样保留，line 42） | 不变。A1 Step 4b 已把 `reviewCondition` 的 `rdfs:domain` 由 `Decision` 放宽为 `owl:unionOf(Decision, Agreement)`，故迁移后不会在 pyshacl `inference="rdfs"` 下被反推为 `Decision`（Flag #1 防污染）。 |
| 7 | `tkos:hasStatus tkos:DecisionPendingConfirmation ;` (line 43) | **删除** | **`DecisionStatus` 体系不再适用**：`Agreement ⊄ Decision`。spec §A.1；迁移映射 spec 行「hasStatus → 删除」。 |
| 8 | —（迁移前无） | `tkos:agreementStatus "go_on" ;` (line 43) | **新增**：A1 新建 `agreementStatus` 数据属性（xsd:string + A2 `AgreementShape` `sh:in ["close","go_on"]`）。取值 `"go_on"` 对应原 `DecisionPendingConfirmation` 的「仍推进中、待 CEO 确认事件」语义（A4 迁移表 spec 行）。 |
| 9 | —（迁移前无） | `tkos:assertedBy tkos:person-liurenhao ;` (line 44) | **新增（非杜撰）**：← 同文件 line 85，姊妹断言 `tkos:assertion-ceo-agent-priority-dual-scenario-2026-08-11` 的 `tkos:assertedBy tkos:person-liurenhao`。同一 DRI 来源 (`tkos:source-dri-product1-validation-update-2026-08-11`)、同一事件、同一主体（刘人豪 DRI operating update）。补此条仅为满足深类靶向的 `AttributedAssertionShape`。 |
| 10 | —（迁移前无） | `tkos:recordedAt "2026-08-11T00:00:00+08:00"^^xsd:dateTime ;` (line 45) | **新增（非杜撰）**：← 同文件 line 87，姊妹断言 `tkos:assertion-ceo-agent-priority-dual-scenario-2026-08-11` 的 `tkos:recordedAt`。值与该实例自身的 `validFrom` (line 48) 一致——同 DRI 事件的同一时间戳。 |
| 11 | `tkos:hasConfirmationStatus tkos:Candidate ;` | 同上（原样保留，line 46） | 不变。仍 `Candidate`（尚未绑定 CEO ConfirmationEvent）。 |
| 12 | `tkos:sourcedFrom tkos:source-dri-product1-validation-update-2026-08-11 ;` | 同上（原样保留，line 47） | 不变。这是与姊妹断言共享的 DRI 来源锚（provenance 取值的总依据）。 |
| 13 | `tkos:validFrom "2026-08-11T00:00:00+08:00"^^xsd:dateTime .` | 同上（原样保留，line 48） | 不变。 |

---

## Shape 合规推导（迁移后）

迁移后实例被两层 Shape 靶向，均满足（已由 `python3 tests/run_instance_conformance.py` 验证：`conforms=True, violations=0`）：

1. **`AttributedAssertionShape`（深类靶向，因 `Agreement ⊂ AttributedAssertion`）**：
   - `assertedBy` ← line 44 ✅（本任务补）
   - `sourcedFrom` ← line 47 ✅（原有）
   - `recordedAt` ← line 45 ✅（本任务补）
   - `hasConfirmationStatus` ← line 46 ✅（原有）

2. **`AgreementShape`（A2 新建，`sh:targetClass tkos:Agreement`）**：
   - `agreementStatus "go_on"` ∈ `sh:in ["close","go_on"]` ← line 43 ✅（本任务补）
   - `adoptsJudgement` minCount 0 ✅（无强制，Reconciliation 4：数据中零 Judgement 实例，强制会逼造）
   - `addressesIssue` minCount 0 ✅（可选）
   - 「同 Issue 最多一个有效 go_on Agreement」sh:sparql ✅（本实例未带 `addressesIssue`，不触发；议题关联经 `informedBy` 而非 `addressesIssue`）

> 注：`hasStatus` / `DecisionPendingConfirmation` 个体不在删除范围（A3 只删 `StrategicChoice`/`StrategicDecision`/`OperatingDecision` + `selectedAs`/`decidedAs`）；`DecisionStatus` enum 与 `hasStatus` 对象属性仍服务于 `Decision` 类（保留）。

---

## 未改动项

- `data/instances/2026-08-11-ceoagent-and-scenarios-update.trig`：line 59 仅是一条指向本实例的 `informedBy` 边（无类型重申），RDF merge 下类型来自定义文件，无需改动（spec A4 Files 已显式标注）。
- 其余 9 个 instance 文件：A3 审计已核验零 `StrategicDecision` 类型实例，无迁移。

## 回滚

`git revert <A4 commit>` 即可恢复 `StrategicDecision` 实例。本 commit 独立于 A3 的删类 commit（A3 在本 commit 之后），二者可独立回退。
