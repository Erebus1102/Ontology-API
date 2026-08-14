# Runtime 2.0 部署方案

状态：draft（2026-08-13，配套 `docs/mvp/04` 基座迭代）
权威范围：**2.0 部署形态与基础设施决策的唯一权威**。回答四个问题：要不要数据库、要不要文件系统存业务文档、还缺什么基础设施、以及每项的演进触发条件。
设计原则：与本体/API 同一条——**支撑业务闭环前提下的最简部署**。每个"不上"的设施都必须写明触发条件，触发前不预建。

---

## 0. 现状底座（2.0 的起点，不推倒）

```text
火山引擎 ECS（cn-beijing，单节点）115.190.213.44
  └─ systemd (tkos-runtime.service)
       └─ Docker 容器（--restart unless-stopped）
            └─ gunicorn + FastAPI，端口 8000（裸 HTTP）
                 └─ rdflib 内存图：schema + shapes + dataset + instances
                    全部烘进镜像，tag = <code-sha>-<dataset-rev12>
  .env（TKOS_API_KEY 等，不进 git）
```

数据总量：ontology 164K + instances 172K，**内存图承载余量为四个数量级**，任何"上库提性能"的论证在此规模下不成立。

这个底座有一个正确得值得保护的性质：**镜像 tag = 代码 + 数据的联合版本指针**。部署即固定、回滚即换 tag、code 与 dataset_revision 永不漂移——这就是 AGENTS.md 要求的"可验证的发布指针"在 MVP 阶段的实现。2.0 保持它。

## 1. 要不要数据库 —— 不要

| 判据 | 2.0 事实 |
|---|---|
| 写并发 | 零（2.0 无写路径；迭代 2 也是单写者 + append-only） |
| 数据量 | <1MB，内存图即索引 |
| 多实例一致性 | 单节点单服务 |
| 查询形态 | BFS 深度 2 + 固定模板，rdflib 足够 |

**git 就是 2.0 的数据库**：trig 文件版本控制 = 存储 + 修订历史 + 审计 + 备份（remote）。RDF Store（Fuseki/GraphDB 等）的**触发条件**（满足任一才立项，写入 `docs/decisions/`）：

1. 写路径出现**多写者**需求（迭代 2 的单写者模型被业务推翻）；
2. 单租户实例数据超 ~50MB 或 resolve p99 超预算；
3. 需要多实例横向扩展（内存图无法跨进程一致）。

**迭代 2 的预埋（本轮只留缝，不实现）**：写路径出现时，数据必须离开镜像（否则容器重启丢写入），切换为**挂载卷 + append-only trig 目录**。镜像 tag 退化为纯代码指针，dataset_revision 由卷内容哈希提供。切换点在迭代 2 spec 里定，本轮 Dockerfile 不改。

## 2. 要不要文件系统存业务文档 —— 不要（服务器上不要）

业务文档（飞书快照、蒸馏源材料、SourceSnapshot）**留在 git 仓库，不上服务器**：

- 蒸馏是**本地 CLI 工序**（文档三 §1：蒸馏不是 API），产物（候选 trig）经确认后进 `data/instances/` 随镜像发布；
- 服务器只需要蒸馏的**结果**，不需要原料；
- git 历史天然满足 SourceSnapshot 的不可变要求。

对象存储（火山 TOS）的**触发条件**：API 2 蒸馏服务化（房懂懂/AIDC 租户自助上传文档）——届时上传文件需要落地点和生命周期管理。触发前不建桶。

## 3. 基础设施缺口清单（架构师裁定：2 个必须补，其余明确不做）

### 3.1 必须补 P0：传输安全（2.0 上线门禁）

**这是当前部署唯一的真实安全缺口**：裸 HTTP + Bearer Key 明文传输，Key 一次嗅探即泄漏。1.0 时 Key 只是开关；**2.0 起 Key 承载租户/角色/确认人/Persona 锚点五重身份**（doc 04 §4），泄漏面从"能不能调"升级为"以谁的名义确认决策"。Key 模型上线而传输不加密，是治理设计自我否定。

方案（最简）：

```text
Internet ──443/TLS──> Caddy 容器（自动证书） ──127.0.0.1:8000──> tkos-runtime
```

- 一个子域名（如 `tkos.tokenking.ai`）解析到 ECS，Caddy 自动签发/续期 Let's Encrypt 证书，配置 ~5 行；
- 安全组收紧：入站仅 `443` + SSH；`8000` 绑回 `127.0.0.1`（docker-run.sh 改 `-p 127.0.0.1:8000:8000`）；
- 无域名的过渡形态：火山 CLB 托管证书或自签 + 调用方固定指纹——**不允许的形态只有一种：裸 HTTP 上生产 Key**。

### 3.2 必须补 P0：Key 注册表的秘密管理与轮换

- `TKOS_API_KEYS_JSON`（含 Key 明文）只存服务器 `.env`，权限 `600`，**永不进 git**；
- 注册表的**非密钥部分**（tenant/role/on_behalf_of/confirmer/default_scenario per key-name）以脱敏形态版本控管（`deploy/ecs/key-registry.example.json`），变更走 git commit = 审计事件（doc 03 §2）；
- 轮换流程：新旧 Key 并存于 JSON → 通知调用方切换 → 删旧 Key，全程不停机（authN 逐请求读环境快照）；
- 泄漏应急：删除该 Key 条目 + 重启容器（秒级），审计经 journald 按 key-name 回溯。

