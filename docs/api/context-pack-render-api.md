# Context Pack 查询与渲染 API

## 1. 接口用途

该接口接收一个企业议题或自然语言查询，完成本体对象匹配、Context Pack 查询、决策上下文编译和 Markdown 渲染。

Agent 通常消费：

- `rendered.content`：可直接注入 Agent User Prompt 的决策上下文。
- `decision_context`：供 Agent 程序、前端页面和后续工作流读取的结构化决策信息。
- `structured`：可选返回的完整结构化 Context Pack，用于审计、调试和进一步查询。

接口不会生成结构化 Context Pack 之外的新业务事实。自然语言内容保留认知状态、成员 ID、数据分区和来源图锚点。

## 2. 接口定义

```http
POST /v1/context-packs:render
Authorization: Bearer <TKOS_API_KEY>
Content-Type: application/json
```

本地开发地址：

```text
http://127.0.0.1:8000/v1/context-packs:render
```

## 3. 认证

业务接口使用 Bearer Token：

```http
Authorization: Bearer <TKOS_API_KEY>
```

服务端通过以下环境变量配置凭据：

- `TKOS_API_KEY`：单个 API Key。
- `TKOS_API_KEYS_JSON`：多个 API Key 及其允许用途。

缺少或无效 Token 返回 `401`；调用方无权使用请求中的 `purpose` 时返回 `403`。

## 4. 请求方式

接口支持两种互斥的输入方式：

1. `resolve_request`：提交议题，由服务端查询本体后渲染。Agent 首次查询推荐使用。
2. `pack`：提交此前 `/v1/context-packs:resolve` 返回的完整 Context Pack，再执行渲染。

一次请求必须且只能提供其中一种。

## 5. 使用议题查询并渲染

### 5.1 请求示例

```json
{
  "resolve_request": {
    "enterprise_id": "tokenking",
    "organization_scope": [
      "tokenking",
      "fe"
    ],
    "purpose": "decision_preparation",
    "query": "是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
    "as_of": "2026-08-12T12:00:00+08:00",
    "actor_id": "ceo-agent"
  },
  "render_options": {
    "mode": "deterministic",
    "format": "markdown",
    "language": "zh-CN",
    "max_chars": 6000,
    "include_structured": true
  }
}
```

### 5.2 请求字段

| 字段 | 类型 | 必填 | 说明 |
|---|---|---:|---|
| `resolve_request.enterprise_id` | string | 是 | 企业标识。当前运行时接收该字段，组织隔离仍以响应中的 `scope_resolution` 为准。 |
| `resolve_request.organization_scope` | string[] | 否 | 本次查询声明的组织范围，例如集团、子公司、Domain 或项目。默认空数组。 |
| `resolve_request.purpose` | string | 是 | 查询用途。调用方必须拥有该用途的访问权限；用途同时参与允许读取图的计算。 |
| `resolve_request.query` | string | 是 | 企业议题、查询文本或可匹配本体对象的关键词。 |
| `resolve_request.as_of` | string | 是 | 查询采用的时间截面，使用 ISO 8601 格式并携带时区，例如 `+08:00` 或 `Z`。 |
| `resolve_request.actor_id` | string | 否 | 发起请求的 Agent 或业务主体标识。 |
| `render_options.mode` | enum | 否 | `deterministic`、`llm_with_fallback` 或 `llm_required`，默认 `deterministic`。 |
| `render_options.format` | enum | 否 | 当前仅支持 `markdown`。 |
| `render_options.language` | string | 否 | 输出语言，默认 `zh-CN`。 |
| `render_options.max_chars` | integer | 否 | Markdown 字符预算，允许范围为 100 至 100000，默认 12000。动态必需内容超过预算时返回 `422`。 |
| `render_options.include_structured` | boolean | 否 | 是否在响应中同时返回完整结构化 Context Pack，默认 `false`。 |

### 5.3 渲染模式

| 模式 | 行为 |
|---|---|
| `deterministic` | 使用确定性 Decision Context Compiler 分节、命名、人性化关系和分配预算，不调用大模型。 |
| `llm_with_fallback` | 在确定性结果上调用大模型润色；润色不可用或结构校验失败时返回确定性结果。 |
| `llm_required` | 要求完成大模型润色；依赖不可用或校验失败时请求失败。 |

## 6. curl 调用示例

