# Runtime 2.0 基座迭代 Spec：V3.0 本体手术 + v1 契约对齐 + Key 模型

状态：draft（2026-08-13，依据本轮范围裁定）
权威范围：**下一轮迭代（Runtime 2.0）的设计基线**。本迭代不交付 lineage / submissions 业务端点，只交付三者共同的基座，使后续 1（Lineage）与 2（Submissions）能以 v1 目标形态出生、有类可写、有角色可投影。
上游权威：`docs/mvp/01-03`（统一语言 / 本体 V3.0 / API v1）。本文件与其冲突时以上游为准并回改本文件。

---

## 0. 定位与依赖图

Runtime 1.0（P1.1，已部署 ECS `115.190.213.44`）只交付了读路径 `resolve` + `render`。要走到 MVP 闭环验收（`docs/mvp/01` §6 九条），还差两个业务端点（lineage / submissions）和它们的三类共同前置。本轮裁定：**先做基座，不做端点**。

依赖图（本轮范围 = A + B + C）：

```text
  A. V3.0 本体手术 ──────────┐
                              ├──→ 2. Submissions 写入闭环（验收 1-4/6）
  C. Key 模型 ────────────────┤
                              └──→ 1. Lineage + 角色投影（验收 5/7）
  B. v1 契约对齐 ─────────────→ 新端点以 v1 目标形态出生，不返工
```

- **A 解锁 2**：submissions 的 9 类提交里，`agreement` / `feedback` 的承载类（`Agreement`、`FeedbackRecord`）与主数据锚 `Product` 在 TBox 中**尚不存在**（已核验：`ontology/schema/` 三者 0 命中），也没有对应 SHACL Shape——不补类，写入闭环做到一半会发现没有东西可写。
- **C 解锁 1 与 2**：lineage 的"executor 不可穿透"（验收 5）与 submissions 的确认权（验收 6）都依赖 `cxo|executor` 角色；当前 `Principal` 无 `role` / `on_behalf_of` / `tenant`。
- **B 兜底形态**：A、C 完成后，lineage / submissions 按 v1 契约（Key 推导作用域、请求只说业务语言）出生，无需返工。

**整体路线图顺序：本轮（3=A+B+C）→ 1（Lineage）→ 2（Submissions）。** 不合并端点迭代。

---

## 1. 目标与非目标

### 目标

1. 本体收敛到 V3.0 核心集：补 `Agreement` / `FeedbackRecord` / `Product` 及 5 个新关系、5 个新数据属性、对应 SHACL Shape；物理删除 `StrategicChoice` / `StrategicDecision` / `selectedAs` / `decidedAs`，按存留判据审计 `Decision` / `OperatingDecision`。
2. Key 模型扩展：`Principal` 增 `tenant` / `role(cxo|executor)` / `on_behalf_of` / `confirmer` / `default_scenario`；Key 注册表成为运维配置制品。
3. v1 契约对齐：resolve/render 收敛到 `docs/mvp/03` 目标形态（作用域由 Key 推导、render 并入 resolve 的 `render` 选项、移除 client-supplied pack 路径），经一个 deprecated 过渡小版本后删除旧字段。
4. 三者集成后：1.0 部署的 FE 场景（产品 1.0 + 灯塔同季交付）仍按现有契约可用（过渡期内），全量回归绿，OpenAPI/Apifox 同步。

### 非目标（显式排除，留待后续迭代）

- `GET /v1/assertions/{id}/lineage` 端点（迭代 1）。
- `POST /v1/submissions` 写入闭环、确认事件、物化、`dataset_revision` 推进（迭代 2）。
- 在线 OWL/SWRL 推理、异步蒸馏 Worker、生产 RDF Store 替换、真实 Agent 端到端联调。
- Persona 个人决策本体包落地（render 三段降级为 context_gap 的现状保持）。

---

## 2. 工作流 A — V3.0 本体手术（与 B/C 可并行）

权威：`docs/mvp/02`。作为**一次性联合手术**执行（物理删减 + 全部新增 + SHACL/SWRL/实例/测试同步迁移，同一个破坏性 Release）。

**分包延后（本轮裁定，已回改文档二 §5）**：破坏性的是删减，必须一次做净；分包在共享命名空间 `tkos#` 不变前提下是非破坏性文件/IRI 重组，延至 Persona 迭代与 8 类实体一起落地——现在做等于造一个零关系、零实例、零消费方的空包，违反“非必要勿增类”。本轮 Release 仅记 company 版本，`ontology_release.persona` 置 null（见 B.3）。

### A.1 新增

