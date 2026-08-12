# TKOS Ontology Runtime — 火山引擎部署设计

> 状态：设计稿 → **部分执行中，已切换为 Mac 本机反代方案**（2026-08-12）：健康端点 + authN/authZ + 启动 SHACL + 客户端 pack purpose 门禁已落地（`server.py`）；容器镜像（Dockerfile + .dockerignore + `PIP_INDEX_URL` build-arg）构建与容器冒烟通过。**当前部署路径 = `deploy/mac-local/`**（docker compose：TKOS 容器 + Caddy 反代 + 自动 HTTPS，域名+公网 IP）。本文档的火山引擎设计保留为**备用路径**（`deploy/ecs/` 产物就绪，需要时启用）。
> 范围：本体服务（FastAPI Runtime）+ 推理（SHACL/SWRL）+ API 运行 + LLM 端点 + 数据/制品分发 + CI/CD + 配置/密钥 + 扩展路径 + 安全前置
> 日期：2026-08-12
> 配套文档：[runtime-architecture.md](./runtime-architecture.md)、[api-contracts-v1.md](../api/api-contracts-v1.md)、[distillation-and-cold-start.md](./distillation-and-cold-start.md)

---

## 0. 阅读须知

本文每个决策给出"**推荐默认 + 理由 + 替代方案**"。涉及账号、凭证、区域、确切产品名/SKU 的位置一律标 `[待确认]`，不臆造火山引擎产品名；不确定时用品类描述（如"火山引擎容器服务（VKE 或同类）"）并请用户确认。

末尾有：
- §13 **最小可部署切片**（先跑起来需要什么）
- §14 **完整生产形态**
- §15 **待确认清单**（汇总所有 `[待确认]`）
- §16 **附录：环境变量映射表**

---

## 1. 现状基线（设计依据，全部 ground 在代码）

| 维度 | 现状事实 | 来源 |
|---|---|---|
| 运行单元 | 单体 FastAPI + uvicorn，模块级 `app = create_app()` | `src/tkos_runtime/api/server.py:171` |
| Store | `RdfDatasetStore`：启动时从磁盘装载 schema/dataset/instances，构建内存 `rdflib.Dataset`，**只读** | `src/tkos_runtime/adapters/rdflib_dataset_store.py:21-34` |
| 数据装载 | `ontology/schema/*.jsonld` + `ontology/datasets/*.trig` + `data/instances/*.trig`，cwd-无关 | `server.py:47-54` |
| 当前数据量 | schema 56K + ttl 44K + dataset 4K + shapes 12K + 6 实例 trig ~88K ≈ **148K**，冷启动亚秒级 | 仓库实测 |
| 版本指纹 | 已计算 `dataset_revision`（数据文件 sha256）+ `ontology_release_id`（OWL versionInfo） | `rdflib_dataset_store.py:51-66` |
| SHACL | pyshacl 同步校验，**仅在测试里跑**（`run_instance_conformance.py`），未进运行时请求路径 | `Makefile`, `tests/` |
| SWRL | Openllet（Java CLI，251MB + JVM），**仅测试**，未进运行时 | `tests/run_v2_3_swrl_openllet.py`, `ci.yml` |
| LLM | OpenAI 兼容客户端，当前指向 DeepSeek，环境变量 `LLM_BASE_URL/LLM_AUTH_TOKEN/LLM_MODEL`；凭证缺失时**静默降级到确定性链路** | `adapters/openai_text_polisher.py:31-40`, `server.py:141-146` |
| 渲染 | 确定性 + LLM 双链路；LLM 只做表达润色，校验链路不变 | `api-contracts`, `decision-context-compiler-design` |
| 身份/权限 | **无**；sensitive 图 + AuthorityBoundary 只是脚手架；Store 有读侧 `restricted_node_ids` 过滤 | `runtime-architecture.md` |
| 健康检查 | **无 `/health`、`/ready`、`/version` 端点** | `server.py` |
| 部署制品 | 无 Dockerfile、无镜像、无 CI 部署步骤 | 仓库根 |
| CI | GitHub Actions，纯 Python 门禁 + 信息性 SWRL | `.github/workflows/ci.yml` |

**对设计影响最大的三条**：
1. **冷启动构建内存图**：每个进程/副本启动时都要从磁盘装载并构建图。当前 148K 亚秒级，但随实例增长会变慢——这是选型与扩展的关键变量。
2. **Store 进程内只读、无跨副本共享可变状态**：水平扩展比有状态服务容易得多（N 个副本完全对等，无缓存一致性问题）。
3. **LLM 不在正确性关键路径上**：凭证缺失时确定性链路兜底——LLM 端点选型是质量/驻留问题，不是可用性问题。

