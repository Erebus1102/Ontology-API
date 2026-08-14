# 渲染时序图：render 并入 resolve（L5/L4/L2 职责切面）

权威代码：`src/tkos_runtime/api/server.py`（resolve 的 render:true 分支 + :render 端点的 deprecated client-supplied 路径）、`src/tkos_runtime/application/context_renderer.py`（`render()`）、`src/tkos_runtime/application/decision_context_compiler.py`（`DecisionContextCompiler`）、`src/tkos_runtime/api/serializer.py`（`pack_to_dict` / `dict_to_pack` / `attach_version_block`）。resolve 链本体见 `sequence-resolve.md`。

```mermaid
sequenceDiagram
    autonumber
    participant Client as Client (L5)
    participant API as server.py resolve / resolve_and_render handler (L5)
    participant Auth as api/auth.py assert_purpose (L5)
    participant Res as ContextPackResolver.resolve (L4)
    participant Render as context_renderer.render (L4)
    participant DCC as DecisionContextCompiler.compile (L4)
    participant Ser as serializer.pack_to_dict / dict_to_pack / attach_version_block (L5)

    Client->>API: POST /v1/context-packs:resolve，render:true（Bearer key，2.0 主线）
    API->>Res: resolve(query, purpose, as_of, …) → ContextPack（L4/L2 完整链，见 sequence-resolve.md）
    Res-->>API: ContextPack
    API->>Render: render(pack, mode="deterministic", format="markdown", max_chars=req.token_budget or 12000, language="zh-CN")
    Render->>DCC: compile(pack, max_chars)：slot 预算两遍分配 + 逐 section RenderedFactUnit
    DCC-->>Render: CompiledDecisionContext（超预算单元进入 render_omissions；RenderBudgetTooSmall → 422）
    Render-->>API: {render_schema_version, rendered{format, content, grounding_status, semantic_preservation, rendering_status, mode_used, warnings}, decision_context, metadata{pack_origin: server_resolved}}
    API->>Ser: result["structured"] = pack_to_dict(pack)；attach_version_block(result, request.state.request_id, pack)
    Ser-->>Client: 200 {rendered, structured, 六键版本块}（render 失败经共享映射抛 422/500 错误 detail：无渲染输出、无结构化 Pack；客户端可去掉 render:true 重试，resolve 主路径照常返回结构化 Pack）

    Note over Client, Ser: deprecated 旁路（过渡期仍接受、log warning、迭代 1 删除）：虚线仅示意 client-supplied pack 变体；resolve_request 变体（server_resolved）同 deprecated 保留

    Client-.->>API: POST /v1/context-packs:render，body {"pack": {…}}（deprecated）
    API-.->>API: log warning：deprecated render field: pack — use resolve render:true
    API-.->>Ser: dict_to_pack(req.pack)（治理字段 dataset_revision / ontology_release_id 缺失 → 422）
    Ser-->>API: ContextPack（admission.accept 默认 False，防伪造提升）
    API-.->>Auth: assert_purpose(pack.purpose, principal)（client-supplied pack 同样过用途门禁）
    API-.->>Render: render(pack, mode=opts.mode, format=opts.format, max_chars=opts.max_chars, language=opts.language, pack_origin="client_supplied")
    Render-->>API: metadata.pack_origin = client_supplied
    API-.->>Ser: attach_version_block(result, request.state.request_id, pack)
    Ser-->>Client: 200 {rendered, metadata.pack_origin: client_supplied}（opts.include_structured 时附 structured）
```

## L5 / L4 / L2 职责切面

- **L5（API 传输面）**：resolve handler 判定 `render:true` 分支并把 `rendered` + `structured` + 版本块装配为单一响应；deprecated 的 client-supplied `pack` 路径同样在 L5 被接受、记 warning 并保持可用（迭代 1 删除），且仍需通过 `assert_purpose` 门禁。
- **L4（Context & Reasoning Runtime）**：`render()` → `DecisionContextCompiler.compile` 把结构化 Pack 编译为 sectioned 事实单元，按字符预算两遍分配后组装 Markdown，超预算单元进入 `render_omissions`；渲染只引用 Pack 成员 ID，不产生新事实。
- **L2（Governed Knowledge Graph）**：渲染不触碰图存储——全部事实在 resolve 阶段已物化为 `ContextPack`；`structured` 随附 `rendered` 正是"结构化 Pack 是权威结果、Rendering 不产生新事实"的契约体现。
- **边界**：render 失败经共享映射 `_render_exception_to_http` 转 422/500（`render_budget_too_small` / 其他映射错误 detail），无 rendered 也无 structured 附随；resolve 主路径本身不受影响；LLM 模式只做润色且失败回退 deterministic，语义保留始终 `not_proven`。
