# 部署硬阻拦项修复设计（健康检查端点 + authN/authZ 最小切片）

> 状态：设计稿（**只设计，不改源码，不执行部署**）
> 范围：补齐 [volcengine-deployment-design.md](./volcengine-deployment-design.md) §6.3、§12 标注的两个部署前硬阻拦项的代码层修复方案
> 日期：2026-08-12
> 配套文档：[volcengine-deployment-design.md](./volcengine-deployment-design.md)（部署设计）、[api-contracts-v1.md](../api/api-contracts-v1.md)（API 契约）、[runtime-architecture.md](./runtime-architecture.md)

---

## 0. 文档定位

火山引擎部署设计文档已明确两个**部署前硬阻塞**（§6.3、§12、§13），但该文档声明"本设计不实施"代码补丁。本文档承接这一缺口，给出两项修复的**代码层设计**（函数级签名 + 行为 + 接入点），仍不实施、不部署。

两项阻拦项：

| # | 阻拦项 | 部署设计的出处 | 后果 |
|---|---|---|---|
| B1 | `src/tkos_runtime/api/server.py` 无 `/health`、`/ready`、`/version` | §6.3、§13 | VKE livenessProbe / readinessProbe / startupProbe 与 LB 健康检查无目标；滚动更新无门控 |
| B2 | 无 authN/authZ；sensitive 图访问控制缺位 | §12、§12.2、§12.3 | 公网暴露后任意调用方可读企业经营本体；401/403 已在契约定义但运行时未实现 |

阅读顺序：§1 现状基线 → §2 方案 A（健康端点）→ §3 方案 B（authN/authZ）→ §4 测试设计（信息性）→ §5 待确认项 → §6 决策摘要。

---

## 1. 现状基线（ground in code，设计依据）

| 维度 | 现状事实 | 来源 |
|---|---|---|
| 应用工厂 | `create_app(store=None) -> FastAPI`，模块级 `app = create_app()` | `server.py:64-167, 171` |
| Store 装载时机 | **同步**：`create_app` 内 `store = _default_store()` → `_build_resolver(store)`，函数返回前 Store 已构建完毕 | `server.py:70-72` |
| 模块级 app | 导入即装载图。gunicorn `-w 2` 不用 `--preload` 时，每个 worker 各自导入 → 各装载一份内存图 | `server.py:171`，部署设计 §6.1 |
| 现有端点 | 仅 `POST /v1/context-packs:resolve`、`POST /v1/context-packs:render` | `server.py:75, 100` |
| 版本指纹（已存在） | `store.ontology_release_id`（OWL versionInfo，如 `"2.4.0"`）、`store.dataset_revision`（数据文件 sha256） | `rdflib_dataset_store.py:31, 34` |
| 策略/计划/renderer 版本 | `policy_version="read-admission/p0-v1"`（硬编码）、`query_plan_version="bfs-2gram/p0-v1"`、`RENDERER_VERSION="context-renderer/p0-v1"` | `context_compiler.py:53`、`domain/query_plan.py:5`、`application/context_renderer.py:24` |
| app version | `FastAPI(..., version="0.1.0")` | `server.py:73` |
| 准入策略 | `AdmissionPolicy.allowed_graphs(self, purpose, registered, restricted) -> list[str]`；Store 包装为单参 `store.allowed_graphs(purpose)` | `policies.py:17`、`rdflib_dataset_store.py:69` |
| purpose 白名单 | `_DEFAULT_PURPOSE_ALLOWED`：`decision_preparation` / `mission_review` → 图白名单 | `policies.py:6-9` |
| sensitive 图过滤 | `restricted_partition_ids = {"graph-sensitive-persona"}` 恒定排除；`restricted_node_ids` 在 `_ok()` 中过滤 subject/object | `rdflib_dataset_store.py:13, 29-30, 75-76` |
| `.env` 机制 | 模块顶部 `load_dotenv(_ENV_PATH)`，缺失/无库时 no-op；默认 `override=False`（编排系统注入的值优先） | `server.py:22-29` |
| 请求模型 | `ResolveRequest` 已有 `actor_id: Optional[str]`、`purpose: str`、`organization_scope: List[str]` 字段（**未做校验**） | `models.py:15-22` |
| 错误码契约 | `401 身份缺失`、`403 组织或用途不允许` 已定义但未实现；现有实现仅 422/404/500 | `api-contracts-v1.md`、`server.py:79-161` |
| 测试约定 | `TestClient(create_app())` 端到端测；BASE_REQ 含 `actor_id="agent-harness"` | `tests/test_runtime_api.py` |

**对设计影响最大的三条**：

1. **Store 同步装载在 `create_app` 内完成**——`/ready` 的 503 窗口在当前代码下实际上等于"模块尚未导入完成"。readiness 标志的真实价值在于：(a) 启动 SHACL 门禁（部署设计 §5.1）、(b) 未来迁到 lifespan 懒装载、(c) 优雅停机 drain。设计须对这三种语义都前向兼容。
2. **`actor_id`、`purpose`、`organization_scope` 已在请求模型中**——authZ 的"身份→purpose→图"链条的入参通道已就绪，只缺"身份→允许 purpose 集"的绑定。
3. **`graph-sensitive-persona` 已在 `restricted_partition_ids` 恒定排除**——这是**读侧过滤，不是访问控制**（部署设计 §12.3 明确）。authZ 落地前，sensitive 实例数据须在**构建期**排除出部署 bundle。

