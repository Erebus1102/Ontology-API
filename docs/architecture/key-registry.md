# Key Registry (Key 注册表制品)

> Runtime 2.0 基座的认证 / 授权锚点。本文档定义 Key 注册表的字段、环境变量加载顺序、变更审计约定与安全红线。对应实现见 `src/tkos_runtime/api/auth.py`（`Principal` dataclass + `_load_credentials`）。

## 1. 用途与边界

Key 注册表把每个 API Key（Bearer token）映射到一个 `Principal`，由 `Principal` 派生出该请求的**租户归属、角色、用途白名单、图作用域、默认场景**——调用方请求体不再携带 `enterprise_id` / `purpose` / `persona_id`，一切作用域由 Key 推导（消除扩权面，见 `docs/mvp/03` §1）。

注册表通过**环境变量**注入运行时，不落 git 明文：

- **Key 明文**只存 ECS 服务器 `.env`（权限 `600`，永不入库）。
- **Key 之外的非密钥部分**（`tenant` / `role` / `on_behalf_of` / `confirmer` / `default_scenario` 等）以脱敏示例形态版本控管——见 `deploy/ecs/key-registry.example.json`。

## 2. 注册表字段

下表按 JSON 条目字段名（`TKOS_API_KEYS_JSON` 的 value 对象）给出。`token` 是 JSON 的 **key**（字符串），其余字段在 value 对象内。除 `token` 必填外，其余字段皆可选，缺省取 `Principal` dataclass 默认值。

| JSON 字段 | Principal 字段 | 类型 | 默认 | 语义 |
|---|---|---|---|---|
| `<token>`（JSON key） | — | string | **必填** | API Key 明文（Bearer token）。仅入 ECS `.env`，不入 git。 |
| `name` | `name` | string | token 前 8 字符 / `"default"` | Key 的可读名，用于日志、审计、journald 按 key-name 回溯。**日志只记 `name`，永不记 token 本体。** |
| `tenant` | `tenant` | string | `"default"` | 租户归属锚。本轮**不**新造图维度，而是与 `scopes` 共同承担作用域收敛（见 `scopes` 行与 §4）。 |
| `purposes` | `allowed_purposes` | array<string> | `["*"]` | 允许的 purpose 白名单。`["*"]` = 全用途。请求推导出的 purpose 必须在此集合内，否则 403。 |
| `scopes` | `allowed_scopes` | array<string> \| null | `null` | partition-id 白名单，决定该 Key 能看到哪些命名图。`null` = 不限（全可见，cxo 默认）；`[]` = 空集（**全拒**——任何图都不可见 → resolve 无命中 → 404，不泄漏存在性）。跨租户隔离经此字段实现（C3）。 |
| `role` | `role` | string | `"cxo"` | `"cxo"`（全可见）或 `"executor"`。本轮不改读路径可见性（默认 cxo 全可见）；role 字段已建模，供 submissions 确认权与后续差异化使用。 |
| `on_behalf_of` | `on_behalf_of` | string \| null | `null` | 该 Key 所代理的 Person IRI（如 `tkos:person-ceo`）。用于断言的"表达主体"溯源。 |
| `confirmer` | `confirmer` | boolean | `false` | 是否持有 submissions 确认权。本轮仅建模，门禁随 submissions 端点（迭代 2）落地。 |
| `default_scenario` | `default_scenario` | string \| null | `null` | 当请求未显式带 `scenario` 时，用于推导 `purpose` 的默认场景 id。**取值必须是权威场景 id**（见下）。 |

### 2.1 权威场景 id

`default_scenario`（以及请求体的 `scenario` 字段）只能取以下四个权威 id 之一——来源：`docs/mvp/01` §5 + `docs/mvp/03` §2 场景注册表（Reconciliation #7）。**不得杜撰 id。**

| scenario id | → purpose | 用途 |
|---|---|---|
| `meeting_supervision` | `decision_preparation` | 会议督导 |
| `strategic_research` | `decision_preparation` | 战略研究 |
| `expert_panel` | `decision_preparation` | 专家面板 |
| `task_followup` | `mission_review` | 任务跟进（映射既有 `mission_review`，非 `execution_support`） |

