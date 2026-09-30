#!/usr/bin/env bash
set -euo pipefail
image=${1:?Usage: test-oauth.sh IMAGE}
builder_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
name="contextforge-oauth-test-${RANDOM}"
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
docker create --name "$name" --network none \
  -e DATABASE_URL=sqlite:////tmp/oauth-test.db \
  -e JWT_SECRET_KEY="$(openssl rand -base64 32)" \
  -e AUTH_ENCRYPTION_SECRET="$(openssl rand -base64 32)" \
  -e PLATFORM_ADMIN_PASSWORD="$(openssl rand -base64 24)" \
  -e DEFAULT_USER_PASSWORD="$(openssl rand -base64 24)" \
  -e BASIC_AUTH_PASSWORD="$(openssl rand -base64 24)" \
  -e APP_DOMAIN=https://gateway.example.com \
  --entrypoint /app/.venv/bin/python "$image" /tmp/test_oauth_scopes.py
docker cp "$builder_dir/tests/test_oauth_scopes.py" "$name:/tmp/test_oauth_scopes.py"
docker start -a "$name"
test "$(docker inspect -f '{{.State.ExitCode}}' "$name")" = 0