---

## 2. 方案 A：健康检查端点（B1）

### A.1 设计约束

- **C-A1**：三个端点必须在 `create_app` 返回的 `app` 上注册（不能只挂在模块级 `app`，否则 `create_app(store=...)` 测试入口拿不到）。
- **C-A2**：`/ready` 必须能反映"Store 已装载且（可选）启动 SHACL 已通过"——即便当前同步装载下窗口很短，也要为 lifespan 懒装载/SHACL 门禁留扩展点。
- **C-A3**：`/version` 必须返回部署设计 §8.2 所述的三个内容指纹（`ontology_release_id`、`dataset_revision`、`code_sha`），供部署后核对"线上跑的是哪份制品"。
- **C-A4**：健康端点不能引入会拖垮探针的依赖（如 LLM、外部网络）——必须本地、O(1)、<10ms。
- **C-A5**：与部署设计 §6.3 已给出的探针映射保持一致（livenessProbe→`/health`、readinessProbe→`/ready`、startupProbe→`/ready`）。

### A.2 推荐默认

**三个独立 GET 端点 + 模块级 readiness 标志 + `/version` 聚合已存在指纹。**

| 端点 | 语义 | 成功 | 失败 |
|---|---|---|---|
| `GET /health` | liveness：进程事件循环活着 | `200 {"status":"ok"}` | （不返回 5xx；进程死了探针连不上，由 TCP 层判定） |
| `GET /ready` | readiness：Store 装载完成（+ 可选启动 SHACL 通过） | `200 {"status":"ready","checks":{...}}` | `503 {"status":"not_ready","reason":...}` |
| `GET /version` | 版本指纹聚合 | `200 {ontology_release_id, dataset_revision, code_sha, policy_version, query_plan_version, renderer_version, app_version}` | （不失败） |

**理由**：

- **三端点分离**而非合一是 VKE/K8s 探针的标准契约——liveness 失败应重启进程，readiness 失败应摘流量，二者语义不能耦合（部署设计 §6.4：优雅停机时 readiness 应先转 False 而 liveness 仍 200，否则会被误杀）。
- **readiness 用模块级标志**而非"尝试解析一个请求"——前者 O(1) 且无副作用，后者会触发图装载以外的故障路径。
- **`/version` 聚合已有指纹**而非新算——`store.ontology_release_id` / `store.dataset_revision` 在 Store 构造时已计算（§1），直接复用；`code_sha` 由构建期注入（见 A.3）。

### A.3 端点规格

#### `GET /health`（liveness）

- **行为**：无条件返回 200。仅证明"uvicorn worker 事件循环在跑、能接受连接"。
- **不做**：不查 Store、不查 LLM、不查外部依赖。
- **响应体**（保持小，避免探针日志膨胀）：
  ```json
  {"status": "ok"}
  ```

#### `GET /ready`（readiness）

- **行为**：读模块级 readiness 标志。标志在 `create_app` 内 Store 构建完成（及可选启动 SHACL 通过）后置 True。
- **响应体（200）**：
  ```json
  {"status": "ready", "checks": {"store_loaded": true, "startup_shacl": "pass|skipped"}}
  ```
- **响应体（503）**：
  ```json
  {"status": "not_ready", "reason": "store_loading|startup_shacl_failed|draining"}
  ```
- **优雅停机扩展点**（v1 可选，v1.1 推荐）：SIGTERM 信号处理函数把 readiness 置 False（reason=`draining`），让 LB 先摘流量再杀进程——与部署设计 §6.4 的 graceful-timeout 语义配合。

#### `GET /version`（版本指纹）

- **行为**：聚合 Store 上已有的指纹 + 构建期注入的 `code_sha` + 各组件版本常量。
- **响应体**：
  ```json
  {
    "ontology_release_id": "2.4.0",
    "dataset_revision": "<sha256 hex 前 16 位>",
    "code_sha": "<git sha 或 build id，来自环境变量>",
    "policy_version": "read-admission/p0-v1",
    "query_plan_version": "bfs-2gram/p0-v1",
    "renderer_version": "context-renderer/p0-v1",
    "app_version": "0.1.0"
  }
  ```
- **指纹来源**：
  - `ontology_release_id`、`dataset_revision`：`store.ontology_release_id` / `store.dataset_revision`（§1）。
  - `policy_version` / `query_plan_version`：从 `context_compiler.py` 的硬编码或 `domain/query_plan.py:QUERY_PLAN_VERSION` 常量读取（不要复制字面量，要引常量）。
  - `renderer_version`：`application/context_renderer.py:RENDERER_VERSION` 常量。
  - `code_sha`：读环境变量 `TKOS_CODE_SHA`（构建期由 CI 注入；缺失时返回 `"unknown"`，不报错）。
  - `app_version`：`app.version`（FastAPI 已挂在 `server.py:73`）。

### A.4 readiness 标志机制

**推荐默认：模块级 `_RuntimeState` 容器 + `create_app` 末尾置位。**

接入点（**函数级签名**，不写实现）：

```python
# server.py 模块级（新增）
class _RuntimeState:
    """Per-worker runtime state for health/readiness probes."""
    ready: bool = False
    startup_shacl_status: str = "skipped"  # "pass" | "fail" | "skipped"

_state = _RuntimeState()

def _ready() -> bool:
    """Readiness gate: True only after Store loaded (+ optional startup SHACL pass)."""
    return _state.ready
```