---

## 2. 设计约束（从事实推导，不可妥协）

- **C1** 每个服务副本启动时必须能访问 schema/dataset/instances 文件（磁盘装载是 `RdfDatasetStore.__init__` 的硬约束）。
- **C2** 数据是只读的；运行时无写入路径（Submission/Confirmation API 尚未实现）。
- **C3** 每个请求可能触发 LLM 调用（润色模式），单次调用数秒；优雅停机 timeout 必须 > p99 LLM 延迟。
- **C4** 公网暴露前必须补 authN/authZ 与 sensitive 图访问控制（当前完全没有）。
- **C5** 不改源码即可部署——但健康检查端点是部署前置缺口，需作为"部署前必须做的最小代码补丁"列出（本设计不实施）。

---

## 3. 计算层选型

### 推荐默认：火山引擎容器服务（VKE 或同类 Kubernetes 托管服务）+ 容器镜像部署

**理由**：
- **冷启动语义契合 Pod 生命周期**：Pod 启动 → 装载图 → readiness 探针通过 → 接流量。滚动更新天然处理"新副本装载完毕再切流量"。这是 VKE 比 VM/函数更顺的关键点。
- **水平扩展零代码成本**：因为 Store 只读、副本对等（§1），扩容只是 `replicas` 数字，无 session 亲和、无共享状态。
- **未来 SWRL/蒸馏 Worker 是独立 Pod**：当 API 3/异步蒸馏上线时，VKE 直接以另一个 Deployment 承接，不需要换基础设施。
- **配置/密钥原生集成**：ConfigMap/Secret + downward API 直接对应 `.env` 注入需求。

**替代方案**：

| 选项 | 何时选 | 不选的原因 |
|---|---|---|
| **ECS（云服务器/裸金属）** | 团队无 K8s 经验、长期单副本试点 | 多副本滚动更新、健康检查、自动伸缩都要手工搭；冷启动滚动不如 Pod 顺 |
| **函数计算（FC 或同类 Serverless）** | ❌ 不推荐作为默认 | 每次冷启动都要重建内存图（请求级冷启），与"长驻进程持有内存图"模型冲突；即便 148K 可接受，模型错配会随数据增长暴露 |

> [待确认] 用户使用火山引擎容器服务 VKE 还是自管 K8s on ECS；以及目标区域（`cn-beijing` / `cn-shanghai` 等）。

### 实例规格（最小切片）

- 当前 148K 数据、单进程、无并发瓶颈：**2 vCPU / 4 GiB** 起步即足够。
- Python + rdflib + pyshacl 内存占用主要来自解析后的图对象，当前数据量远低于 1 GiB。
- [待确认] VKE 节点池规格与可用区。

---

## 4. 本体与数据制品分发

> 决定 `.ttl/.trig/.jsonld` 制品与实例数据怎么进入运行进程。这是 §2-C1 的核心。

### 推荐默认（分两阶段）

**阶段 A（当前 ~ MB 级以下，推荐立即采用）：制品打进镜像**

- 构建时把 `ontology/schema/*.jsonld` + `ontology/datasets/*.trig` + `data/instances/*.trig` + `ontology/shapes/*.jsonld` 一并 COPY 进镜像（路径与仓库一致，保证 cwd-无关装载逻辑不变）。
- 镜像 tag 同时编码 `code-sha` + `dataset_revision`，做到"代码即制品、制品即版本"。
- **理由**：当前总量 148K，打进镜像零成本；启动时无外部依赖（不依赖 TOS 可用性）；完全可复现；CI 已有 `run_instance_conformance.py` 做装载前 SHACL 门禁——直接复用为发布门禁。
- **版本指纹**：镜像标签里带上 `dataset_revision` 前 12 位 + `ontology_release_id`，例如 `tkos-runtime:<code-sha>-<dataset-rev12>`。

**阶段 B（数据更新频率高于代码 / 实例增长到 10MB+ 时迁移）：TOS 对象存储 + release manifest**

- 制品以 **release bundle** 形式上传到火山引擎对象存储 TOS（`tos-cn-<region>` [待确认]）。bundle 是一个 tar/zst 包，内含 schema/shapes/dataset/instances + 一份 `release-manifest.json`。
- 镜像只装运行时代码。Pod 启动时读环境变量 `TKOS_RELEASE_BUNDLE_URL`（指向 TOS 对象），拉取、校验 sha256（与 manifest 中 `dataset_revision` 对比）、解压到本地、再装载。
- **release manifest** 字段：`{ ontology_release_id, dataset_revision, code_sha_min, built_at, shapes_digest, instances: [{path, digest}], compatibility }`。
- **理由**：把"数据发布"与"代码发布"解耦；数据可独立滚动（无需重建镜像）；manifest 提供可追溯的发布指针。
- **替代**：挂载共享文件系统（NAS/CFS [待确认产品]）——比 TOS 拉取复杂、冷启动依赖网络挂载可用性，**不作为默认**。