## 3. 环境变量加载顺序

运行时通过 `_load_credentials()`（`auth.py`）在每次调用时读取环境快照，支持两种模式，**可组合**：

| 环境变量 | 形态 | 产出 Principal |
|---|---|---|
| `TKOS_API_KEY` | 单个 token 字符串 | `Principal(name="default", allowed_purposes={"*"}, allowed_scopes=None)`，2.0 字段取默认（`tenant="default"` / `role="cxo"` / `on_behalf_of=None` / `confirmer=False` / `default_scenario=None`）——即单 Key 调用方保持 cxo 全可见（C.4 向后兼容红线）。 |
| `TKOS_API_KEYS_JSON` | JSON：`{"<token>": {字段...}}` | 按字段构造 `Principal`，支持多租户 / 多角色。 |

**加载与冲突裁定**：`TKOS_API_KEY` 先加载，`TKOS_API_KEYS_JSON` 后加载；当同一 token 字符串在两边都出现时（碰撞），**`TKOS_API_KEY` 的单 Key 解释优先**——该 token 取 cxo / 全可见 / `tenant="default"` 形态，不被多 Key 条目降权。这是向后兼容的安全属性：单 Key 部署永远不会被意外的多 Key 碰撞 demote。

> 设计意图：`TKOS_API_KEY` 是 1.0 推荐形态（单 cxo 全可见），`TKOS_API_KEYS_JSON` 是 2.0 多租户 / 多角色形态。两者共存期间，单 Key 的 cxo 语义不可被覆盖。

## 4. 租户 → 图作用域（与 `scopes` 的关系）

`tenant` 是**归属锚**（记录该 Key 属于哪个租户），本轮**不**把 tenant 映射成新的图维度。跨租户隔离由 `scopes` 字段承担——它是 partition-id 白名单，经既有 `AdmissionPolicy.allowed_graphs` 机制过滤（C3 接线）：

- `scopes: null` → 不限（cxo 默认，全图可见）。
- `scopes: ["confirmed", "provenance", "derived"]` → 仅这些 partition 可见。
- `scopes: []` → 空集，**全拒**：任何图都不可见 → intent 无命中 → resolve 返回 404（不泄漏存在性）。

`deploy/ecs/key-registry.example.json` 的第二租户 `other` 故意设 `scopes: []`，正是为 C3 跨租户 404 负向测试而设。

## 5. 变更记审计事件

Key 注册表的非密钥部分（字段值）变更**经 git commit 提交**——commit 历史即为审计事件的可追溯载体（脱敏形态版本控管，对应 `docs/mvp/05-deployment-2.0.md` §3.2）。轮换流程（新旧 Key 并存 → 通知调用方切换 → 删旧 Key）不停机，因为 authN 逐请求读环境快照。

**结构化审计事件机制（`CandidateCreated` / `ConfirmationRecorded` 等）本轮不建**——随 submissions 端点（迭代 2）落地。本轮只约定：注册表变更走 git、Key 明文不入库、日志按 key-name 回溯。

## 6. 安全红线

- **不含明文 Key 之外的敏感凭据**：注册表 / 示例 JSON / `.env` 之外，**不得**入库任何其他敏感凭据（ECS 凭据、Apifox token、第三方 API Key 等）。CLAUDE.md「不提交敏感」红线适用于此。
- **Key 明文仅入 ECS `.env`**（权限 `600`），永不入 git、永不入日志、永不入响应。
- **日志含 `request_id` + key-name，永不含 Key 本体**。
- 示例文件 `deploy/ecs/key-registry.example.json` 的 token 字段是**明显占位符**（`REPLACE_WITH_TOKENKING_KEY` / `REPLACE_WITH_OTHER_TENANT_KEY`），不可被误认为真实 Key。

## 7. 示例

脱敏双租户示例见 **`deploy/ecs/key-registry.example.json`**（含 cxo 全可见租户 + `scopes: []` 跨租户隔离示例）。部署时复制为 `.env` 内的 `TKOS_API_KEYS_JSON` 值，并把占位符替换为真实 Key。
