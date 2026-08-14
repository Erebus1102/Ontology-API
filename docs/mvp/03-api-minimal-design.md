# 核心文档三：API 最简设计

状态：v1（依据 2026-08-13 拍板记录构建）
权威范围：**API 功能面、端点边界与出入参结构的唯一权威**。字段术语与文档一一致，引用对象不超出文档二核心集。
调用方模型：**Runtime 的调用方是平台后端（Agent 编排层）**，Key 按 Agent 实例发放并绑定确认人（`on_behalf_of`）；终端 LLM Agent 不直连 Runtime。
设计原则：**薄请求、厚响应**；调用方只说业务语言（query/scenario/挂靠位置），治理词汇与机制（purpose、图路由、事件链、物化）全部后端闭环；Key 即租户/角色/Persona 锚点（请求不自带作用域）；候选/已确认边界不可越过；认知诚实（omissions / gaps 必须如实返回）；LLM 失败不阻断结构化结果，事实查询失败不得用 LLM 补偿。

---

## 1. 功能面（3 业务端点 + 3 运维端点，不再多）

| 端点 | 功能 | 对应业务动作 |
|---|---|---|
| `POST /v1/context-packs:resolve` | 议题 → 结构化 Context Pack；`render: true` 时附可注入 Prompt 的 Markdown | 会前呈现、研究/讨论上下文、Mission Context Pack 下发 |
| `GET /v1/assertions/{id}/lineage` | 断言 → 版本/来源/确认/挑战/反馈图 | 追溯 Judgement 链、验证反馈是否改好 |
| `POST /v1/submissions` | 唯一写入口：候选断言与确认/拒绝事件 | 闭环全部写入动作，含一号位界面确认落盘 |
| `GET /health` `/ready` `/version` | 运维 | 已实现，保持 |

**写入本体的四段式**（红线：任何调用方不得直接写当前有效视图，一切写入先候选后确认）：

```text
① 提交候选  Agent: POST /v1/submissions → 落候选图，返回 candidate_ids
② 界面呈现  Agent 向一号位展示候选内容（按钮/语音等交互形态属 L5，Runtime 不感知）
③ 确认      同一写入口：即时确认随首写带 confirmation_status=confirmed；
            延迟确认再写一条 type=confirmation 事件指向候选 id
④ 物化      确认事件自动触发：候选进 confirmed 图，dataset_revision 原子前进
```

确认怎么被触发（按钮/口头/时机）是 L5 后端逻辑；Runtime 只认写入事件。git 通道降级为**冷启动批量导入专用**（慢变事实蒸馏批次）。

**蒸馏不是 API**：两个入口性质不同——submissions 收**结构化候选断言**（Agent 已知字段含义，高频小粒度同步）；蒸馏收**原始文档**（需解析/抽取/消歧，低频批量异步），MVP 为 CLI 流水线。四场景中 Agent 自己就是蒸馏器（会议纪要→五项产出由一号位 Agent 完成，提交的已是结构化断言）。**升级为 API 2（Distillation Job）的触发条件**：房懂懂/AIDC 独立租户接入且其 Agent 需自助上传文档蒸馏；届时 SourceSnapshot → CandidateAssertionBatch 制品语义不变，仅加异步 Job 接口层。

**其余不是 API 的能力**：推理器/图库/LLM（内部 Adapter）。**慢变客观事实**（宪法/公司现实/产品档案/方法）的维护走蒸馏 + git 通道，不进 submissions 高频路径。

## 2. 认证与通用契约

- `Authorization: Bearer <key>`。Key 解析出 `tenant_scopes`、`role: cxo|executor`、`allowed_purposes`、`on_behalf_of`（确认人与 Persona 锚点）。**`enterprise_id` / `organization_scope` / `persona_id` / `purpose` 均不在请求中**——作用域与 Persona 锚点由 Key 得出，purpose 由 scenario + Key 映射，消除扩权面。
- 所有成功响应统一携带版本固定块（错误响应见下条）：

```json
{
  "api_version": "v1",
  "request_id": "…",
  "ontology_release": {"company": "…", "persona": null},
  "dataset_revision": "…",
  "policy_version": "…",
  "query_plan_version": "…"
}
```

- **错误响应不携带版本固定块**：401/422 等错误多发生在版本解析或查询执行之前，此时 `dataset_revision` / `query_plan_version` 根本未参与——补上即伪造执行痕迹（违反认知诚实）。错误体只含错误语义（`code` / `detail`，422 附 validation report），`request_id` 经响应头 `X-Request-ID` 回显（RFC 7807 惯例：错误语义 + trace id）。该语义由契约测试固定（迭代 1）。

- **scenario 注册表**（唯一权威映射，四场景 id 以文档一 §5 为准）：

| scenario id | 默认 purpose | 场景 Profile / WorkPattern | 渲染重点 |
|---|---|---|---|
| `meeting_supervision` | decision_preparation | 会议督导 Profile | 分歧、证据、待确认项 |
| `strategic_research` | decision_preparation | 战略研究 Profile | 已知事实、缺口、反证 |
| `expert_panel` | decision_preparation | 专家团讨论 Profile | 支持与反证、盲区 |
| `task_followup` | mission_review | 任务跟进 Profile | Agreement、验收标准、上次问题 |