```bash
curl -sS -X POST 'http://127.0.0.1:8000/v1/context-packs:render' -H 'Authorization: Bearer YOUR_TKOS_API_KEY' -H 'Content-Type: application/json' --data '{"resolve_request":{"enterprise_id":"tokenking","organization_scope":["tokenking","fe"],"purpose":"decision_preparation","query":"是否在本季度同时完成产品 1.0 上线和灯塔项目交付","as_of":"2026-08-12T12:00:00+08:00","actor_id":"ceo-agent"},"render_options":{"mode":"deterministic","format":"markdown","language":"zh-CN","max_chars":6000,"include_structured":true}}'
```

只打印 Markdown：

```bash
curl -sS -X POST 'http://127.0.0.1:8000/v1/context-packs:render' -H 'Authorization: Bearer YOUR_TKOS_API_KEY' -H 'Content-Type: application/json' --data '{"resolve_request":{"enterprise_id":"tokenking","organization_scope":["tokenking","fe"],"purpose":"decision_preparation","query":"是否在本季度同时完成产品 1.0 上线和灯塔项目交付","as_of":"2026-08-12T12:00:00+08:00"},"render_options":{"mode":"deterministic","max_chars":6000}}' | python3 -c "import json,sys; print(json.load(sys.stdin)['rendered']['content'])"
```

## 7. 成功响应

### 7.1 响应结构

```json
{
  "render_schema_version": "context-render/2.0",
  "rendered": {},
  "decision_context": {},
  "metadata": {},
  "structured": {}
}
```

`structured` 仅在 `include_structured=true` 时返回。

### 7.2 响应示例

以下响应为字段和内容节选。实际成员数量、候选状态、来源、数据版本和省略项取决于查询时间与当前数据集。

```json
{
  "render_schema_version": "context-render/2.0",
  "rendered": {
    "format": "markdown",
    "content": "# 决策上下文：是否在本季度同时完成产品 1.0 上线和灯塔项目交付\n\n> 已确认事实 0 项，候选视图 73 项（其中信息缺口 8 项），溯源视图 15 项。\n\n# 决策议题\n\n- 是否在本季度同时完成产品 1.0 上线和灯塔项目交付…… [member:issue-product1-lighthouse-synchronous-delivery][partition:graph-candidate-and-dispute][source:graph-candidate-and-dispute]\n\n## 决策目标\n\n- 让灯塔项目常态化高质量使用 CEO Agent……\n- 产品 1.0 网页版本上线……\n\n## 当前进展与已有证据\n\n- 产品 1.0 四个组件处于 MVP 产出阶段……\n\n## 共同依赖与约束\n\n- 产品上线、客户采用与 FE Context 存在同步依赖……\n\n## 当前最重要的风险\n\n- 产品上线和灯塔交付存在资源冲突风险……\n\n## 拍板前需要补齐的信息\n\n- 产品 1.0 MVP 尚缺正式验收结果 [Candidate] [member:gap-product1-mvp-acceptance][partition:graph-candidate-and-dispute][source:graph-candidate-and-dispute]\n\n## 决策与判断依据\n\n- 采用 CEO Agent 优先的词元云集与房懂懂双场景验证路径……\n\n### 省略 53 项（milestone×8, risk×6）\n\n---\npack_id: `context-pack-decision_preparation` | ontology: 2.4.0 | renderer: context-renderer/p0-v1",
    "grounding_status": "structurally_validated",
    "semantic_preservation": "not_proven",
    "rendering_status": "completed",
    "mode_requested": "deterministic",
    "mode_used": "deterministic",
    "warnings": [
      "53 member(s) omitted due to max_chars=6000"
    ]
  },
  "decision_context": {
    "compiler_version": "decision-context/v1",
    "issue": {
      "view_key": [
        "issue-product1-lighthouse-synchronous-delivery",
        "graph-candidate-and-dispute"
      ],
      "member_id": "issue-product1-lighthouse-synchronous-delivery",
      "name": "是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
      "query": "是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
      "matched_root": "https://ontology.tokenking.ai/tkos#issue-product1-lighthouse-synchronous-delivery",
      "partition": "graph-candidate-and-dispute",
      "source_graphs": [
        "graph-candidate-and-dispute"
      ],
      "epistemic_summary": "已确认事实 0 项，候选视图 73 项（其中信息缺口 8 项），溯源视图 15 项。"
    },
    "outcomes": [
      {
        "view_key": [
          "outcome-lighthouse-ceo-agent-routine-use-2026-08",
          "graph-candidate-and-dispute"
        ],
        "member_id": "outcome-lighthouse-ceo-agent-routine-use-2026-08",
        "name": "让灯塔项目常态化高质量使用 CEO Agent",
        "claim": "让灯塔项目常态化高质量使用 CEO Agent……",
        "epistemic_status": "Candidate",
        "partition": "graph-candidate-and-dispute",
        "source_graphs": [
          "graph-candidate-and-dispute"
        ]
      }
    ],
    "progress": [],
    "dependencies": [],
    "risks": [],
    "evidence": [],
    "gaps": [
      {
        "view_key": [
          "gap-product1-mvp-acceptance",
          "graph-candidate-and-dispute"
        ],
        "member_id": "gap-product1-mvp-acceptance",
        "name": "产品 1.0 MVP 尚缺正式验收结果",
        "claim": "产品 1.0 MVP 尚缺正式验收结果",
        "epistemic_status": "Candidate",
        "partition": "graph-candidate-and-dispute",
        "source_graphs": [
          "graph-candidate-and-dispute"
        ]
      }
    ],
    "decisions": [],
    "secondary": [],
    "derived": [],
    "render_omissions": [
      {
        "member_id": "milestone-fe-m2-loop",
        "partition": "graph-candidate-and-dispute",
        "role": "milestone",
        "tier": "2",
        "reason": "max_chars_exceeded",
        "incident_edges": 0
      }
    ],
    "warnings": [],
    "epistemic_summary": "已确认事实 0 项，候选视图 73 项（其中信息缺口 8 项），溯源视图 15 项。"
  },
  "metadata": {
    "context_pack_id": "context-pack-decision_preparation",
    "dataset_revision": "<SHA-256>",
    "ontology_release_id": "2.4.0",
    "renderer_version": "context-renderer/p0-v1",
    "pack_origin": "server_resolved"
  },
  "structured": {
    "pack_id": "context-pack-decision_preparation",
    "matched_root": "https://ontology.tokenking.ai/tkos#issue-product1-lighthouse-synchronous-delivery",
    "current_facts": [],
    "candidate_context": [
      "<完整成员对象，示例省略>"
    ],
    "context_gaps": [
      "<完整成员对象，示例省略>"
    ],
    "provenance_context": [
      "<完整成员对象，示例省略>"
    ]
  }
}
```