### 制品分层（两阶段通用）

| 制品 | 来源 | 体积 | 进镜像 / TOS |
|---|---|---|---|
| schema (`ontology/schema/tkos-ontology.jsonld`, `.ttl`) | 仓库 / `make generate` | ~100K | 镜像（A）/ bundle（B） |
| shapes (`ontology/shapes/tkos-validation-shapes.jsonld`) | 仓库 | 12K | 镜像（A）/ bundle（B） |
| dataset (`ontology/datasets/tkos-runtime-dataset.trig`) | 仓库 | 4K | 镜像（A）/ bundle（B） |
| instances (`data/instances/*.trig`) | 仓库（当前）/ 蒸馏管道（未来） | ~88K 且增长 | 镜像（A）/ bundle（B） |
| views (`ontology/views/*-protege-view.ttl`) | `make generate` | — | **不进运行镜像**（仅 Protégé 浏览用） |

> [待确认] 阶段 B 迁移时机——预期实例数据增长速率（蒸馏管道上线后）。

---

## 5. 推理运行（SHACL + SWRL 在管道中的位置）

> 关键原则：**推理是发布时/构建时的产物，不是请求时的开销。** 这与 `runtime-architecture.md` 的"本体 Release 发布时运行推理并物化派生图"一致。

### 5.1 SHACL（pyshacl，同步）

- **不在请求路径跑 SHACL**。请求路径只读取已校验的内存图，保证低延迟。
- **SHACL 门禁接进发布管道**：CI 构建镜像前必须跑 `run_instance_conformance.py`（真实实例硬门禁）+ `run_v2_3_shacl.py`（正负向），失败则不产镜像、不部署。
- **启动时 defense-in-depth（推荐启用）**：Pod 启动装载图后、readiness 通过前，在本地再跑一次 pyshacl（当前数据量亚秒级，成本可忽略）。门禁失败 → Pod 不接流量。这是对 CI 门禁的二次保险，防止镜像内的数据被意外污染。
  - [代码层] 需要在 `server.py` 启动序列里加一个"装载后校验"开关（本设计不实施，列为部署前补丁）。

### 5.2 SWRL（Openllet/Java）

- **SWRL 推理产物 = 构建时物化**。在 CI 里用 Openllet 跑 SWRL，把派生三元组写回 dataset（或单独 `derived` 命名图），再装载/打包。
- **运行时不带 JVM**。Openllet（251MB）+ JVM 留在 CI runner，不进服务镜像。服务镜像保持纯 Python、小而快。
- **CI 接线**：当前 `ci.yml` 里 SWRL job 是 `continue-on-error: true` 的信息性 job。设计上应迁为 **release 构建管道中的 blocking job**（仅对将要发版的 tag/branch 触发），产出物化后的 dataset 制品。
- **未来增量 SWRL**：若写路径（Submission/Confirmation）上线后需要增量重算派生图，应作为**独立的 Worker 服务**（独立 Pod，带 JVM），通过 Release 发布器产出新版本 dataset，**仍不进 API 请求路径**。
- **替代（不推荐）**：API Pod 内跑 Openllet JVM sidecar——镜像膨胀、冷启动慢、资源浪费，且与"推理物化"原则相悖。

> [待确认] SWRL 物化在 CI 里的触发策略：是否每次 main 合并都跑（当前是信息性），还是仅在 release tag 时跑。

---

## 6. API 运行配置

### 6.1 进程模型：gunicorn + uvicorn worker

**推荐命令**（镜像 CMD）：
```
gunicorn tkos_runtime.api.server:app \
  -k uvicorn.workers.UvicornWorker \
  -w 2 \
  -b 0.0.0.0:8000 \
  --timeout 60 \
  --graceful-timeout 35 \
  --keep-alive 5 \
  --access-logfile - \
  --error-logfile -
```

**决策点**：

| 参数 | 推荐值 | 理由 |
|---|---|---|
| worker class | `uvicorn.workers.UvicornWorker` | FastAPI 官方推荐的 gunicorn 进程管理 + uvicorn ASGI |
| `-w` | 2（最小切片）→ 按 CPU 调 | 每个进程独立装载图（只读，无锁竞争） |
| `--preload` | **不用** | rdflib Dataset 对象在 fork 后可能有线程锁隐患；当前数据量下让每个 worker 各自装载更安全 |
| `--timeout` | 60s | LLM 润色调用可能数秒，留足裕量；确定性链路远低于此 |
| `--graceful-timeout` | 35s | **必须 > p99 LLM 延迟**，否则滚动更新会强杀在途润色请求（§2-C3） |
| `--reload` | 生产**禁用** | 仅本地 dev |