在 `create_app` 内（**接入点**：`server.py:72` 之后、`return app` 之前）：

```python
def create_app(store=None) -> FastAPI:
    if store is None:
        store = _default_store()
    resolver = _build_resolver(store)
    app = FastAPI(...)

    # ── readiness 置位（新增）──
    # 可选：启动 SHACL 门禁（部署设计 §5.1），由 env TKOS_STARTUP_SHACL=1 开启
    _state.startup_shacl_status = _run_startup_shacl_if_enabled(store)  # "pass"|"fail"|"skipped"
    _state.ready = (_state.startup_shacl_status != "fail")

    # ── 健康端点注册（新增）──
    _register_health_routes(app, store, _state)

    @app.post("/v1/context-packs:resolve")  # 现有
    ...
    return app
```

**关键行为**：

- `_run_startup_shacl_if_enabled(store)`：读 `os.environ.get("TKOS_STARTUP_SHACL")`；为 `"1"` 时在本地跑 pyshacl（当前数据量亚秒级），失败返回 `"fail"` 且 `_state.ready=False`——Pod 不接流量（部署设计 §5.1 的 defense-in-depth）；默认 `"skipped"`（最小切片不强制）。
- `_register_health_routes(app, store, state)`：注册三个 GET 端点的辅助函数（见 A.7），避免 `create_app` 主体膨胀。
- 模块级 `app = create_app()`（`server.py:171`）保持不变——导入完成即 `_state.ready=True`（除非启动 SHACL 失败）。

**前向兼容**（不在 v1 实施，仅留接入点）：

- 迁到 FastAPI `lifespan` 异步事件时，Store 装载移入 `lifespan` 的 startup 阶段，`_state.ready` 在 startup 末尾置位——`/ready` 端点与探针配置零改动。
- 优雅停机时，SIGTERM handler 置 `_state.ready=False`（reason=`draining`）——`/ready` 立即 503，LB 摘流量，配合 gunicorn `--graceful-timeout`（部署设计 §6.1）。

### A.5 VKE 探针 / LB 健康检查对接语义

与部署设计 §6.3 保持一致并补全建议值：

| 探针 | 端点 | `periodSeconds` | `timeoutSeconds` | `failureThreshold` | `initialDelaySeconds` | 说明 |
|---|---|---|---|---|---|---|
| livenessProbe | `GET /health` | 10 | 2 | 3 | 0 | 进程死则 kubelet 连不上，TCP 层判失败；~30s 重启 |
| readinessProbe | `GET /ready` | 5 | 2 | 3 | 0 | 装载完即 200，摘流量 <15s |
| startupProbe | `GET /ready` | 2 | 2 | 30 | 0 | 给冷启动 + 启动 SHACL 最多 60s（`failureThreshold × periodSeconds`） |

- **ALB/CLB 健康检查**（部署设计 §6.2）：指向 `GET /health`（LB 通常只支持单路径健康检查，选 liveness 路径即可；LB 不关心 readiness 的 SHACL 状态）。
- **startupProbe 必须用 `/ready` 而非 `/health`**：否则进程一启动就过 startup，但 Store 还在装载，readinessProbe 会在装载窗口内连续 503 触发误告警。startupProbe 的 `failureThreshold=30, periodSeconds=2` 给足 60s 装载裕量（当前 148K 亚秒级，但前向兼容数据增长）。

### A.6 健康端点鉴权策略

**推荐默认：`/health`、`/ready` 不鉴权；`/version` 鉴权或仅内网可达。**

**理由**：

- `/health`、`/ready` 必须不鉴权——VKE kubelet 探针不带凭证；若加鉴权，探针 401 → 判不健康 → Pod 被重启/摘流量。
- `/version` 暴露构建指纹（`code_sha`、`dataset_revision`），对攻击者有价值（指纹识别、定向攻击）。**应鉴权**（用 §3 的 `require_token`）或通过网络层限制（仅 ALB 内网 / VPC 内可达）。

**防滥用（`/health`、`/ready` 公网可达时）**：

| 措施 | 推荐度 | 说明 |
|---|---|---|
| 网络层：探针路径只放行 kubelet + ALB 健康检查源 IP | 推荐 | VKE kubelet 来自节点 IP，ALB 来自 LB 内网 IP；在 Ingress/网络策略层限制 |
| 限流：`/health`、`/ready` 每源 IP 60 req/min | 可选 | slowapi 或网关层限流；探针默认 12 req/min（periodSeconds=5），60 req/min 留足裕量 |
| 响应体最小化 | 推荐 | 只返 `{"status":"ok"}`，不暴露版本/内部状态（版本走 `/version` 且鉴权） |

**[待确认]**：是否在 API 网关层做探针路径的白名单（部署设计 §12.2 的 API 网关选型），还是依赖 Ingress 网络策略。

### A.7 改动文件与函数级变更

**全部改动集中在 `src/tkos_runtime/api/server.py`（+ 可选 `src/tkos_runtime/api/health.py` 抽模块）。**