| 维度 | 内容 |
|---|---|
| 类 | `Agreement`（⊂ `AttributedAssertion`）、`FeedbackRecord`（⊂ `ContextAsset`）、`Product`（主数据锚，TBox 现缺） |
| 对象属性 | `addressesIssue`、`adoptsJudgement`、`producesArtifact`、`mandatedBy`、`evaluatesTarget`（值域审计后须覆盖 `Artifact`/`Agreement`/`Mission`/`ContextPack`，不足则放宽值域，不新增属性） |
| 数据属性 | `agreementStatus`（`close\|go_on`）、`signalSourceType`（`external\|internal\|ceo_personal`）、`qualityScore`（int 1–5）、`experienceScore`（int 1–5）、`gapNote`（string） |
| SHACL Shape | `Agreement`（必有 `adoptsJudgement`/`agreementStatus`/确认事件；同 Issue 同时最多一个有效 Agreement）、`FeedbackRecord`（必有 `evaluatesTarget` 与至少一个评分；分值 1–5）、`Product`（主数据唯一性门禁） |

### A.2 删除（V3.0 第一刀）与审计

- 物理删除：`StrategicChoice`、`StrategicDecision`、`selectedAs`、`decidedAs`。
- 唯一 `StrategicDecision` 实例 `decision-ceo-agent-priority-dual-scenario-validation` 迁移为 `Agreement`。
- `Decision`、`OperatingDecision` 进删除候选，按 §5 存留判据审计（无 SHACL/SWRL/查询计划/`roles.py` 实质依赖即删）。
- `src/tkos_runtime/domain/roles.py` 类型桶同步：移除删除项，为 `Agreement` 增设桶（决议/结论语义）。
- **`src/tkos_runtime/domain/query_plan.py` 同步**：TRAVERSAL 谓词表移除 `selectedAs`/`decidedAs`、加入 5 个新对象属性，`query_plan_version` bump——否则迁移后的 Agreement 实例经 `adoptsJudgement`/`mandatedBy` 展不开，迭代 1 lineage 直接踩坑。**注意：`roles.py:20` 当前 `decision` 桶仍含 `StrategicDecision`/`StrategicChoice`/`Decision`/`OperatingDecision`，是 resolver 角色分类的单一来源，删类必同步。**

### A.3 存留判据（`docs/mvp/02` §5）

进核心集，或满足任一豁免且该引用仍被需要：① 有真实实例引用（`data/instances/`）；② 被 SHACL/SWRL/查询计划/`roles.py` 引用；③ 属上位本体 imports。豁免不成立即删。

### A.4 交付物（破坏性迁移必备）

1. 删除清单（逐类豁免核查）。
2. 实例迁移映射（被删类的既有实例如何改挂）。
3. 前后类数对比（现 ~104 → 核心集 ~47 中本轮应落的部分：Persona 缺失类随分包延后，本轮落地数以审计清单为准，逐类可解释）。
4. 全量回归证据：解析、SHACL 正负向、Openllet SWRL、Runtime/API/Harness。

### A.5 红线

- **部署系统的破坏性手术**：1.0 实例数据（FE 场景议题链 `issue-product1-lighthouse-*`、风险/进展快照）所引用的类必须落在核心集或豁免内，手术不得破坏现行 resolve 命中；**允许受控 diff**（实例迁移映射内的类型/分桶变化，如 StrategicDecision→Agreement），diff 必须逐条对应迁移映射。
- 新增门禁（迁移后生效）：任何新类必须回答"进不进核心集、支撑闭环哪一环、哪条 Competency Question 需要它"。

---

## 3. 工作流 B — v1 契约对齐（依赖 C 的 Key 模型）

权威：`docs/mvp/03` §1/§2/§3.1。薄请求、厚响应；Key 即租户/角色/Persona 锚点。

### B.1 resolve 收敛

- 请求：`query`（唯一必填）+ 可选 `scenario` / `render` / `as_of` / `token_budget`。
- **移除请求字段**：`enterprise_id`、`organization_scope`、`purpose`、`persona_id`——作用域与 Persona 锚点由 Key 得出，`purpose` 由 `scenario` + Key 映射（消除扩权面）。
- `scenario` 注册表为唯一权威映射（四场景 id 以 `docs/mvp/01` §5 为准）。**本轮只做**：枚举校验 + 映射 purpose + 记录进 Pack；场景 Profile / WorkPattern 加载 / 渲染模板差异化**不在本轮**（当前只有一套渲染模板，提前分化是隐藏工作量），留待场景真正分化时实现。

### B.2 render 并入 resolve

- `POST /v1/context-packs:render`（独立端点，含 client-supplied pack 路径）并入 resolve 的 `render: true` 选项。
- **删除 client-supplied pack 输入路径**（已知门禁缺口；当前 `server.py:340-349` 仍接受 `req.pack`）。