**替代**：直接 `uvicorn ... --workers 2`——可行但 gunicorn 进程管理/信号处理更成熟，推荐 gunicorn。

### 6.2 反向代理与端口

- 容器内 gunicorn 监听 `0.0.0.0:8000`。
- 前置火山引擎负载均衡（应用型负载均衡 ALB / 经典型 CLB [待确认]）做 TLS 终止 + 四层/七层健康检查 + 流量分发。
- VKE 场景：用 VKE Ingress（或 ALB Ingress Controller）暴露 Service。
- ECS 场景：CLB 直接挂 ECS 实例。

### 6.3 健康检查（部署前必须补的代码缺口）

当前 `server.py` **无 `/health`、`/ready`、`/version`**。这是部署硬阻塞——VKE 探针/LB 健康检查无目标。

**部署前最小代码补丁（本设计不实施，仅列出）**：
- `GET /health` — 进程存活，无条件 200（liveness）。
- `GET /ready` — 仅当 Store 装载完成（且可选地启动 SHACL 通过）后 200，否则 503（readiness / 滚动更新门）。
- `GET /version` — 返回 `ontology_release_id`、`dataset_revision`、`code_sha`（可观测性 + 故障排查）。

VKE 探针映射：
- livenessProbe → `/health`（`periodSeconds=10`, `failureThreshold=3`）
- readinessProbe → `/ready`（`periodSeconds=5`, `failureThreshold=3`）
- startupProbe → `/ready`（`failureThreshold=30`, `periodSeconds=2`）——给冷启动 + 启动 SHACL 留最多 60s

### 6.4 优雅停机（内存图重建语义）

- Store 是内存只读、无持久化写入。**"优雅停机"的核心不是 flush 状态，而是不丢在途请求。**
- 流程：SIGTERM → gunicorn 停止接新请求 → 等在途请求完成（最长 `--graceful-timeout=35s`）→ 退出。
- 滚动更新时新 Pod 先通过 readiness 才接流量，旧 Pod drain——因为图只读、副本对等，**不存在跨副本状态迁移问题**，这是无状态只读 Store 带来的部署红利。
- 内存图"重建"只发生在新副本启动时，不在停机路径上。

---

## 7. LLM 端点：火山引擎方舟（Ark） vs 保留外部 DeepSeek

### 7.1 权衡

| 维度 | 方舟（Ark） | 外部 DeepSeek（现状） |
|---|---|---|
| 数据驻留 | 同区域 Volcengine VPC 内，可走 VPC Endpoint，不出公网 | 数据出 Volcengine（跨区域/公网） |
| 延迟 | 同区域内 ms 级 RTT | 公网 + 跨服务商，更高 |
| 凭证管理 | Volcengine IAM / 方舟 API Key，可与计算同账号 | 独立第三方凭证 |
| 模型选择 | 方舟模型花园（Doubao 系列等）[待确认是否有 DeepSeek-V3/R1 等同档模型] | DeepSeek 已知 |
| 故障域 | 与计算同云（一损俱损） | 跨云（互为独立故障域） |
| 适配器代码改动 | **零**（OpenAI 兼容接口） | **零** |

### 7.2 推荐默认：方舟（Ark）为主 + 环境变量切换保留外部 DeepSeek 兜底

**理由**：
- **数据驻留**：企业经营本体属敏感数据，同区域 VPC 内调用降低合规与传输风险。
- **零代码成本**：`OpenAITextPolisher` 已经是 OpenAI 兼容客户端，只换三个环境变量值即可切换 Provider。生产用 Ark、调试/对照可即时切回 DeepSeek。
- **降级安全网不变**：LLM 凭证缺失或调用失败时，`server.py:141-146` 已会静默回退到确定性链路——LLM Provider 故障不影响 API 可用性。

> [待确认] 方舟是否提供满足润色质量要求的模型（Doubao-pro / 是否上架 DeepSeek-V3 / 其他）。这决定主 Provider 是否真用方舟。

### 7.3 方舟接入环境变量映射（§16 附录有完整表）

| 现有变量 | 方舟取值 | 说明 |
|---|---|---|
| `LLM_BASE_URL` | `https://ark.cn-beijing.volces.com/api/v3` | 方舟 OpenAI 兼容入口 [区域待确认] |
| `LLM_AUTH_TOKEN` | 方舟 API Key（方舟控制台或 IAM 签发） | 走 K8s Secret / KMS 注入，**不进镜像** |
| `LLM_MODEL` | 方舟 Endpoint ID（如 `ep-xxxxxxxx`）或模型别名 | [待确认具体 endpoint id] |

