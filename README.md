# TKOS Ontology Runtime

`tkos-ontology-runtime` —— 面向企业一号位 Agent 的经营本体 Runtime。提供受用途、时间、确认状态与图分区准入的决策上下文（Context Pack），支撑战略闭环 `Signal → Issue → Research → Judgement 版本链 → Agreement → Mission`。

> 当前版本：**Runtime 2.0 基座**（分支 `runtime-2.0-foundation`，待合并部署；ECS 当前运行 1.0/P1.1 镜像 `115.190.213.44:8000`，cn-beijing）。
> 完整协作规则见 [CLAUDE.md](CLAUDE.md)；MVP 设计权威见 [`docs/mvp/`](docs/mvp/)。

## 当前能力

| 能力 | 端点 | 状态 |
|---|---|---|
| 议题 → 结构化 Context Pack（v1 形态：`scenario`/`render:true`/`token_budget` + 版本固定块） | `POST /v1/context-packs:resolve` | ✅ |
| Context Pack + Markdown 渲染 | resolve 的 `render:true`（独立 `:render` 标 deprecated，迭代 1 删除） | ✅ |
| 运维与健康 | `GET /health` `/ready` `/version` | ✅ |
| 认证授权 | Bearer + purpose 门禁 + Key 模型（tenant/role/on_behalf_of/confirmer/default_scenario，跨租户 404） | ✅ |
| 断言溯源 | `GET /v1/assertions/{id}/lineage` | ⏳ 迭代 1 |
| 候选写入与确认 | `POST /v1/submissions` | ⏳ 迭代 2 |

**P1.1 契约亮点**：解析器不再对并列候选兜底——得分与名称证据并列时返回 **409 歧义**（候选含本体 `type` + `matched_evidence`）；知识库未覆盖时返回 **404** 并附 `alternatives` 候选建议；命中根议题的 Pack 附 `intent_facets`（entity / requested_role / operation）。

**2.0 基座亮点**：V3.0 本体手术（`Agreement`/`FeedbackRecord`/`Product` 落地，`StrategicChoice`/`StrategicDecision`/`OperatingDecision` 删除，类数 104→104）；Key 即租户/角色/Persona 锚点，purpose 由 `scenario`/`default_scenario` 推导；响应统一携带版本固定块（`api_version`/`request_id`/`ontology_release`/`dataset_revision`/`policy_version`/`query_plan_version`，`X-Request-ID` 回显）；旧字段与独立 `:render` 进入 deprecated 过渡期（仍接受不 422），迭代 1 物理删除。

## 五层架构

```text
Layer 5  Agent & Application        企业 Agent、董办应用、项目团队工具
Layer 4  Context & Reasoning Runtime 意图解析、查询规划、推理、冲突检测、Context 编译与渲染
Layer 3  Ontology & Policy Model     OWL、SHACL、SWRL、场景 Profile、策略与查询模板
Layer 2  Governed Knowledge Graph    Current、Candidate、Provenance、Sensitive、Derived 命名图
Layer 1  Enterprise Source           飞书、文档、会议、业务系统、人工提交与 Agent 运行记录
```

模块化单体，通过四类版本化制品组合：`OntologyReleasePackage`、`AssertionEnvelope`、`CandidateAssertionBatch`、`ContextPack`。内部推理器、图库、向量检索、文档解析器、LLM 均经 Adapter 替换，不直接暴露为业务接口。

## 项目结构

```text
.
├── docs/
│   ├── mvp/                  MVP 权威设计（01 统一语言 / 02 本体 V3.0 / 03 API v1 / 04 2.0 基座迭代）
│   ├── api/                  OpenAPI 契约（权威）+ 历史草案
│   ├── architecture/         架构与部署设计
│   ├── decisions/  audits/  examples/
├── ontology/                 规范本体：schema(OWL/JSON-LD) · shapes(SHACL) · datasets(trig) · views(Protégé)
├── data/instances/           真实业务候选实例与确认事件
├── src/tkos_runtime/         可部署服务（api · application · domain · adapters）
├── tests/                    197 pytest + 5 门禁脚本 + Openllet SWRL
├── scripts/                  原型与维护脚本
├── deploy/ecs/               ECS 单节点部署（systemd + docker-run）
└── Makefile                  test / generate / install 聚合入口
```

本体命名空间：`https://ontology.tokenking.ai/tkos#`。

## 快速开始

