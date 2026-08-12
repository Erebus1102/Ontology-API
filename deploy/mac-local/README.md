# TKOS Runtime — Mac 本机反代部署手册

> 方案（2026-08-12 调整）：**不部署火山引擎服务器**，TKOS 容器在本机运行，Caddy 反代 + 自动 HTTPS 对外提供 API。
> 保留备用路径：`../ecs/`（火山引擎 ECS 部署物，后续需要时可用）。
> 前置：Docker Desktop 运行中；`tkos-runtime` 镜像已构建（见下）。

## 拓扑

```
公网 ──HTTPS──▶ Caddy (本机:80/443) ──▶ tkos 容器 (compose 网络内:8000)
                    │
                    └── 本机调试直连: http://127.0.0.1:8000（仅回环）
```

## 1. 准备域名与网络

- 域名（或子域）加 A 记录 → 本机公网 IP。
- 路由器/防火墙放行 **80**（ACME challenge + HTTP 跳转）与 **443**。
- 若公网 IP 会变，先配好 DDNS（如 cloudflare-ddns / 路由器自带）再映射域名。

## 2. 构建镜像（若尚未构建）

```bash
docker build -t tkos-runtime:latest .
```

tag 规范：`tkos-runtime:<code-sha>-<dataset-rev12>`（`/version` 返回的 `dataset_revision` 前 12 位与 tag 一致）。

## 3. 配置与启动

```bash
cd deploy/mac-local
cp .env.example .env        # 填 TKOS_API_KEY（强随机）、LLM_*（方舟/DeepSeek）、TKOS_CODE_SHA
# Caddyfile 已配好域名 api.tokenking-ontologyfetch.com；如换域名改这里
docker compose up -d
```

首次启动后等证书签发（`docker compose logs -f caddy`，看到 certificate obtained 即可）。

## 4. 验证清单

```bash
KEY=<TKOS_API_KEY>
BASE=https://api.tokenking-ontologyfetch.com

# 指纹核对（code_sha 与 dataset_revision 应对得上构建时的 tag）
curl -sS -H "Authorization: Bearer $KEY" $BASE/version

# 401（无/错 token）
curl -sS -o /dev/null -w '%{http_code}\n' -X POST $BASE/v1/context-packs:resolve
curl -sS -o /dev/null -w '%{http_code}\n' -X POST $BASE/v1/context-packs:resolve -H "Authorization: Bearer wrong"

# resolve
curl -sS -X POST $BASE/v1/context-packs:resolve -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d '{
  "enterprise_id":"tokenking","organization_scope":[],"purpose":"decision_preparation",
  "query":"是否在本季度同时完成产品 1.0 上线和灯塔项目交付","as_of":"2026-08-12T23:59:59+08:00"}'

# render（llm_with_fallback：LLM 失败自动降级确定性链路）
curl -sS -X POST $BASE/v1/context-packs:render -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" -d '{
  "resolve_request":{"enterprise_id":"tokenking","organization_scope":[],"purpose":"decision_preparation",
    "query":"是否在本季度同时完成产品 1.0 上线和灯塔项目交付","as_of":"2026-08-12T23:59:59+08:00"},
  "render_options":{"mode":"llm_with_fallback","max_chars":12000}}'

# 本机直连调试（不经 Caddy）
curl -sS http://127.0.0.1:8000/health
```

## 5. 日常运维

| 操作 | 命令 |
|---|---|
| 日志（TKOS / Caddy） | `docker compose logs -f tkos` / `docker compose logs -f caddy` |
| 重启 | `docker compose restart` |
| 升级（新镜像） | 构建新 tag → 改 `docker-compose.yml` 的 image → `docker compose up -d` |
| 回滚 | 改回旧 tag → `docker compose up -d`（只读 Store，无迁移） |
| 停机 | `docker compose down` |

## 6. 已知限制

- 单机单副本，无 HA；Mac 关机即服务不可用。
- 公网暴露依赖 80/443 可达（ACME 需要 80）；运营商封 80 时需换方案（隧道）。
- `organization_scope` 尚未强制；`TKOS_API_KEYS_JSON` 多调用方细分未启用（v1 单 key）。
- 审计仅容器 access log。
