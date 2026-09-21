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

echo 'Checking canonical PostgreSQL Compose syntax...'
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
  postgres_validation_env="$(mktemp)"
  trap 'rm -f "$postgres_validation_env"' EXIT
  cat >"$postgres_validation_env" <<'EOF'
POSTGRES_DB=postgres
POSTGRES_USER=postgres
POSTGRES_PASSWORD_FILE=/tmp/postgres-password
POSTGRES_DATA_PATH=/srv/infrastructure/state/postgres/data
POSTGRES_NETWORK=infrastructure-dev-postgres
POSTGRES_PROJECT_NAME=infrastructure-dev-postgres
EOF
  docker compose --env-file "$postgres_validation_env" -f compose/postgres/compose.yml config --quiet
else
  echo 'Docker Compose is unavailable; Compose validation skipped.'
fi

echo 'Checking patch whitespace...'
git diff --check

echo 'Validation completed.'