| 变更 | 函数/符号签名 | 行为 | 接入点 |
|---|---|---|---|
| 新增模块级状态 | `class _RuntimeState` + `_state: _RuntimeState` + `def _ready() -> bool` | 持 `ready`、`startup_shacl_status` | `server.py` 顶部（imports 后） |
| 新增启动 SHACL 辅助 | `def _run_startup_shacl_if_enabled(store) -> str` | 读 `TKOS_STARTUP_SHACL` env；`"1"` 跑 pyshacl 返回 `"pass"`/`"fail"`，否则 `"skipped"` | 新增；被 `create_app` 调用 |
| 新增健康路由注册 | `def _register_health_routes(app: FastAPI, store, state: _RuntimeState) -> None` | 注册 `/health`、`/ready`、`/version` 三个 GET handler | 新增；被 `create_app` 调用 |
| 新增 handler | `async def health() -> dict` | 返回 `{"status":"ok"}`，状态码 200 | 注册于 `app.get("/health")` |
| 新增 handler | `async def ready() -> dict` | 读 `_state.ready`；True→200 `{"status":"ready","checks":{...}}`，False→503 `{"status":"not_ready","reason":...}` | 注册于 `app.get("/ready")` |
| 新增 handler | `async def version() -> dict` | 聚合 `store.ontology_release_id`、`store.dataset_revision`、`os.environ["TKOS_CODE_SHA"]`、各版本常量；返回 200 | 注册于 `app.get("/version")` |
| 改 `create_app` | 在 Store 构建后、`return app` 前插入 readiness 置位 + 路由注册 | 见 A.4 伪代码 | `server.py:72-73` 之间 |
| **不改** | `app = create_app()`（模块级，`server.py:171`） | 保持——导入完成即就绪 | — |

**抽模块选项**：若 `server.py` 已接近可读上限，可把 `_RuntimeState`、`_run_startup_shacl_if_enabled`、`_register_health_routes` 连同三个 handler 抽到新文件 `src/tkos_runtime/api/health.py`，`server.py` 仅 `from .health import register_health_routes, RuntimeState`。**推荐 v1 先内联在 `server.py`**（端点少，避免过度抽象），v1.1 视情况抽模块。

**`/version` 鉴权接入点**：若 §3 的 `require_token` 落地，`/version` handler 加 `Depends(require_token)`；`/health`、`/ready` **不加**。

### A.8 替代方案

| 方案 | 何时选 | 不选的原因 |
|---|---|---|
| **单端点 `/health` 兼作 readiness**（加 `?check=ready` 参数） | 团队想极简 | liveness 与 readiness 语义耦合；优雅停机时无法"liveness 200 但 readiness 503"；违反 K8s 探针标准契约 |
| **`/ready` 尝试真实解析**（如跑一次 dry resolve） | 想覆盖更深的故障路径 | O(n) 且可能触发 LLM；探针路径不能有副作用；Store 已装载即足以判就绪 |
| **readiness 用 FastAPI lifespan 异步装载** | 想让冷启动不阻塞 worker 导入 | 当前 148K 同步装载亚秒级，收益不抵复杂度；留作数据增长后的 v1.1 演进（A.4 已留接入点） |
| **`/version` 完全不鉴权** | 想最大化可观测便利 | 暴露构建指纹给攻击者；与 `/health` 共享公开性会诱导把版本信息也放 `/health`（污染探针响应） |

---

## 3. 方案 B：authN/authZ 最小可行方案（B2）

### B.1 设计约束与语义

- **C-B1**：v1 必须满足 API 契约已定义的 `401`（身份缺失）与 `403`（组织或用途不允许）语义（`api-contracts-v1.md` §通用错误）。
- **C-B2**：必须复用现有 `AdmissionPolicy.allowed_graphs(purpose, registered, restricted)`——它是 purpose→图白名单的纯策略，已是 authZ 的现成基础（`policies.py:17`）。
- **C-B3**：必须与现有 `.env` 凭证机制协调（`server.py:22-29`）——凭证从环境变量/Secret 读，不进镜像、不进仓库（部署设计 §10）。
- **C-B4**：`graph-sensitive-persona` 已在 `restricted_partition_ids` 恒定排除（读侧过滤），但**这不是访问控制**（部署设计 §12.3）。authZ 落地前，sensitive 实例数据必须**构建期排除出部署 bundle**。
- **C-B5**：v1 不实现完整 RBAC / ODRL / AuthorityBoundary（设计层有、运行时缺，见 runtime-architecture.md"当前项目差距"）——只做"有 token + purpose 门禁"的最小切片。

**身份→purpose→图 的链条**：

```
调用方 ─Bearer token─▶ authN: token 有效? ─no─▶ 401
                              │ yes
                              ▼
              authZ-1: token 允许该 purpose? ─no─▶ 403
                              │ yes
                              ▼
              现有 AdmissionPolicy.allowed_graphs(purpose, registered, restricted)
                              │
                              ▼
                    图白名单（已排除 sensitive）
```

关键点：当前 `purpose` 来自请求体（`models.py:21 ResolveRequest.purpose`），不绑定调用方身份。v1 的 authZ-1 就是给"身份→允许的 purpose 集"加一道门。

### B.2 authN（推荐默认：API Key / Bearer token 最小依赖）

**推荐默认：单 API Key，`Authorization: Bearer <key>` 头，FastAPI Dependency，凭证来自环境变量。**

#### 函数级签名

```python
# src/tkos_runtime/api/auth.py（新增）或 server.py 内联
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

_bearer = HTTPBearer(auto_error=False)

def _load_credentials() -> dict[str, "Principal"]:
    """从环境变量加载 token→Principal 映射。
    读 TKOS_API_KEY（单 token，全 purpose）和/或 TKOS_API_KEYS_JSON（多 token，按 purpose 细分）。
    """

def require_token(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> "Principal":
    """authN 依赖：校验 Bearer token。
    缺失/格式错 -> 401 {"detail":"missing or malformed bearer token"}.
    token 不匹配 -> 401 {"detail":"invalid api key"}.
    通过 -> 返回 Principal（含 allowed_purposes）.
    """
```