- **`dataset_revision` 按租户独立推进**：Key 即租户，版本固定块与 `base_dataset_revision` 均指该租户自己的 revision，租户间互不干扰。
- **Key 注册表**是运维配置制品（MVP：配置文件），字段：`key`、`tenant_scopes`、`role`、`on_behalf_of`（确认人/Persona 锚点）、`confirmer`（确认权）、`default_scenario`、`allowed_purposes`；变更本身记审计事件。
- 幂等语义：同一 `Idempotency-Key` 重放返回首次结果；同 Key 不同 payload 返回 `409`。
- 错误语义：`401` 未认证；`403` 无确认权 Key 提交 confirmed 写入或确认事件；`404` 无匹配或不可见（知识不可见即不存在，不泄漏存在性）；`409` 意图歧义（返回 alternatives 供确认——对应业务侧"越界先确认"）；`422` SHACL 校验失败（附 validation report）。

## 3. 出入参结构

### 3.1 `POST /v1/context-packs:resolve`

```json
// 请求（1 必填 + 全部可选默认化）
{
  "query": "灯塔项目与产品1.0能否同季交付",   // 必填，唯一必填项
  "scenario": "meeting_supervision",          // 可选：产品四场景之一，后端映射 purpose +
                                              // 场景 Profile + WorkPattern 加载 + 渲染模板；
                                              // 缺省按 Key 的默认场景
  "as_of": "2026-08-13",                      // 可选，默认服务器当前时间
  "render": true,                             // 可选，默认 false：附带 Markdown 渲染
  "token_budget": 4000                        // 可选，仅 render 时有意义
}
// Persona 锚点不是入参：由 Key 的 on_behalf_of 得出（敏感分区，参数即扩权面）
```

```json
// 响应（厚：审计与可复现性的承载处）
{
  "pack": {
    "pack_id": "…",
    "query_understanding": {"matched_root": "…", "alternatives": []},
    "scope_resolution": {"tenant": "tokenking", "contributing_graphs": []},
    "current_facts": [],
    "candidate_context": [],          // 保留 Candidate 标记与待确认边界
    "derived_claims": [],
    "conflicts": [],
    "context_gaps": [],
    "omissions": []                   // 含 stage=temporal_projection 的版本裁剪记录
  },
  "rendering": {"status": "completed|degraded|unavailable", "markdown": "…"},  // 仅 render:true
  "…版本固定块"
}
```

时序投影在响应侧生效：`role=cxo` 得 Judgement 全版本链；`role=executor` 仅得 Agreement 或链头（文档一 §4）。
渲染语义：Markdown 段落序固定（persona_context 规范）：当前事项 → 当前有效事实 → 相关原则 → 相似案例 → 已验证优势 → 历史盲区 → 支持与反证 → 未知与缺口 → 决策边界 → 输出要求。"相关原则"与"决策边界"两段由常驻宪法簇填充（见文档二 §9）。渲染只引用 Pack 成员 ID，不产生新事实；LLM 失败时 `degraded/unavailable`，结构化 Pack 照常返回。**Persona 包落地前**，“相似案例 / 已验证优势 / 历史盲区”三段为空并在 `context_gaps` 记录 persona 缺口（降级不造事实）。**不接受 client-supplied pack 输入**（已知门禁缺口，删除）。

### 3.2 响应消费分层（平台后端的二次解析约定）

| 分层 | 字段 | 处理方式 |
|---|---|---|
| **给 Agent 推理**（进 prompt） | `current_facts`、`candidate_context`、`derived_claims`、`conflicts`、`context_gaps`、`rendering.markdown` | 注入或二次裁剪 |
| **给平台后端**（编排与下次调用） | `dataset_revision`（→ 确认动作的 `base_dataset_revision`）、`candidate_ids` / `materialized_ids`（→ 界面确认引用）、`alternatives`（→ 歧义让用户选） | 后端消费，不进 prompt |
| **仅审计留存** | `pack_id`、版本固定块其余字段、`scope_resolution`、`omissions` 明细 | 落日志，按需回查 |

### 3.3 `GET /v1/assertions/{id}/lineage`

请求：路径参数 + 可选 `?depth=3`。
响应：`{"nodes": [{id, type, label, confirmation_status}], "edges": [{from, to, type}]}`，边类型 `supports | challenges | derives | confirms | supersedes | evaluates`。

- **可见性投影对 lineage 同样生效**：resolve 的硬过滤与时序投影是同一权威实现——executor Key 遍历不到被裁剪的 Judgement 版本（节点直接不出现，非打码），杜绝 lineage 成为投影后门。
- **"是否变好只看下一次"的对照机制**：FeedbackRecord 经 `evaluates` 边指向被评产出；下一次同场景产出经共同议题锚（`addressesIssue`）与时间序对照，不新增属性——lineage 按议题锚遍历即得"前次反馈 → 本次结果"链。