### B.3 版本固定块

所有响应统一携带 `docs/mvp/03` §2 的版本固定块：`api_version` / `request_id` / `ontology_release{company,persona}` / `dataset_revision` / `policy_version` / `query_plan_version`。

- **`dataset_revision` 本轮为只读语义**：加载时按租户计算的内容哈希。“推进”（确认物化后原子前进）属迭代 2 的写路径，本轮不得半建写机制。
- **`ontology_release.persona` 置 null**（Persona 包随分包延后），字段结构就位、值待 Persona 迭代填充。

### B.4 过渡策略（`docs/mvp/03` §5）

相对现行实现是 v1 大版本内收敛：移除字段与独立 `:render` 端点本轮标记 **deprecated**，**删除动作在迭代 1（Lineage）发布时执行**——本轮结束时旧字段必须仍可用；新增字段全部可选默认化。OpenAPI/JSON Schema、正反契约测试、Apifox 同步与实现同步。每端点补一张标注 L5/L4/L2 职责切面的时序图。

### B.5 红线

- **契约破坏面**：当前 ECS 消费方与 Apifox 13 个用例绑定旧字段（`enterprise_id`/`purpose`/独立 `:render`）。过渡期旧字段必须仍被接受（deprecated 警告），不得直接 422，否则打断联调。

---

## 4. 工作流 C — Key 模型（与 A 可并行；B 依赖之）

权威：`docs/mvp/03` §2。`Principal` 扩展为 Key 即租户/角色/Persona 锚点。

### C.1 Principal 扩展

当前 `auth.py` `Principal{name, allowed_purposes, allowed_scopes}` 增字段：

| 字段 | 语义 |
|---|---|
| `tenant` | **主租户**（单值）：revision 归属与写入归属的锚；跨组织协作作用域（灯塔）继续走 `allowed_scopes`，不引入复数租户 |
| `role` | `cxo \| executor`（时序投影与确认权权威） |
| `on_behalf_of` | 确认人 / Persona 锚点（Person IRI；敏感分区锚点） |
| `confirmer` | 是否有确认权（submissions 用；本轮先建模，不消费） |
| `default_scenario` | 缺省场景 id（scenario 缺省时由 Key 得出） |

`allowed_purposes` / `allowed_scopes` 保留（purpose 门禁既有逻辑不变）。

### C.2 Key 注册表（运维配置制品）

字段：`key` / `tenant`（主租户）/ `allowed_scopes`（含协作作用域）/ `role` / `on_behalf_of` / `confirmer` / `default_scenario` / `allowed_purposes`。MVP 形态：配置文件（环境变量或受版本控的注册表文件，**不含明文 Key 之外的敏感凭据**）。变更本身记审计事件。

### C.3 authZ 扩展

- 既有：purpose 门禁（`assert_purpose`，`allowed_purposes × AdmissionPolicy.allowed_graphs`）。
- 新增：**role 门禁**——为后续 temporal_projection（lineage）与 confirmer（submissions）预留。本轮先实现 role 字段解析与"cxo/executor 命中"的契约测试，不改变 1.0 读路径可见性（默认 Principal = cxo 全可见，保证向后兼容）。
- 新增：**tenant → 图作用域接线（本轮必做，不是预留）**：`tenant` 经既有 `allowed_scopes × AdmissionPolicy.allowed_graphs` 机制过滤可见图。不接线则 B 的“作用域由 Key 推导”是空转。跨租户访问返回 404（不可见即不存在，不泄漏存在性）。

### C.4 向后兼容（红线）

- 单 `TKOS_API_KEY`（1.0 部署形态）继续映射为 `Principal(name="default", role="cxo", allowed_purposes={"*"})`——1.0 的 401/403 契约测试与 ECS 联调不回归。
- `TKOS_API_KEYS_JSON` 扩展为可声明 `role`/`tenant`/`on_behalf_of`；未声明者回退 cxo/默认租户。

### C.5 红线

- **认证面扩权**：`on_behalf_of` / Persona 锚点是敏感分区入口；本轮只建模、不开放任何按 Persona 取 Pack 的新读路径（Persona 包未落地）。

---

## 5. 依赖、顺序与并行

| 工作流 | 依赖 | 可并行于 |
|---|---|---|
| A. V3.0 手术 | 无（纯 Layer 3） | B、C |
| C. Key 模型 | 无（纯 auth 层） | A、B 的设计 |
| B. v1 契约对齐 | **C**（Key 推导作用域） | A |