#### `Principal` 数据结构

```python
@dataclass
class Principal:
    """认证后的调用方身份。"""
    name: str                       # 标识（日志/审计用，不进响应）
    allowed_purposes: set[str]      # 该 token 允许使用的 purpose 集；{"*"} 表示全部
    allowed_scopes: set[str] | None # organization_scope 白名单；None=不限（v1 默认 None）
```

#### 凭证来源（两种模式，二选一或并存）

| 环境变量 | 形态 | 适用 |
|---|---|---|
| `TKOS_API_KEY` | 单个 token 字符串；映射到 `Principal(name="default", allowed_purposes={"*"}, allowed_scopes=None)` | **v1 推荐**：试点/最小切片，单一调用方 |
| `TKOS_API_KEYS_JSON` | JSON：`{"<token>": {"name": "...", "purposes": ["decision_preparation"], "scopes": ["group"]}}` | v1.1：多调用方、按 purpose 细分 |

**加载语义**：

- `_load_credentials()` 在 `create_app` 内调用一次，结果挂在 `app.state`（避免每请求重读环境变量）。
- 启动时若两个 env 都缺失：`create_app` **不报错**（让 `/health`、`/ready` 仍可用），但 `require_token` 对所有业务请求返回 401——等价于"未配置凭证则业务端点不可用，探针仍活"。**[待确认]**：是否改为启动即 fail-fast（部署设计倾向 fail-fast，但会与探针可用性冲突；推荐保持不报错）。
- token 比较用 `hmac.compare_digest`（恒定时间，抗时序攻击）。

#### 401 vs 403 语义

| 场景 | 状态码 | 契约出处 |
|---|---|---|
| 缺 `Authorization` 头 / 非 Bearer scheme / token 不匹配 | **401** | `api-contracts-v1.md`：身份缺失 |
| token 有效但 purpose 不在 `Principal.allowed_purposes` | **403** | `api-contracts-v1.md`：用途不允许 |
| token 有效、purpose 允许，但 organization_scope 越界（v1.1） | **403** | 组织不允许 |

#### 健康端点豁免

- `require_token` 只挂在业务端点（`/v1/context-packs:resolve`、`/v1/context-packs:render`）。
- `/health`、`/ready` **不挂** `require_token`（A.6）。
- `/version` **挂** `require_token`（A.6：暴露指纹应鉴权）。

#### 接入点（`server.py`）

| 端点 | 现状签名 | 改后签名 |
|---|---|---|
| `POST /v1/context-packs:resolve` | `def resolve(req: ResolveRequest)` | `def resolve(req: ResolveRequest, principal: Principal = Depends(require_token))` |
| `POST /v1/context-packs:render` | `def resolve_and_render(req: RenderRequest)` | `def resolve_and_render(req: RenderRequest, principal: Principal = Depends(require_token))` |
| `GET /version` | （新增） | `async def version(principal: Principal = Depends(require_token))` |

`resolve` / `resolve_and_render` 内部把 `principal` 传入 authZ 链（B.3）。

#### 与 `.env` 机制协调

- `TKOS_API_KEY` / `TKOS_API_KEYS_JSON` 走与 `LLM_AUTH_TOKEN` 相同的注入路径：本地 dev 写进 `.env`（`server.py:22-29` 的 `load_dotenv` 自动加载），生产走 K8s Secret + KMS（部署设计 §10）。
- `load_dotenv` 默认 `override=False`——编排系统注入的值优先，与现有机制完全一致，零额外协调。

### B.3 authZ（推荐默认：actor → purpose → allowed_graphs 串接）

#### v1 最小切片：purpose 门禁

**推荐默认：`require_token` 返回的 `Principal` 携带 `allowed_purposes`；在业务 handler 内校验 `req.purpose in principal.allowed_purposes`，不通过则 403。**

**理由**：

- `AdmissionPolicy.allowed_graphs(purpose, ...)` 已经是 purpose→图白名单的纯函数（`policies.py:17`）。只要在调用它之前校验"该身份允许用这个 purpose"，就把身份串进了现有策略链。
- 不改 `AdmissionPolicy` 一行代码——它继续做 purpose→图映射；身份→purpose 的绑定在应用层（新依赖 `require_token`）。
- `graph-sensitive-persona` 已在 `restricted_partition_ids` 恒定排除（`rdflib_dataset_store.py:29`），所以任何 purpose 的白名单都不会包含 sensitive 图——读侧过滤天然兜底。

#### 函数级签名

```python
# src/tkos_runtime/api/auth.py（新增）
def require_purpose(
    purpose: str,
    principal: Principal = Depends(require_token,
) -> Principal:
    """authZ-1 依赖：purpose 门禁。
    purpose in principal.allowed_purposes (或 "*") -> 返回 principal.
    否则 -> 403 {"detail":"purpose '{purpose}' not permitted for principal '{principal.name}'"}.
    """
```

**接入方式（二选一，推荐嵌套依赖）**：

- **方式 1（推荐）：`require_purpose` 内部 `Depends(require_token)`**——handler 只写 `Depends(require_purpose)`，链式校验 authN→authZ。但 `purpose` 来自请求体，需要从 request 取：
  ```python
  def resolve(
      req: ResolveRequest,
      principal: Principal = Depends(require_token,
  ):
      require_purpose(req.purpose, principal)  # 内联校验，抛 HTTPException(403)
  ```