### 3.4 `POST /v1/submissions`

```json
// 请求头：Idempotency-Key: <幂等键>（必填）
{
  "type": "judgement_version",   // signal | issue | research_result | judgement_version |
                                 // agreement | mission | evidence | context_gap | feedback |
                                 // confirmation（延迟确认/拒绝既有候选）
  "payload": { "…": "待确认 content + 业务挂靠位置（挂哪个议题/任务），见 3.5" },
  "confirmation_status": "candidate",  // 可选，默认 candidate；confirmed = 界面已确认，
                                       // Runtime 原子补全 候选→确认→物化 全链
  "base_dataset_revision": "…",  // 条件必填：仅确认动作（confirmed / type=confirmation）
                                 // 需要——那里才有真实并发冲突面；纯追加类型不带
  "source_ref": "…"              // 可选：文档/会议记录锚点。缺省时溯源 = 提交活动本身
                                 // （Agent + 确认人 + 时间），不逼调用方编造来源
}
```

```json
// 响应
{
  "submission_id": "…",
  "status": "accepted_candidate | confirmed | rejected",
  "candidate_ids": ["…"],
  "materialized_ids": ["…"],        // 仅 confirmed：物化进 confirmed 图的断言
  "new_dataset_revision": "…",      // 仅 confirmed：物化后的新版本
  "validation_report": { "conforms": true, "violations": [] }
}
```

写入语义：

- 一切提交先成候选（append-only trig 事件），SHACL 门禁前置；确认动作 `base_dataset_revision` 过期返回 `409`；judgement 版本并发冲突由后端查 `supersedes` 目标是否仍为链头（payload 级检查，调用方无需带全局版本）。
- **调用方不指定物理图位置**：租户由 Key 得出，分区由 type 路由——业务挂靠位置在 payload，图 IRI 是后端内部事务。
- `confirmation_status=confirmed` 与 `type=confirmation` 要求 Key 有确认权（否则 `403`）；Persona 候选仅本人可确认。
- **双主体记录**：确认事件同时记录执行 Agent（Key 身份）与确认人（Key 的 `on_behalf_of` 主体）；口头确认与按钮在审计链等价。
- 不可变事件链 CandidateCreated → ValidationCompleted → ConfirmationRecorded / CandidateRejected → CurrentViewMaterialized，物化与 revision 推进原子完成（MVP：单写者 + append-only trig）。
- 已被确认/拒绝/替代的候选再次确认返回 `422`。

### 3.5 提交类型的最小 payload

| type | 最小字段 |
|---|---|
| `signal` | `statement`, `signal_source_type` |
| `issue` | `statement`, `informed_by`(signal ids) |
| `research_result` | `artifact_ref`, `addresses_issue`, `persona_pack_ref?`（生成时使用的个人本体 Pack id） |
| `judgement_version` | `statement`, `addresses_issue`, `supersedes?`(前版本 id), `supported_by`(evidence ids), `sourced_from`(会议 DecisionRecord id) |
| `agreement` | `adopts_judgement`, `agreement_status: close\|go_on` |
| `mission` | `mandated_by`(agreement id), `dri`, `acceptance_criteria` |
| `evidence` | `statement`, `supports \| challenges`(目标 id), `source_ref` |
| `context_gap` | `missing_what`, `blocking?`(被阻断对象 id) |
| `feedback` | `evaluates_target`, `quality_score?`, `experience_score?`, `gap_note?`（至少一个评分） |
| `confirmation` | `target_candidate_ids`, `action: confirm\|reject`, `note?` |

## 4. 场景 → API 调用序列（对齐产品说明四场景）

| 场景 | 调用序列 |
|---|---|
| 会议督导 | 会前 `resolve(render)`（预审 Pack）→ 会后 `submissions` × 五项产出（映射见文档一 §5）→ 界面呈现候选 → 一号位确认（inline confirmed 或 `type=confirmation`）→ `submissions type=feedback` |
| 战略研究 | `resolve(render)`（研究上下文）→ `submissions type=research_result` → 需要时进专家团讨论 |
| 专家团讨论 | `resolve(render)` → `submissions type=evidence / context_gap`（支持与反证、缺口） |
| 任务跟进 | Agreement go_on 后 `resolve`（Mission Context Pack 下发）→ 回看时 `submissions type=evidence / feedback` + 需落盘项界面确认 → `lineage` 验证上次问题是否复现 |

## 5. 兼容与演进

- 本设计相对现行实现是 v1 大版本内收敛：移除字段（`enterprise_id`、`organization_scope`、`purpose`、`persona_id`、render 的 `pack`）与独立 `:render` 端点（并入 resolve 的 `render` 选项）经一个过渡小版本标记 deprecated 后删除；新增字段全部可选默认化。
- OpenAPI/JSON Schema、正反契约测试与实现同步更新；每端点补一张标注 L5/L4/L2 职责切面的时序图。
- API 2（蒸馏）出现第二个高频蒸馏租户前不服务化。