建议执行序：**A 与 C 先并行开工** → C 落地后启动 B → A/B/C 集成回归。A 的破坏性 Release 与 B 的契约切换不宜同 commit；先 A（本体 Release 前进）→ 再 B（API 契约 deprecated→remove）。

---

## 6. 验收标准

### 6.1 A（本体）

- [ ] `Agreement` / `FeedbackRecord` / `Product` 进 TBox 且有 SHACL Shape；`docs/mvp/02` §6 约束全部进 Core Profile。
- [ ] `StrategicChoice` / `StrategicDecision` / `selectedAs` / `decidedAs` 物理删除；`Decision`/`OperatingDecision` 审计有结论。
- [ ] `roles.py` 类型桶同步，resolver 角色分类测试绿。
- [ ] A.4 四项交付物齐备；类数 104→~47（以审计为准）。
- [ ] FE 场景议题链 resolve 命中不变，受控 diff 逐条对应实例迁移映射（`issue-product1-lighthouse-synchronous-delivery` 等）。
- [ ] `query_plan.py` TRAVERSAL 更新 + `query_plan_version` bump，新关系可展开有测试。

### 6.2 C（Key 模型）

- [ ] `Principal` 扩字段；Key 注册表制品落地；`role`/`tenant`/`on_behalf_of` 解析有契约测试。
- [ ] 单 `TKOS_API_KEY` 向后兼容：1.0 的 401（无凭据/错凭据）/ 200 路径不回归。
- [ ] role 门禁骨架可测（cxo/executor 解析正确），但读路径可见性默认不变。
- [ ] **跨租户负向测试**：第二租户 Key 访问 tokenking 议题返回 404；双 Key（cxo/executor 结构）解析各就位。

### 6.3 B（契约）

- [ ] resolve 接受 v1 形态（`query`+可选 `scenario`/`render`/`as_of`/`token_budget`），旧字段（`enterprise_id`/`organization_scope`/`purpose`）过渡期接受并标 deprecated。
- [ ] `render: true` 返回 Markdown；client-supplied pack 路径标记 deprecated（过渡期）→ 删除。
- [ ] 响应携带版本固定块；`dataset_revision` 为租户级内容哈希（只读语义）；`ontology_release.persona` 为 null。
- [ ] OpenAPI 与 Apifox（AI 分支）同步：v1 形态示例 + deprecated 标注。

### 6.4 集成

- [ ] `make test-fast` + `make test`（含 Openllet）全绿。
- [ ] ECS（`115.190.213.44`）过渡期联调：旧字段仍 200，v1 字段可用。
- [ ] CLAUDE.md / README.md 反映 2.0 状态（本轮交付物的一部分）。

---

## 7. 风险与回退

| 风险 | 影响 | 缓解 / 回退 |
|---|---|---|
| V3.0 删类破坏 1.0 实例数据 | FE 场景 resolve 命中丢失 | 手术前冻结 FE 场景议题链类清单为回归基线；删类前逐一过 §5 豁免；失败回退到手术前 Release 指针 |
| 契约切换打断 ECS/Apifox 联调 | 联调中断 | 强制 deprecated 过渡期，旧字段不直接 422；Apifox 用例双轨（旧字段 + v1 字段） |
| Key 模型扩权或回归 401/403 | 部署认证坏 | 单 Key 默认 cxo 全可见；保留 1.0 的 9 项认证契约测试为门禁 |
| A 与 B 同 commit 不可回滚 | 本体与契约耦合 | 分 Release：先 A 后 B，各自独立回退指针 |

---

## 8. 交付物清单（本轮）

1. 本 Spec（本文件）。
2. V3.0 本体 Release（含 A.4 四项迁移交付物）。
3. Key 注册表制品 + `Principal` 扩展 + authZ 骨架。
4. v1 契约（resolve 收敛 + render 并入 + 版本固定块）+ deprecated 过渡。
5. OpenAPI / Apifox 同步。
6. 全量回归证据（解析/SHACL/Openllet/Runtime/API/Harness）。
7. 重写的 CLAUDE.md / README.md（反映 2.0 状态与本轮成果）。
8. 被 2.0 取代的文档标注 superseded（指向 docs/mvp）；**不做仓库大扫除**——物理清理是独立任务，不与破坏性手术同迭代混合 diff 面。

---

## 9. 本轮之后（路线图提醒，不在本轮）

- **迭代 1 — Lineage**：`GET /v1/assertions/{id}/lineage`，复用 C 的 role 投影（executor 不可穿透），覆盖验收 5/7。
- **迭代 2 — Submissions**：`POST /v1/submissions` + 候选→SHACL→确认事件→物化→`dataset_revision` 推进 + 9 类提交，依赖 A（类）与 C（确认权），覆盖验收 1-4/6。
