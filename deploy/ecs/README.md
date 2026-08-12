# TKOS Runtime — ECS 单机试点部署手册（cn-beijing）

> 范围：设计文档 [volcengine-deployment-design.md](../../docs/architecture/volcengine-deployment-design.md) 的**最小可部署切片**（§13），按已拍板决策执行：**ECS 单机 + cn-beijing + 方舟 Ark**。
> 前置：两个部署阻断项已在代码中修复（`server.py`：健康端点 + authN/authZ + 启动 SHACL + 客户端 pack purpose 门禁），测试 116 绿。

## 目录

1. [镜像构建与推送](#1-镜像构建与推送)
2. [ECS 主机准备](#2-ecs-主机准备)
3. [部署与启动](#3-部署与启动)
4. [CLB 健康检查与访问](#4-clb-健康检查与访问)
5. [部署后验证清单](#5-部署后验证清单)
6. [升级与回滚](#6-升级与回滚)
7. [已知限制](#7-已知限制)

---

## 1. 镜像构建与推送

构建（在仓库根目录；构建上下文已由 `.dockerignore` 收敛）：

```bash
DATASET_REV=$(python3 - <<'EOF'
from tkos_runtime.adapters.rdflib_dataset_store import RdfDatasetStore
from pathlib import Path
s = RdfDatasetStore(
    Path("ontology/schema/tkos-ontology.jsonld"),
    Path("ontology/datasets/tkos-runtime-dataset.trig"),
    sorted(Path("data/instances").glob("*.trig")),
    release_root=Path("."),
)
print(s.dataset_revision[:12])
EOF
)
TAG="$(git rev-parse --short HEAD)-${DATASET_REV}"
docker build -t "tkos-runtime:${TAG}" .
```

镜像 tag 编码 `code-sha + dataset_revision`（设计 §4：代码即制品、制品即版本）。`/version` 返回的 `dataset_revision` 前 16 位应与 tag 中的 12 位一致。

推送火山引擎容器镜像服务（CR，cn-beijing）：

```bash
docker tag "tkos-runtime:${TAG}" "cr.cn-beijing.volces.com/<namespace>/tkos-runtime:${TAG}"
docker login cr.cn-beijing.volces.com          # 用 CR 临时凭证或 RAM 子账号 AK/SK
docker push "cr.cn-beijing.volces.com/<namespace>/tkos-runtime:${TAG}"
```

## 2. ECS 主机准备

- 规格：**2 vCPU / 4 GiB 起步**（设计 §3，当前数据 ~150K，冷启动亚秒级）。
- 系统：Ubuntu 22.04 LTS（或同档），安装 Docker Engine。
- 网络：私有子网；出向放行 443 到 `ark.cn-beijing.volces.com`（方舟 API）。若后续走 VPC Endpoint 可收紧。
- 安全组：只放行 CLB 源 IP → 8000，以及运维 SSH（或堡垒机）。

放置目录：

```bash
sudo mkdir -p /opt/tkos/deploy/ecs
sudo cp deploy/ecs/{docker-run.sh,tkos-runtime.service,env.production.example} /opt/tkos/deploy/ecs/
cd /opt/tkos/deploy/ecs && sudo cp env.production.example .env && sudo chmod 600 .env
# 编辑 .env：TKOS_API_KEY（强随机）、LLM_AUTH_TOKEN（方舟 Key）、LLM_MODEL（ep-xxx）、TKOS_CODE_SHA
sudo chmod +x docker-run.sh
```

## 3. 部署与启动

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now tkos-runtime
journalctl -u tkos-runtime -f   # 看启动日志
```

启动后按 docker-run.sh 的烟测输出核对：`/health` 200 → `/ready` 200（`startup_shacl: pass`，因 `TKOS_STARTUP_SHACL=1`）→ `/version` 指纹与构建 tag 一致。

## 4. CLB 健康检查与访问

- 创建内网 CLB/ALB，后端指向 ECS:8000。
- 健康检查路径：**`/health`**（设计 §6.3：LB 单路径健康检查用 liveness；readiness 的 SHACL 状态由 `TKOS_STARTUP_SHACL` 在启动期决定，不依赖 LB）。
- 试点期可不绑定公网；内部调用走 CLB 内网地址。公网暴露前先完成 §5 验证。

## 5. 部署后验证清单

```bash
BASE=http://<CLB内网或ECS>:8000
KEY=<TKOS_API_KEY>

# 1. 指纹核对（与镜像 tag 对账）
curl -sS -H "Authorization: Bearer $KEY" $BASE/version

# 2. 认证/授权
curl -sS -o /dev/null -w '%{http_code}\n' $BASE/v1/context-packs:resolve   # 期望 401
curl -sS -H "Authorization: Bearer wrong" $BASE/v1/context-packs:resolve   # 期望 401

# 3. 端到端 resolve
curl -sS -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  $BASE/v1/context-packs:resolve -d '{
    "enterprise_id":"tokenking","organization_scope":[],
    "purpose":"decision_preparation",
    "query":"是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
    "as_of":"2026-08-12T23:59:59+08:00"}'

# 4. 渲染（LLM 链路：llm_with_fallback → 方舟，失败自动降级确定性）
curl -sS -X POST -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  $BASE/v1/context-packs:render -d '{
    "resolve_request":{
      "enterprise_id":"tokenking","organization_scope":[],
      "purpose":"decision_preparation",
      "query":"是否在本季度同时完成产品 1.0 上线和灯塔项目交付",
      "as_of":"2026-08-12T23:59:59+08:00"},
    "render_options":{"mode":"llm_with_fallback","max_chars":12000}}'
# 期望：200；mode_used 为 llm 或 deterministic（LLM 凭证/网络故障时降级）

# 5. agent harness 冒烟
.venv/bin/python scripts/agent_harness.py --base-url $BASE --api-key $KEY
```

## 6. 升级与回滚

- 新镜像构建 → push → `cd /opt/tkos/deploy/ecs && IMAGE=cr...:<新tag> sudo ./docker-run.sh`（先 `docker rm -f` 再启动）。
- 回滚：切回旧 tag 重跑 `docker-run.sh`。只读 Store、副本对等——无迁移、无脏状态。

## 7. 已知限制

- 单副本无 HA；试点期可接受。
- `TKOS_API_KEYS_JSON` 多调用方 purpose 细分（设计 B.2 v1.1）未启用——当前单 `TKOS_API_KEY` 全 purpose。
- `organization_scope` 尚未强制（`scope_resolution.enforcement=not_enforced`，设计明确 v1 不做）。
- 无敏感分区数据（实测 `data/instances` 无 `graph-sensitive-persona`），`TKOS_INCLUDE_SENSITIVE=0` 保持默认。
- 审计仅 gunicorn access log；`request_id` 链路为后续工作。