- **方式 2：handler 内显式调 `assert_purpose(req.purpose, principal)`**——更直白，无 FastAPI 依赖魔法：
  ```python
  def assert_purpose(purpose: str, principal: Principal) -> None:
      """Raise HTTPException(403) if purpose not permitted for principal."""
  ```
  推荐方式 2（v1）：FastAPI 的 `Depends` 嵌套对"参数来自请求体"的场景不友好（需要重复解析 body），显式调用更清晰。

#### 完整链条（v1 落地后）

```python
@app.post("/v1/context-packs:resolve")
def resolve(
    req: ResolveRequest,
    principal: Principal = Depends(require_token,   # B.2 authN
):
    assert_purpose(req.purpose, principal)            # B.3 authZ-1: purpose 门禁
    # 以下完全不变 —— 现有 resolver 链：
    #   resolver.resolve(purpose=req.purpose, ...)
    #   → ContextCompiler → AdmissionPolicy.allowed_graphs(purpose, registered, restricted)
    #   → 图白名单（已排除 graph-sensitive-persona）
    ...
```

**关键：现有 `AdmissionPolicy.allowed_graphs` 不改、`resolver.resolve` 不改**——authZ 的"purpose→图"那一段完全复用，只在前面加"身份→purpose"。

### B.4 sensitive 图首批部署约束（C-B4）

部署设计 §12.3 要求"authZ 落地前，sensitive 图实例数据默认不进生产部署 bundle"。这一约束在代码/配置上的表达：

#### 三层兜底（推荐全做）

| 层 | 措施 | 实现 | 强度 |
|---|---|---|---|
| **构建期**（主） | Dockerfile COPY 时排除 sensitive 实例文件，或 `_default_store()` 的 instance glob 排除 sensitive 分区 | 见下方 | 最强——数据根本不在镜像里 |
| **运行期**（兜底） | `AdmissionPolicy` 的 `restricted_partition_ids` 恒定含 `graph-sensitive-persona`（现状，`rdflib_dataset_store.py:29`） | 现状已满足 | 中——只要数据进了镜像，理论上能被绕过 if 调用方构造特殊查询；但只读 Store 无写路径，运行期过滤有效 |
| **配置开关** | `TKOS_INCLUDE_SENSITIVE` 环境变量控制 `_default_store()` 的 instance glob | 见下方 | 显式化——避免"哪些文件进 bundle"成为隐式约定 |

#### 函数级变更：`_default_store()` 加敏感排除

```python
# server.py（改 _default_store）
def _default_store() -> RdfDatasetStore:
    instance_paths = sorted((_REPO_ROOT / "data" / "instances").glob("*.trig"))
    # 新增：按 env 开关排除 sensitive 分区实例
    if os.environ.get("TKOS_INCLUDE_SENSITIVE", "0") != "1":
        instance_paths = [p for p in instance_paths if not _is_sensitive_instance(p)]
    return RdfDatasetStore(_SCHEMA, _DATASET, instance_paths, release_root=_REPO_ROOT)

def _is_sensitive_instance(path: Path) -> bool:
    """启发式：文件名含 'sensitive' 或 'persona'，或解析后含 graph-sensitive-persona 命名图。
    v1 用文件名启发（O(1)）；v1.1 可改为解析后按命名图判定（O(n) 但更准）。
    """
```

#### Dockerfile 侧（部署设计 §13 第 2 项，非源码）

镜像构建时排除：
```dockerfile
COPY data/instances/ /app/data/instances/
# 改为（排除 sensitive）：
COPY data/instances/ /app/data/instances/
RUN find /app/data/instances -name '*sensitive*' -delete 2>/dev/null || true
```
或更干净：用 `.dockerignore` 排除 `data/instances/*sensitive*`。

**[待确认]**（与部署设计 §12.3 Q14 同）：当前 `data/instances/*.trig` 中是否真有 sensitive 分区数据。实测 `2026-08-fe-domain-mission-card-candidates.trig` 含 "persona" 字样但未必是 `graph-sensitive-persona` 命名图——需用户确认首批是否含 sensitive 数据、是否随首批部署。

### B.5 与 ODRL / AuthorityBoundary 脚手架的关系

runtime-architecture.md 的"当前项目差距"明确："尚无服务身份、组织范围、权限和 Token 预算实现"。ODRL（策略表达）/ AuthorityBoundary（组织边界）在本体 schema 层有脚手架，但运行时不消费它们。

| 概念 | 设计层（schema） | 运行时（v1 本文） | 运行时（后续） |
|---|---|---|---|
| authN（你是谁） | 无 | Bearer token → `Principal` | JWT/OIDC（接火山引擎 IAM / API 网关） |
| purpose 门禁（你能做什么） | `_DEFAULT_PURPOSE_ALLOWED`（`policies.py:6`） | `Principal.allowed_purposes` × `assert_purpose` | ODRL 策略机读取本体中的策略声明 |
| organization_scope 边界 | AuthorityBoundary 类（schema） | **不实现**（`Principal.allowed_scopes=None`） | AuthorityBoundary → 按 actor 解析可见 scope |
| sensitive 分区 | `graph-sensitive-persona`（schema） | 构建期排除 + 读侧 `restricted_partition_ids` | 应用层 actor→sensitive 显式授权 |

