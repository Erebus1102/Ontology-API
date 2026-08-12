#!/usr/bin/env bash
# TKOS Runtime — ECS single-node pilot launcher (cn-beijing).
#
# Usage:
#   IMAGE=cr.cn-beijing.volces.com/<namespace>/tkos-runtime:<tag> ./docker-run.sh
#   ./docker-run.sh              # default image name below
#
# Requirements on the ECS host:
#   * docker engine (or container runtime) installed and started
#   * .env file next to this script with production values
#     (cp env.production.example .env && edit)
#
# Health gate: waits for /health 200, then prints /ready and /version
# fingerprints for the smoke checklist.
set -euo pipefail

cd "$(dirname "$0")"

IMAGE="${IMAGE:-cr.cn-beijing.volces.com/tkos/tkos-runtime:latest}"
NAME="tkos-runtime"
PORT="${PORT:-8000}"

if [[ ! -f .env ]]; then
  echo "ERROR: .env missing — cp env.production.example .env and fill in values." >&2
  exit 1
fi

docker rm -f "$NAME" >/dev/null 2>&1 || true

docker run -d \
  --name "$NAME" \
  --restart unless-stopped \
  -p "$PORT:8000" \
  --env-file .env \
  "$IMAGE"

echo "container started: $NAME ($IMAGE)"
echo "waiting for /health ..."
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "  /health OK (attempt $i)"
    break
  fi
  [[ $i -eq 60 ]] && { echo "ERROR: /health not reachable after 60s" >&2; exit 1; }
  sleep 1
done

echo "--- /ready ---"
curl -sS "http://127.0.0.1:$PORT/ready"
echo
echo "--- /version (needs TKOS_API_KEY from .env) ---"
KEY="$(grep '^TKOS_API_KEY=' .env | cut -d= -f2-)"
curl -sS -H "Authorization: Bearer $KEY" "http://127.0.0.1:$PORT/version"
echo
echo "smoke: ./scripts/agent_harness.py --base-url http://127.0.0.1:$PORT --api-key \$TKOS_API_KEY"
