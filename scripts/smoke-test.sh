#!/usr/bin/env bash
set -euo pipefail
image=${1:?Usage: smoke-test.sh IMAGE}
name="contextforge-smoke-${RANDOM}"
cleanup() {
  docker logs --tail 100 "$name" || true
  docker rm -f "$name" >/dev/null || true
}
trap cleanup EXIT
# Isolated disposable container: no production credentials or data.
docker run -d --name "$name" \
  --entrypoint /app/.venv/bin/uvicorn \
  -e DATABASE_URL=sqlite:////tmp/mcp.db \
  -e JWT_SECRET_KEY="$(openssl rand -hex 32)" \
  -e AUTH_ENCRYPTION_SECRET="$(openssl rand -hex 32)" \
  -e PLATFORM_ADMIN_EMAIL=smoke@example.com \
  -e PLATFORM_ADMIN_PASSWORD="$(openssl rand -hex 32)" \
  -e DEFAULT_USER_PASSWORD="$(openssl rand -hex 32)" \
  -e BASIC_AUTH_PASSWORD="$(openssl rand -hex 32)" \
  -e LLM_API_PREFIX=/llm/v1 \
  "$image" mcpgateway.main:app --host 0.0.0.0 --port 4444
for attempt in $(seq 1 60); do
  if docker exec "$name" /app/.venv/bin/python -c \
    "import httpx; r=httpx.get('http://127.0.0.1:4444/health',timeout=5); r.raise_for_status()"; then
    exit 0
  fi
  if [ "$(docker inspect -f '{{.State.Running}}' "$name")" != true ]; then
    exit 1
  fi
  sleep 5
done
echo 'Health check did not pass within five minutes' >&2
exit 1