**v1 明确不做**：

- 不做完整 RBAC（角色/权限矩阵）。
- 不做 ODRL 策略机（读取本体中的 ODRL 策略声明并执行）。
- 不做 AuthorityBoundary 的 organization_scope 强制（当前 `scope_resolution.enforcement` 在测试里就是 `"not_enforced"`，`test_runtime_api.py:35`）。
- 不做 per-actor 审计日志增强（仅依赖现有 gunicorn access log + 未来的 `request_id`，部署设计 §12.4）。

### B.6 改动文件与函数级变更

| 文件 | 变更 | 函数/符号 | 说明 |
|---|---|---|---|
| `src/tkos_runtime/api/auth.py`（新增） | 新模块 | `Principal`、`require_token`、`assert_purpose`、`_load_credentials` | authN + authZ-1；可选独立模块，v1 也可内联 `server.py` |
| `src/tkos_runtime/api/server.py` | import auth | `from .auth import Principal, require_token, assert_purpose` | 顶部 |
| 同上 | 改 `_default_store` | 加 `TKOS_INCLUDE_SENSITIVE` 排除逻辑 + `_is_sensitive_instance` | B.4 |
| 同上 | 改 `create_app` | 调 `_load_credentials()` 挂 `app.state.principals`；`require_token` 读 `request.app.state` | B.2 |
| 同上 | 改 `resolve` / `resolve_and_render` | 加 `principal: Principal = Depends(require_token)` 参数 + `assert_purpose(req.purpose, principal)` 调用 | B.3 |
| 同上（或 `health.py`） | 改 `version` handler | 加 `principal: Principal = Depends(require_token)` | A.6 |
| **不改** | `policies.py`、`rdflib_dataset_store.py`、`resolver`、`compiler` | — | authZ 的 purpose→图段完全复用 |

### B.7 替代方案

#### authN 替代

| 方案 | 何时选 | 不选的原因 |
|---|---|---|
| **API 网关层 authN**（部署设计 §12.2 推荐） | 已有火山引擎 API 网关 [待确认]；不想在应用层管 token | 网关未定；即便网关做 authN，应用层仍需 authZ（网关通常不知 purpose 语义）；**推荐 v1 应用层做最小 authN，网关作为 v1.1 前置**（纵深防御） |
| **JWT / OIDC**（接火山引擎 IAM） | 多用户、SSO 场景 | v1 单/少调用方，JWT 验签 + JWKS + 时钟漂移复杂度不划算；留作公网多租户阶段 |
| **mTLS**（客户端证书） | 高安全、内部服务网格 | 证书签发/轮换基础设施重；VKE 内部 service mesh（如 Istio）可做，但超出 v1 范围 |

#### authZ 替代

| 方案 | 何时选 | 不选的原因 |
|---|---|---|
| **per-token purpose 绑定（`TKOS_API_KEYS_JSON`）** | 多调用方、按职能分 purpose | v1 单 token 够用；JSON 配置易错，留作 v1.1 |
| **ODRL 策略机** | 策略需可溯源、可审计、非工程师可改 | 运行时无 ODRL 引擎；v1 用硬编码 purpose 白名单（`policies.py:6` 已是此形态） |
| **organization_scope 强制** | 跨组织数据隔离 | `scope_resolution.enforcement` 当前 `"not_enforced"`；需先设计 AuthorityBoundary 解析逻辑，超出 v1 |

### B.8 v1 范围 vs 后续

| 能力 | v1（本文） | v1.1 | v2 |
|---|---|---|---|
| authN | 单 Bearer token（`TKOS_API_KEY`） | 多 token（`TKOS_API_KEYS_JSON`）+ API 网关前置 | JWT/OIDC + IAM |
| authZ-purpose | `assert_purpose`：token→purpose 门禁 | per-token purpose 细分 | ODRL 策略机 |
| authZ-scope | 不实现（`allowed_scopes=None`） | `Principal.allowed_scopes` × `organization_scope` 校验 | AuthorityBoundary 自动解析 |
| sensitive 图 | 构建期排除 + 读侧过滤（现状） | 应用层 actor→sensitive 显式授权 | 同左 + 审计 |
| 健康端点 | `/health`、`/ready`、`/version`（本文 A） | 优雅停机 drain（SIGTERM→ready=False） | 同左 |
| 审计 | gunicorn access log | `request_id` + principal.name 入日志 | 完整审计链路（部署设计 §12.4） |

---

## 4. 测试设计（信息性，非实施）

仅描述应增测试用例（不写实现），沿用 `tests/test_runtime_api.py` 的 `TestClient(create_app())` 约定。

### A. 健康端点

| 用例 | 断言 |
|---|---|
| `test_health_always_200` | `GET /health` → 200，body `{"status":"ok"}` |
| `test_ready_200_after_startup` | `create_app()` 返回后 `GET /ready` → 200，`store_loaded:true` |
| `test_ready_503_before_load` | 构造 `_state.ready=False`（或用 `monkeypatch`）→ `GET /ready` → 503 |
| `test_version_returns_fingerprints` | `GET /version` → 200，含 `ontology_release_id=="2.4.0"`、`dataset_revision` 非空、`app_version=="0.1.0"` |
| `test_version_code_sha_from_env` | `monkeypatch.setenv("TKOS_CODE_SHA","abc123")` → `version()["code_sha"]=="abc123"`；不设 → `"unknown"` |
| `test_startup_shacl_pass` | `TKOS_STARTUP_SHACL=1` → `ready` 的 `checks.startup_shacl=="pass"`（当前数据合规） |

