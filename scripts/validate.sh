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

echo 'Checking patch whitespace...'
git diff --check

echo 'Validation completed.'