### 3.3 应补 P1（不阻塞 2.0 上线，本迭代内完成）

| 项 | 最简做法 |
|---|---|
| 日志持久化 | journald 开持久存储（`Storage=persistent` + `SystemMaxUse=1G`）；请求日志含 `request_id` + key-name，**永不含 Key 本体** |
| 监控告警 | 云监控 HTTP 拨测 `/health`（1 分钟间隔）+ ECS 磁盘/内存告警 → 飞书 webhook。不上 Prometheus/Grafana |
| 时钟 | chrony/NTP 确认同步——`as_of`/`validFrom`/`recordedAt` 全部依赖系统时钟，时钟漂移即时序投影漂移 |
| 构建门禁 | 镜像构建脚本前置 `make test-fast`；构建仍手工触发（发布频率不支撑 CI 流水线） |
| 回滚演练 | `IMAGE=<上一 tag> ./docker-run.sh` 实测一次并记录耗时——V3.0 是破坏性 Release，回滚指针必须被验证过，不是被声明过 |

### 3.4 明确不做（有触发条件才立项）

| 设施 | 不做的理由 | 触发条件 |
|---|---|---|
| RDF Store / 数据库 | §1 | §1 三条任一 |
| 对象存储 | §2 | API 2 服务化 |
| 消息队列 / 异步 Worker | 无异步任务（蒸馏在本地） | API 2 服务化 |
| 多节点 / 负载均衡 | 单节点内存图余量巨大；调用方是单一平台后端 | resolve p99 超预算或可用性 SLA 要求出现 |
| CI/CD 流水线 | 发布频率低，手工脚本 + 构建门禁足够 | 每周多次发布成为常态 |
| 容器编排（K8s） | 一个容器 + systemd 已覆盖重启/开机自启 | 多节点触发后一并评估 |
| 密钥管理服务（KMS） | `.env` + 600 权限与当前威胁模型匹配 | 多租户 Key 数量 >10 或合规要求 |

## 4. 2.0 部署形态（目标图）

```text
Internet
  │ 443 TLS
  ▼
Caddy（自动证书，容器）
  │ 127.0.0.1:8000
  ▼
tkos-runtime 容器（镜像 = code-sha + dataset-rev12，数据烘焙）
  ├─ .env：TKOS_API_KEYS_JSON（多 Key：tenant/role/on_behalf_of/confirmer）
  ├─ 单 gunicorn worker 组，各自加载内存图（只读，无一致性问题）
  └─ journald 持久化日志
git remote = 数据备份 + 修订审计
镜像仓库（火山 CR）保留最近 5 个 tag = 回滚指针链
```

**多 worker 说明**：2.0 只读，workers 各持图副本无一致性问题。迭代 2 的单写者模型要求写路径收敛到单 worker 或独立写进程——这是迭代 2 spec 的部署章节要解决的第一个问题，此处立此存照。

## 5. 上线检查单（2.0 发布门禁）

1. [ ] TLS 生效：`curl https://…/health` 200，裸 HTTP 端口外网不可达；
2. [ ] 安全组：入站仅 443/SSH；8000 仅本机；
3. [ ] 多 Key 生效：cxo/executor/第二租户三个 Key，`/version` 各返回正确身份；跨租户 404 负向用例在生产环境通过；
4. [ ] `.env` 权限 600，git 仓库内无 Key 明文（`git grep` 校验）；
5. [ ] 镜像 tag 含 V3.0 后的 dataset-rev；`/ready` 的 SHACL 启动校验通过；
6. [ ] 回滚演练完成：切回上一 tag、验证 FE 场景 resolve、再切回，全程记录；
7. [ ] journald 持久化生效；拨测告警触达飞书验证一次；
8. [ ] Apifox 用例（旧字段 deprecated 双轨）对生产 URL 全绿；
9. [ ] Apifox v1 双轨用例（用例 14–15：scenario task_followup→mission_review 版本块断言、render:true）对生产 URL 转绿；
10. [ ] 发布制品时推进本体 Release 号至 **3.0.0**（V3.0 为破坏性 TBox 变更，`owl:versionInfo` 已推进；`/version` 与 Pack 的 `ontology_release.company` 必须显示 "3.0.0"，不得回退旧值——这是部署步骤，不是台账愿望）。

## 6. 与迭代路线图的部署演进对照

| 迭代 | 部署变化 |
|---|---|
| **2.0（本轮）** | +TLS/Caddy、+多 Key 注册表、+日志持久化/拨测告警、镜像照常烘焙数据 |
| 迭代 1（Lineage） | 无新设施（新端点走同一容器）；删除 deprecated 字段随镜像发布 |
| 迭代 2（Submissions） | **数据出镜像**：挂载卷 + append-only trig + 单写者进程模型 + 卷备份策略（每日 git push 或 tar → 快照）——迭代 2 spec 单列部署章节 |
| API 2 服务化（触发式） | +对象存储 +异步 Worker，届时重评估 RDF Store |
