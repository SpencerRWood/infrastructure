#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

echo 'Checking shell syntax...'
bash -n scripts/validate.sh postgres/scripts/provision-database.sh

echo 'Checking for tracked credential files...'
tracked_credentials="$(git ls-files | rg '(^|/)(\.env($|\.)|id_rsa$|.*\.(pem|key)$|credentials(\.|$))' | rg -v '(^|/)\.env\.example$' || true)"
if [[ -n "$tracked_credentials" ]]; then
  printf 'Refusing tracked credential-like files:\n%s\n' "$tracked_credentials" >&2
  exit 1
fi

echo 'Checking canonical Compose and Caddy syntax...'
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  postgres_validation_env="$(mktemp)"
  caddy_validation_env="$(mktemp)"
  trap 'rm -f "$postgres_validation_env" "$caddy_validation_env"' EXIT
  printf '%s\n' \
    'POSTGRES_DB=postgres' \
    'POSTGRES_USER=postgres' \
    'POSTGRES_PASSWORD_FILE=/tmp/postgres-password' \
    'POSTGRES_DATA_PATH=/srv/infrastructure/state/postgres/data' \
    'POSTGRES_NETWORK=infrastructure-dev-postgres' \
    'POSTGRES_PROJECT_NAME=infrastructure-dev-postgres' >"$postgres_validation_env"
  printf '%s\n' \
    'CADDY_PROJECT_NAME=infrastructure-dev-caddy' \
    'CADDY_HTTP_BIND=127.0.0.1:8080' \
    'CADDY_HTTPS_BIND=127.0.0.1:8443' \
    'CADDYFILE_PATH=/srv/infrastructure/compose/caddy/Caddyfile' \
    'CADDY_DATA_PATH=/srv/infrastructure/state/caddy/data' \
    'CADDY_CONFIG_PATH=/srv/infrastructure/state/caddy/config' \
    'CADDY_PROXY_NETWORK=infrastructure-dev-proxy' >"$caddy_validation_env"
  docker compose --env-file "$postgres_validation_env" -f compose/postgres/compose.yml config --quiet
  docker compose --env-file "$caddy_validation_env" -f compose/caddy/compose.yml config --quiet
  docker run --rm -v "$repository_root/compose/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" \
    caddy:2.11.2-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
else
  echo 'Docker Compose is unavailable; Compose and Caddy validation skipped.'
fi

echo 'Checking patch whitespace...'
git diff --check

echo 'Validation completed.'