### 7.4 网络

- 方舟走 VPC Endpoint（同区域）——API Pod 无需公网出向。
- 若临时保留外部 DeepSeek：需 NAT 网关 [待确认] 出公网，且凭证进 Secret。

---

## 8. 持久化与版本（不停机更新）

### 8.1 当前

- Store 内存只读，**无持久化写入路径**。"持久化"在此 = 制品（schema/dataset/instances）的版本化存储。
- 已有 `dataset_revision`（sha256）+ `ontology_release_id`（OWL versionInfo）作为内容指纹。

### 8.2 版本化设计

- **不可变发布单元 = 镜像 tag**（阶段 A）或 **TOS bundle + manifest**（阶段 B），二者都携带 `{ontology_release_id, dataset_revision, code_sha}`。
- 部署侧永远引用具体 tag/manifest，不用 `latest`。
- `/version` 端点（§6.3）暴露这三个指纹，供排查"线上跑的到底是哪份制品"。

### 8.3 不停机更新

- 因为 Store 只读、副本对等：**滚动更新即可**，无需蓝绿、无需双写、无需 schema migration。
- 流程（VKE）：`kubectl set image` 或触发部署管道 → 新 Pod 拉新镜像 → 启动装载新图 → readiness 通过 → 接流量 → 旧 Pod drain（§6.4）。
- **关键前提**：readiness 探针必须真正在"装载完成 + 启动 SHACL 通过"后才转 200（§6.3）。否则会出现"接了流量但图没装好"的 500 窗口。
- **回滚**：切回旧 tag 即可，因为旧副本的内存图不受影响。

### 8.4 未来写路径（Submission/Confirmation 上线后）

- 当 API 4（受控写入）实现后，Store 不再纯只读——届时需要：
  1. 持久化的 RDF 三元库（火山引擎图数据库 / 自管 RDF store [待确认]）作为 Source of Truth；
  2. 内存图退化为读缓存或物化视图；
  3. 写入经 Confirmation 事务 → 新 Release → 滚动装载。
- 本设计**不含**写路径部署（仓库尚未实现写路径），仅标注演进方向。

---

## 9. CI/CD

### 9.1 当前

- GitHub Actions（`.github/workflows/ci.yml`）：push/PR 时跑纯 Python 门禁（SHACL + Context Pack + 实例一致性 + 同构 + Runtime/API 38 测试），SWRL 信息性。

### 9.2 设计（叠加发布管道，不替换现有 CI）

```
push to main / tag release-vX.Y.Z
        │
        ▼
[现有] 纯 Python 门禁 (必过)
   ├─ SHACL 正负向
   ├─ 实例一致性 (真实数据硬门禁) ← 即 §5.1 的发布门禁
   ├─ 同构守卫
   └─ Runtime/API/Harness pytest
        │ (失败 → 停)
        ▼
[新增] SWRL 物化 (release 阶段 blocking; 主分支可继续信息性)
        │ 产出物化 dataset（写回 trig 或 derived 图）
        ▼
[新增] 构建镜像
   ├─ 基础镜像: python:3.11-slim
   ├─ pip install -e '.[api]' (或 [all]，含 openai)
   ├─ COPY src + ontology/{schema,shapes,datasets} + data/instances
   ├─ CMD: gunicorn ... (§6.1)
   └─ tag: <code-sha>-<dataset-rev12>-<ontology-release>
        │
        ▼
[新增] 推送镜像到火山引擎容器镜像服务 (CR [待确认])
        │
        ▼
[新增] 触发部署
   ├─ VKE: 更新 Deployment image tag → 滚动更新
   └─ ECS: 新镜像 + 替换实例（需 ALB/CLB 健康检查门控）
        │
        ▼
[新增] 部署后验证
   └─ agent_harness.py + /version 指纹核对
```

### 9.3 选择

- **CI runner**：继续用 GitHub Actions（已有）+ 跨云 push 到火山引擎 CR；或迁到火山引擎持续交付 [待确认产品名]。**推荐先保留 GitHub Actions**，降低迁移成本，CR push 用火山引擎 RAM/IAM 长期凭证（存 GitHub Secret）。
- **镜像仓库**：火山引擎容器镜像服务 CR [待确认]，与 VKE 同区域私有镜像拉取，走内网。
- **部署触发**：手动/自动二选一。**推荐最小切片期手动**（tag 触发 build，人工确认 deploy），稳定后再开自动滚动。

