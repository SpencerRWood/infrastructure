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

echo 'Checking Compose syntax...'
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  docker compose --project-directory environments/dev --env-file environments/dev/.env.example \
    -f environments/dev/compose.yaml config --quiet
  docker compose --project-directory environments/prod --env-file environments/prod/.env.example \
    -f environments/prod/compose.yaml config --quiet
else
  echo 'Docker Compose is unavailable; Compose validation skipped.'
fi

echo 'Checking canonical PostgreSQL Compose syntax...'
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  postgres_validation_env="$(mktemp)"
  trap 'rm -f "$postgres_validation_env"' EXIT
  cat >"$postgres_validation_env" <<'EOF'
POSTGRES_DB=wood_data
POSTGRES_USER=wood
POSTGRES_PASSWORD_FILE=/tmp/postgres-password
POSTGRES_DATA_PATH=/srv/data-platform/postgres/data
POSTGRES_INIT_PATH=/srv/docker/wood-data-platform/platform/postgres/init
POSTGRES_INTERNAL_NETWORK=wood-data-platform-db
POSTGRES_LAN_NETWORK=wood-data-platform-lan
POSTGRES_BIND_ADDRESS=192.168.1.21
POSTGRES_PORT=25432
EOF
  docker compose --env-file "$postgres_validation_env" -f compose/postgres/compose.yml config --quiet
fi

echo 'Checking patch whitespace...'
git diff --check

echo 'Validation completed.'