```bash
# 1. 安装（开发 + API 依赖）
python3 -m pip install -e '.[dev]'

# 2. 测试（聚合，推荐）
make test-fast   # SHACL + Context Pack + 实例一致 + 模式同构 + Runtime/API/Harness（197 pytest）
make test        # 上述 + Openllet SWRL 验收（首次需 Maven 构建 Openllet CLI）

# 3. 重生成派生本体制品（编辑 JSON-LD 后必须）
make generate    # JSON-LD → Turtle → Protégé 视图

# 4. 启动本地 API
python3 -m uvicorn tkos_runtime.api.server:app --reload --port 8000
```

单独运行各套件：

```bash
python3 tests/run_v2_3_shacl.py              # SHACL 正负向
python3 tests/run_v2_3_context_pack.py       # Context Pack 读侧过滤
python3 tests/run_instance_conformance.py    # 真实实例硬门禁
python3 tests/run_schema_isomorphism.py      # JSON-LD ⇔ Turtle ⇔ Protégé 同构
python3 tests/run_v2_3_swrl_openllet.py      # Openllet SWRL 验收
python3 -m pytest tests/ -v                  # Runtime/API/Harness
```

GitHub Actions（`.github/workflows/ci.yml`）在 push/PR 时跑全部纯 Python 套件（必过），SWRL 为信息性 job。

## 契约与验证

- **OpenAPI**：[`docs/api/tkos-runtime-openapi.yaml`](docs/api/tkos-runtime-openapi.yaml)（v0.2.0：v1 形态 `scenario`/`render`/`token_budget` + 版本块 schema + 旧字段 deprecated 标注；含 P1.1 的 409/404/`intent_facets` 与 `/version` 指纹）。
- **Apifox**：项目 `8708985`「Tokenking」，AI 分支 `ai/20260813-from-main-tkos-runtime-api`（5 端点 + 指南文档 v1 收敛 + 17 测试用例，v1 双轨）。
- **Agent 契约验证**：`scripts/agent_harness.py` 作为独立 HTTP 客户端模拟 Agent 消费 Context Pack（不导入内部模块，纯 HTTP）。

```bash
python3 scripts/agent_harness.py
python3 scripts/resolve_issue_context.py \
  --query '是否在本季度同时完成产品 1.0 上线和灯塔项目交付'
```

> 真实 CEO-Agent 端到端联调（Agent 消费 Pack、注入 User Prompt、输出引用 Pack member ID）仍在后续阶段。

## 部署

ECS 单节点试点（cn-beijing，公网 `115.190.213.44:8000`，HTTP 受控联调；正式使用前切 HTTPS）。部署制品与流程见 [`deploy/ecs/`](deploy/ecs/)：

- 镜像 `tkos-runtime:<code_sha>-<dataset_revision>`（ECS 当前实际运行 `bce5ab8-29249ff944020a02`，V2.4.1 状态；2.0 基座合并后按 `docs/mvp/05` 部署）
- `tkos-runtime.service`（systemd）+ `docker-run.sh`
- `env.production.example`（`TKOS_API_KEY` 等只入 `.env`，不入仓库）

## 路线图

| 阶段 | 内容 | 文档 |
|---|---|---|
| 1.0（已交付） | resolve + render 读路径、authN/authZ、ECS 部署、P1.1 歧义/缺口契约 | — |
| **2.0 基座（已实现，待合并部署）** | V3.0 本体手术 + v1 契约对齐（deprecated 过渡）+ Key 模型（lineage / submissions 的共同前置） | [`docs/mvp/04`](docs/mvp/04-iteration-2.0-foundation.md) |
| 迭代 1 | `lineage` 端点 + 角色时序投影（验收 5/7） | `docs/mvp/03` §3.3 |
| 迭代 2 | `submissions` 写入闭环 + 9 类提交 + 确认/物化（验收 1-4/6） | `docs/mvp/03` §3.4 |
| 后续 | 在线推理、异步蒸馏 Job、Persona 本体包、真实 Agent 联调 | `docs/mvp/01` §6 |

## 规范制品

- `ontology/schema/tkos-ontology.jsonld` —— 人工编辑源（紧凑 @context、多语言 label）
- `ontology/schema/tkos-ontology.ttl` —— 推理器规范 Turtle（`scripts/export_schema_ttl.py` 生成，保留 imports）
- `ontology/shapes/tkos-validation-shapes.jsonld` —— SHACL 约束
- `ontology/datasets/tkos-runtime-dataset.trig` —— 命名图运行契约
- `ontology/views/tkos-ontology-protege-view.ttl` —— 去 imports 的 Protégé 副本（`scripts/export_protege_view.py` 生成）

编辑任一本体源后用 `make generate` 重生成派生制品，否则 `run_schema_isomorphism.py` 同构守卫会失败。