## 8. 关键响应字段

### 8.1 `rendered`

| 字段 | 说明 |
|---|---|
| `content` | 按决策作用分节的 Markdown，可注入 Agent Prompt。 |
| `grounding_status` | 当前为 `structurally_validated`，表示成员、分区、章节、来源、状态标签、数字和 URI 已通过结构校验。 |
| `semantic_preservation` | 当前固定为 `not_proven`，表示纯文本的语义等价无法仅凭结构校验得到证明。 |
| `rendering_status` | 渲染执行状态。成功时为 `completed`。 |
| `mode_requested` | 调用方请求的渲染模式。 |
| `mode_used` | 实际采用的渲染路径。LLM 失败并降级时为 `deterministic_fallback`。 |
| `warnings` | 降级、预算省略或 LLM 校验结果。 |

### 8.2 `decision_context`

| 字段 | 说明 |
|---|---|
| `issue` | 与 `matched_root` 对齐的根议题。 |
| `outcomes` | 与议题有关的结果与目标。 |
| `progress` | 当前进展与进度快照。 |
| `dependencies` | 共同依赖、约束和责任关系。 |
| `risks` | 当前 Pack 中与议题相关的风险。 |
| `evidence` | 支持或挑战相关判断的证据。 |
| `gaps` | 拍板前需要补齐的信息。 |
| `decisions` | 已有 Decision、研究、判断或理由。 |
| `secondary` | Mission、Criterion、Milestone 等次级上下文。 |
| `derived` | 已物化的派生信息。 |
| `render_omissions` | 因字符预算、层级或呈现策略未进入 Markdown 的完整条目。 |
| `epistemic_summary` | 按视图计算的确认状态分布，不包含系统生成的业务结论。 |

每个正文事实使用 `view_key = [member_id, partition]` 作为视图主键。Markdown 行尾保留三段锚点：

```text
[member:<member_id>][partition:<graph_partition>][source:<source_graph>]
```