> [待确认] 是否已有火山引擎容器镜像服务实例与命名空间；CR push 凭证的获取方式。

---

## 10. 配置与密钥

### 10.1 原则

- **`.env` 不进镜像、不进仓库（生产）。** `server.py:23-29` 的 `load_dotenv` 在 `.env` 缺失时是 no-op，生产环境由编排系统注入环境变量即可。
- 非敏感配置 → ConfigMap（或 ECS user-data）。
- 敏感凭证 → K8s Secret（或火山引擎密钥管理服务 KMS [待确认] 加密），通过环境变量注入容器。

### 10.2 配置分层

| 类别 | 项 | 注入方式 |
|---|---|---|
| 非密 | `LLM_MODEL`（模型名非密） | ConfigMap / 镜像默认 |
| 非密 | `TKOS_RELEASE_BUNDLE_URL`（阶段 B） | ConfigMap |
| 非密 | gunicorn `-w` / `--timeout` | 镜像 CMD / Deployment env |
| **密** | `LLM_BASE_URL`（可能含 endpoint id，半密） | Secret |
| **密** | `LLM_AUTH_TOKEN`（API Key） | Secret + KMS |
| **密** | TOS 访问 AK/SK（阶段 B 拉取 bundle） | Secret + KMS，用最小权限 RAM 子账号 |
| **密** | 火山引擎账号访问密钥（CI push 镜像用） | GitHub Actions Secret，**不进运行镜像** |

### 10.3 代码侧可选优化（非阻塞，本设计不实施）

- 增加一个 `TKOS_ENV=production` 开关，显式跳过 `.env` 自动加载，避免生产环境意外读到镜像内残留的 `.env`。
- 当前 `load_dotenv` 不会覆盖已存在的环境变量（默认 `override=False`），编排系统注入的值优先生效——所以即便保留自动加载也安全。

> [待确认] 火山引擎密钥管理服务（KMS）的确切产品名与 K8s Secret 加密集成方式。

---

## 11. 成本与扩展路径

### 11.1 当前（单副本模块化单体）

- 计算成本：2 vCPU/4 GiB 单 Pod，几乎可忽略。
- **主要成本在 LLM token**（方舟计费），确定性渲染链路几乎免费。
- 存储成本：镜像 + TOS（阶段 B），当前 148K 量级零成本。

### 11.2 水平扩展路径（核心论点：只读 Store 让扩容变简单）

| 阶段 | 形态 | 前提 |
|---|---|---|
| 试点 | 1 副本 | readiness/liveness 端点就绪（§6.3） |
| HA | 2+ 副本 + ALB/CLB | 无代码改动；LLM 凭证经 Secret 共享；每副本各装载一份内存图 |
| 自动伸缩 | VKE HPA（CPU/RPS 触发） | 仍无代码改动，因为只读无状态 |

**为什么水平扩展容易（要点明）**：
- Store 进程内只读 → N 个副本完全对等，**无 session 亲和、无共享缓存、无锁竞争、无主从同步**。
- 这与有状态服务（带写入的图库、带会话的服务）相比，扩容成本是数量级的差距。
- 唯一随副本数线性增长的是**内存**（每副本一份图）。当前 148K 可忽略；当图涨到 100MB+/副本 时，需评估节点内存或转向共享只读 Store。

### 11.3 垂直 / 数据增长拐点

- 冷启动时间 = O(数据量)。当前亚秒级；预计 10MB 级仍在 1-2s 内；100MB+ 级可能到秒级——此时：
  - 倾向**少而大**的副本（减少冷启动次数），配合 HPA 缓慢扩缩。
  - 或预编译内存图快照（pickle/serialize）随镜像分发，启动时 `mmap` 载入而非重新解析（代码改造，本设计不含）。
- 一旦写路径上线（§8.4），无状态假设失效，扩展模型需重新设计（持久化 Store + 读副本）。

---

## 12. 安全（公网暴露前的最小必须措施）

> 当前**完全没有 authN/authZ**。以下为公网部署前的硬前置，**哪怕只是标注"必须先做"**。

### 12.1 网络

- **API Pod 不直接暴露公网**。部署在私有子网，仅 ALB/API 网关有公网 IP。
- LLM 出向走 VPC Endpoint（方舟同区域），不出公网。
- 安全组：只放行 ALB → Pod:8000，以及 Pod → 方舟 VPC Endpoint。

### 12.2 鉴权（必须先做）