### B. authN/authZ

| 用例 | 断言 |
|---|---|
| `test_resolve_without_token_is_401` | 无 `Authorization` 头 → 401 |
| `test_resolve_with_wrong_token_is_401` | `Authorization: Bearer wrong` → 401 |
| `test_resolve_with_valid_token_is_200` | `TKOS_API_KEY=test-key`，头 `Bearer test-key` → 200 |
| `test_resolve_purpose_not_permitted_is_403` | `TKOS_API_KEYS_JSON='{"k":{"purposes":["mission_review"]}}'`，请求 `purpose=decision_preparation` → 403 |
| `test_health_no_auth_required` | 无 token `GET /health` → 200（豁免） |
| `test_version_requires_auth` | 无 token `GET /version` → 401 |
| `test_sensitive_instance_excluded_by_default` | `TKOS_INCLUDE_SENSITIVE` 未设 → `_default_store()` 的 `restricted_node_ids` 为空（或不含 sensitive 节点） |

---

## 5. 待确认项清单

| # | 项 | 出处 | 影响决策 |
|---|---|---|---|
| P1 | **authN 凭证来源**：v1 用单 `TKOS_API_KEY` 还是多 token JSON？凭证由谁签发/轮换？ | §B.2 | 决定 `_load_credentials` 形态 |
| P2 | **是否接 API 网关做前置 authN**（火山引擎 API 网关 [待确认]）？若接，应用层 authN 是兜底还是移除？ | §B.7、部署设计 §12.2 | 决定应用层 authN 的角色（纵深 vs 唯一） |
| P3 | **`/version` 是否鉴权**：本文推荐鉴权（A.6），但若部署后可观测性要求免 curl 即查版本，可放宽。 | §A.6 | 决定 `/version` 是否挂 `require_token` |
| P4 | **`TKOS_STARTUP_SHACL` 默认开启吗**：开启更安全（启动 defense-in-depth），但会在数据不合规时阻塞 Pod 接流量。 | §A.4 | 决定启动 SHACL 是 opt-in 还是 opt-out |
| P5 | **健康探针路径的网络层限制**：在 Ingress/网络策略层限 kubelet+ALB 源 IP，还是依赖应用层？ | §A.6 | 决定是否需要 Ingress 配置变更 |
| P6 | **sensitive 实例首批是否部署**：当前 `data/instances/*.trig` 是否含 `graph-sensitive-persona` 命名图数据？ | §B.4、部署设计 Q14 | 决定 `_is_sensitive_instance` 的启发式 + Dockerfile 排除规则 |
| P7 | **凭证缺失时是否 fail-fast**：本文推荐不报错（探针仍活、业务 401），还是 `create_app` 直接 raise？ | §B.2 | 决定 `_load_credentials` 在凭证缺失时的行为 |
| P8 | **优雅停机 drain 是否进 v1**：SIGTERM→`ready=False` 让 LB 先摘流量，是 v1 还是 v1.1？ | §A.4 | 决定是否在 v1 加信号处理 |

> P1–P2 与部署设计 §15 的 Q9（API 网关）、Q14（sensitive 数据）联动，建议一并确认。

---

## 6. 决策摘要（一屏速览）

**方案 A（健康端点）**：
- 三个独立 GET：`/health`（liveness 无条件 200）、`/ready`（readiness 读 `_state.ready` 标志，503 when 未就绪）、`/version`（聚合 `ontology_release_id`/`dataset_revision`/`code_sha` + 各组件版本常量）。
- 模块级 `_RuntimeState` 持 `ready`、`startup_shacl_status`；`create_app` 在 Store 构建后置位；前向兼容 lifespan 懒装载与优雅停机 drain。
- 探针映射与部署设计 §6.3 一致：liveness→`/health`、readiness+startup→`/ready`（startup 60s 裕量）。
- `/health`、`/ready` 不鉴权；`/version` 鉴权（防指纹泄露）。

**方案 B（authN/authZ 最小切片）**：
- authN：单 Bearer token（`TKOS_API_KEY`），FastAPI `Depends(require_token)`，凭证走现有 `.env`/Secret 机制；401（缺/错 token）vs 403（purpose 不允许）。
- authZ：`Principal.allowed_purposes` × `assert_purpose(req.purpose, principal)` 串接现有 `AdmissionPolicy.allowed_graphs(purpose, ...)`——**不改策略/Store/resolver 一行代码**，只在前面加"身份→purpose"门。
- sensitive 图：三层兜底——构建期排除（`TKOS_INCLUDE_SENSITIVE` + Dockerfile/.dockerignore）+ 运行期 `restricted_partition_ids`（现状）+ 配置开关。
- v1 不做：完整 RBAC、ODRL 策略机、AuthorityBoundary 强制、JWT/OIDC——明确为 v1.1/v2。

**改动文件**：全部集中在 `src/tkos_runtime/api/server.py` + 新增 `src/tkos_runtime/api/auth.py`（可选）+ 健康模块抽分（可选）。**不动** `policies.py`、`rdflib_dataset_store.py`、`resolver`、`compiler`、`serializer`、现有请求/响应模型。

**待用户确认**：P1–P8（§5），其中 P1（凭证来源）、P2（API 网关）、P6（sensitive 首批）为部署前必须拍板的三项。