### 8.3 `metadata`

| 字段 | 说明 |
|---|---|
| `context_pack_id` | 本次 Context Pack 标识。 |
| `dataset_revision` | 本次查询使用的数据集内容哈希。 |
| `ontology_release_id` | 本次查询固定的本体发布版本。 |
| `renderer_version` | 渲染器实现版本。 |
| `pack_origin` | `server_resolved` 或 `client_supplied`。 |

## 9. 使用已有 Context Pack 渲染

调用方可以先请求：

```http
POST /v1/context-packs:resolve
```

再把该接口返回的完整 JSON 放入 `pack`：

```json
{
  "pack": {
    "pack_id": "context-pack-decision_preparation",
    "purpose": "decision_preparation",
    "dataset_revision": "<SHA-256>",
    "ontology_release_id": "2.4.0",
    "current_facts": [],
    "candidate_context": [],
    "provenance_context": [],
    "context_gaps": []
  },
  "render_options": {
    "mode": "deterministic",
    "max_chars": 6000
  }
}
```

客户端 Pack 至少需要合法的 `dataset_revision` 和 `ontology_release_id`。正式使用时应原样传递 `/resolve` 返回的完整 Pack，避免丢失成员关系、来源和状态。

## 10. 错误响应

### 10.1 未认证

```http
HTTP/1.1 401 Unauthorized
```

```json
{
  "detail": "missing or malformed bearer token"
}
```

### 10.2 用途不允许

```http
HTTP/1.1 403 Forbidden
```

```json
{
  "detail": "purpose 'decision_preparation' not permitted for principal 'restricted-agent'"
}
```

### 10.3 未匹配到本体对象

```http
HTTP/1.1 404 Not Found
```

```json
{
  "detail": "<no-match message>"
}
```

### 10.4 字符预算不足

当 `max_chars` 无法容纳根议题、必需结果、全部 Gap 和固定结构时返回：

```http
HTTP/1.1 422 Unprocessable Entity
```

```json
{
  "detail": {
    "code": "render_budget_too_small",
    "requested_max_chars": 500,
    "minimum_required_chars": 1378
  }
}
```

### 10.5 输入方式冲突

同时提供 `pack` 与 `resolve_request`，或两者均未提供时返回 `422`。

## 11. Agent 接入建议

Agent 的推荐调用顺序：

1. 使用 `resolve_request` 提交议题。
2. 检查 HTTP 状态码和 `rendered.rendering_status`。
3. 把 `rendered.content` 放入本次任务的企业上下文区域。
4. 根据 `decision_context.gaps` 生成待补充问题。
5. 根据 `view_key` 或 `member_id` 发起后续来源追溯。
6. 保存 `context_pack_id`、`dataset_revision` 和 `ontology_release_id`，确保最终回答可复现。

Prompt 注入示例：

```text
以下为 TKOS Runtime 根据当前议题返回的企业决策上下文。
请保留其中 Current、Candidate 与 Gap 的认知状态边界。
引用业务事实时保留对应 member ID，不得补造 Context Pack 之外的事实。

<TKOS_CONTEXT>
{{ rendered.content }}
</TKOS_CONTEXT>
```

`decision_context` 适合程序消费和页面展示；`structured` 适合审计与深度查询。完整 `structured` 通常不需要注入 Prompt。

## 12. 当前边界

- `organization_scope` 当前会进入 Context Pack 的作用域解析结果，运行时仍会明确返回实际执行状态。
- `grounding_status=structurally_validated` 表示结构约束通过，不表示自然语言语义等价已经得到形式证明。
- `semantic_preservation=not_proven` 是当前渲染链路的固定诚实边界。
- `reasoning_status` 反映当前 Pack 是否读取到已物化派生结果；在线请求不会临时重新运行 SWRL 推理。
- `render_omissions` 中的条目仍属于 Context Pack，只是没有进入受字符预算约束的 Markdown。

当前版本还有两项已知工程门禁：

- 客户端直接提交 `pack` 的路径需要补齐基于 `pack.purpose` 的授权校验。完成前，生产 Agent 应使用 `resolve_request` 路径。
- 真实 FE 议题的 6000 字预算已经通过；极长根议题、极长 Gap ID 等通用边界仍需完成精确 mandatory-floor 校验。生产调用方应检查实际 `rendered.content` 长度，并保留 `422 render_budget_too_small` 的处理分支。