- **API 网关层 authN（最小）**：在火山引擎 API 网关 [待确认] 或 ALB + 鉴权插件层做 API Key / JWT 校验。API 契约已定义 `401/403` 错误码，先在网关实现，不动应用代码。
- **应用层 authZ（后续）**：组织作用域（organization_scope）+ purpose 门禁 + sensitive 分区访问控制，需代码实现——当前 `AdmissionPolicy` 只做用途→图映射，不绑定调用方身份。

### 12.3 Sensitive 图

- Store 有读侧 `restricted_node_ids` 过滤 + `graph-sensitive-persona` 分区，但**这不是访问控制**，只是查询过滤。
- **部署决策**：在应用层 authZ 落地前，sensitive 图的实例数据**默认不进生产部署 bundle**（构建时排除 `data/instances/*sensitive*` 或按分区过滤）。
- [待确认] 当前 `data/instances/*.trig` 中是否含 sensitive 分区数据；若含，是否随首批部署。

### 12.4 其他

- **TLS**：ALB 终止 TLS（火山引擎证书服务 [待确认]），内部 VPC 流量可明文。
- **密钥**：见 §10，绝不进镜像/仓库。
- **审计日志**：启用火山引擎日志服务 [待确认] 收集 gunicorn access/error log + 请求 trace id（API 契约要求 `request_id`）。
- **依赖扫描**：CI 中加 `pip-audit` / Trivy 扫镜像，本设计建议项。

---

## 13. 最小可部署切片（先跑起来的最小集合）

> 目标：在火山引擎 VPC 内跑起一个可被内部调用的 TKOS API，验证端到端链路。**不含公网暴露、不含 authZ、不含 HA**。

**前置代码补丁（必须，本设计不实施）**：
1. `GET /health`、`GET /ready`、`GET /version` 三个端点（§6.3）。

**需要创建（非源码改动）**：
2. `Dockerfile`（多阶段或单阶段，基于 `python:3.11-slim`，`pip install -e '.[api]'`，COPY `src/` + `ontology/{schema,shapes,datasets}/` + `data/instances/`，CMD = §6.1 gunicorn）。
3. VKE Deployment + Service + HPA(可选) 的 K8s manifest（或 ECS 启动脚本）。
4. ConfigMap（非密）+ Secret（LLM 凭证）。

**最小云资源（火山引擎，产品名 [待确认]）**：
5. 一个 VPC + 私有子网 + NAT/VPC Endpoint（出向方舟）。
6. 一个 VKE 集群（或一台 ECS）。
7. 一个容器镜像服务 CR 实例 + 命名空间。
8. 一个 ALB/CLB（内网监听即可，试点期可先用 VPC 内访问不挂公网）。
9. 方舟 API Key（或先复用 DeepSeek 凭证）。

**最小验证**：
10. 部署后 `curl /version` 确认 `dataset_revision` 与预期一致。
11. `scripts/agent_harness.py` 对内网 LB 跑通。
12. 跑一次 `/v1/context-packs:render`（mode=llm_with_fallback）确认 LLM 链路通（或正确降级）。

---

## 14. 完整生产形态

在最小切片之上叠加：

| 维度 | 完整形态 |
|---|---|
| 计算 | VKE，2+ 副本跨可用区，HPA on CPU/RPS |
| 数据分发 | 阶段 B：TOS release bundle + manifest；镜像只含代码 |
| 推理 | CI SWRL 物化 blocking；启动 SHACL defense-in-depth |
| API 运行 | gunicorn + uvicorn worker，timeout/graceful 调优，可观测齐全 |
| LLM | 方舟同区域 VPC Endpoint（数据驻留），确定性链路兜底 |
| 版本 | 不停机滚动更新；release manifest 追溯；`/version` 暴露指纹 |
| CI/CD | GitHub Actions/火山引擎持续交付 → 镜像 CR → VKE 滚动；部署后自动验证 |
| 配置/密钥 | KMS 加密的 K8s Secret；`.env` 不进镜像 |
| 安全 | API 网关 + authN（API Key/JWT）；私有子网；TLS 终止于 ALB；审计日志；sensitive 图访问控制（应用层 authZ 落地后） |
| 扩展 | 只读 Store 水平扩容零代码成本；监控内存增长与冷启动时间拐点 |
| 可观测 | 日志服务 + 云监控 + trace id；`/version` + release manifest 对账 |
| 多 AZ | 节点池跨可用区，ALB 跨可用区分发 |

---

## 15. 待确认清单（汇总）

