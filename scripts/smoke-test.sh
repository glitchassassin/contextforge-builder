#!/usr/bin/env bash
set -euo pipefail
image=${1:?Usage: smoke-test.sh IMAGE [default|uvicorn]}
mode=${2:-default}
case "$mode" in default|uvicorn) ;; *) echo "Unknown startup mode: $mode" >&2; exit 2 ;; esac
name="contextforge-smoke-${mode}-${RANDOM}"
log_dir=${SMOKE_LOG_DIR:-smoke-logs}
mkdir -p "$log_dir"
cleanup() {
  docker logs "$name" > "$log_dir/$mode.log" 2>&1 || true
  tail -n 100 "$log_dir/$mode.log"
  docker rm -f "$name" >/dev/null 2>&1 || true
}
trap cleanup EXIT
# Isolated disposable container: no production credentials or data.
# Base64 avoids the entropy-floor failures possible with a hex-only alphabet.
jwt_secret=$(openssl rand -base64 32)
encryption_secret=$(openssl rand -base64 32)
admin_password=$(openssl rand -base64 24)
user_password=$(openssl rand -base64 24)
basic_password=$(openssl rand -base64 24)
if [ "${GITHUB_ACTIONS:-}" = true ]; then
  for secret in "$jwt_secret" "$encryption_secret" "$admin_password" "$user_password" "$basic_password"; do
    echo "::add-mask::$secret"
  done
fi
run_args=(
  -d --name "$name"
  -e HOST=0.0.0.0 -e PORT=4444
  -e DATABASE_URL=sqlite:////tmp/mcp.db
  -e JWT_SECRET_KEY="$jwt_secret"
  -e AUTH_ENCRYPTION_SECRET="$encryption_secret"
  -e PLATFORM_ADMIN_EMAIL=smoke@example.com
  -e PLATFORM_ADMIN_PASSWORD="$admin_password"
  -e DEFAULT_USER_PASSWORD="$user_password"
  -e BASIC_AUTH_PASSWORD="$basic_password"
  -e MCPGATEWAY_UI_ENABLED=true
  -e MCPGATEWAY_ADMIN_API_ENABLED=true
  -e EMAIL_AUTH_ENABLED=true
  -e AUTH_REQUIRED=true -e MCP_REQUIRE_AUTH=true
  -e GUNICORN_WORKERS=2
  -e LLM_API_PREFIX=/llm/v1
)
command_args=()
if [ "$mode" = uvicorn ]; then
  run_args+=(--entrypoint /app/.venv/bin/uvicorn)
  command_args=(mcpgateway.main:app --host 0.0.0.0 --port 4444)
fi
docker run "${run_args[@]}" "$image" "${command_args[@]}"
healthy=false
for attempt in $(seq 1 60); do
  if docker exec "$name" /app/.venv/bin/python -c \
    "import httpx; r=httpx.get('http://127.0.0.1:4444/health',timeout=5); r.raise_for_status(); assert r.status_code == 200 and r.json().get('status') == 'healthy', r.text"; then
    healthy=true
    break
  fi
  if [ "$(docker inspect -f '{{.State.Running}}' "$name")" != true ]; then
    echo "Container exited during $mode startup" >&2
    exit 1
  fi
  sleep 5
done
if [ "$healthy" != true ]; then
  echo "Health check did not pass within five minutes ($mode)" >&2
  exit 1
fi
docker exec "$name" /app/.venv/bin/python -c \
  "import httpx; r=httpx.get('http://127.0.0.1:4444/admin/login',timeout=10); r.raise_for_status(); assert r.status_code == 200 and 'Sign In - ContextForge' in r.text, 'Admin login page failed to render'"
docker logs "$name" > "$log_dir/$mode.log" 2>&1
if grep -E 'Control server error|Read-only file system|SIGKILL|Perhaps out of memory|^Traceback \(most recent call last\)' "$log_dir/$mode.log"; then
  echo "Container logged startup/runtime errors ($mode)" >&2
  exit 1
fi
echo "Health payload, admin login page, and runtime logs passed ($mode)"