| # | 项 | 说明 |
|---|---|---|
| Q1 | 计算产品 | 火山引擎容器服务 VKE 还是自管 K8s on ECS；目标区域（`cn-beijing`/`cn-shanghai`） |
| Q2 | 节点规格 | VKE 节点池机型与可用区 |
| Q3 | 镜像仓库 | 火山引擎容器镜像服务 CR 实例/命名空间 + push 凭证获取方式 |
| Q4 | 对象存储 | TOS bucket（`tos-cn-<region>`）与阶段 B 迁移时机 |
| Q5 | 共享文件系统 | 若不用 TOS 拉取，是否用 NAS/CFS（不推荐） |
| Q6 | LLM 模型 | 方舟是否提供满足润色质量的模型（Doubao-pro / DeepSeek-V3 等）；具体 Endpoint ID |
| Q7 | LLM 网络 | 方舟 VPC Endpoint 配置；若留 DeepSeek 则需 NAT 网关出公网 |
| Q8 | 负载均衡 | ALB 还是 CLB；证书服务产品名 |
| Q9 | API 网关 | 火山引擎 API 网关产品名与 authN 方案 |
| Q10 | 密钥管理 | 火山引擎密钥管理服务（KMS）产品名与 K8s Secret 加密集成 |
| Q11 | 日志/监控 | 火山引擎日志服务 + 云监控产品名 |
| Q12 | CI/CD | 保留 GitHub Actions 还是迁火山引擎持续交付；CI→CR push 凭证 |
| Q13 | SWRL 触发 | CI 中 SWRL 物化作为 blocking 的触发时机（release tag vs main） |
| Q14 | Sensitive 图 | 当前 `data/instances/*.trig` 是否含 sensitive 分区数据；首批是否部署 |
| Q15 | 写路径时间线 | Submission/Confirmation 上线预期——决定是否需提前规划持久化 RDF Store |

---

## 16. 附录：环境变量映射表

| 变量 | 含义 | 示例 / 来源 | 敏感 | 注入方式 |
|---|---|---|---|---|
| `LLM_BASE_URL` | OpenAI 兼容 API 入口 | 方舟: `https://ark.cn-beijing.volces.com/api/v3`；DeepSeek: 现有值 | 半密 | Secret |
| `LLM_AUTH_TOKEN` | API Key | 方舟 API Key / DeepSeek token | **密** | Secret + KMS |
| `LLM_MODEL` | 模型名 / Endpoint ID | 方舟 `ep-xxxxxxxx` / DeepSeek 模型名 | 否 | ConfigMap |
| `TKOS_RELEASE_BUNDLE_URL` | 阶段 B：TOS bundle URL | `tos://bucket/releases/<rev>/bundle.tar.zst` | 否 | ConfigMap |
| `TKOS_RELEASE_MANIFEST_URL` | 阶段 B：manifest URL | `.../release-manifest.json` | 否 | ConfigMap |
| `TKOS_ENV` | （建议新增）环境标识 | `production` / `pilot` | 否 | ConfigMap |
| `TOS_ACCESS_KEY_ID` | 阶段 B：TOS 拉取 AK | 最小权限 RAM 子账号 | **密** | Secret + KMS |
| `TOS_SECRET_ACCESS_KEY` | 阶段 B：TOS 拉取 SK | 同上 | **密** | Secret + KMS |
| `GUNICORN_WORKERS` | worker 数 | `2` | 否 | Deployment env / CMD |
| `GUNICORN_TIMEOUT` | 请求超时 | `60` | 否 | Deployment env / CMD |
| `GUNICORN_GRACEFUL_TIMEOUT` | 优雅停机超时 | `35`（须 > p99 LLM 延迟） | 否 | Deployment env / CMD |

---

## 17. 决策摘要（一屏速览）

- **计算**：火山引擎 VKE（容器）+ gunicorn/uvicorn，2 副本起。冷启动只读内存图契合 Pod 滚动生命周期；水平扩展因只读 Store 而零代码成本。
- **数据**：当前打镜像（148K 零成本、无外部依赖）；未来 TOS + release manifest 解耦数据发布。
- **推理**：SHACL = 发布门禁（CI）+ 启动 defense-in-depth（可选）；SWRL = CI 物化产物，运行时不带 JVM。
- **LLM**：方舟为主（数据驻留 + 零代码切换），DeepSeek 兜底；缺失凭证自动降级到确定性链路。
- **版本**：镜像 tag 编码 `code-sha + dataset_revision + ontology_release_id`；只读副本滚动更新零迁移。
- **CI/CD**：保留 GitHub Actions，跨云 push 火山引擎 CR，滚动部署 VKE。
- **配置/密钥**：ConfigMap + KMS 加密 Secret，`.env` 不进镜像。
- **安全硬前置**：不直接暴露公网、API 网关 authN、sensitive 图默认不进首批部署。
- **必须用户确认**：Q1（VKE/区域）、Q3（CR 实例）、Q6（方舟模型）、Q14（sensitive 数据）等见 §15。
