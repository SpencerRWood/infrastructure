#!/usr/bin/env bash

set -euo pipefail

repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"

echo 'Checking shell syntax...'
bash -n scripts/validate.sh scripts/health-check-dev.sh \
  scripts/health-check-dev-remote.sh postgres/scripts/provision-database.sh

echo 'Checking deployment readiness behavior...'
if command -v uv >/dev/null 2>&1; then
  PYTHONDONTWRITEBYTECODE=1 uv run python -m unittest discover -s tests
elif [[ -x .venv/bin/python ]]; then
  PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests
else
  echo 'Validation requires uv or a synced .venv/bin/python.' >&2
  exit 1
fi

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
  website_validation_env="$(mktemp)"
  events_validation_env="$(mktemp)"
  rag_validation_env="$(mktemp)"
  automerge_validation_env="$(mktemp)"
  trap 'rm -f "$postgres_validation_env" "$caddy_validation_env" "$website_validation_env" "$events_validation_env" "$rag_validation_env" "$automerge_validation_env"' EXIT
  printf '%s\n' \
    'POSTGRES_DB=postgres' \
    'POSTGRES_USER=postgres' \
    'POSTGRES_PASSWORD_FILE=/tmp/postgres-password' \
    'POSTGRES_DATA_PATH=/srv/infrastructure/state/postgres/data' \
    'POSTGRES_NETWORK=infrastructure-dev-postgres' \
    'POSTGRES_LAN_NETWORK=infrastructure-dev-postgres-lan' \
    'POSTGRES_PROJECT_NAME=infrastructure-dev-postgres' \
    'POSTGRES_LAN_BIND=192.168.1.21' \
    'POSTGRES_LAN_PORT=25433' >"$postgres_validation_env"
  printf '%s\n' \
    'CADDY_PROJECT_NAME=infrastructure-dev-caddy' \
    'CADDY_HTTP_BIND=192.168.1.21:8080' \
    'CADDY_HTTPS_BIND=192.168.1.21:8443' \
    'CADDYFILE_PATH=/srv/infrastructure/compose/caddy/Caddyfile' \
    'CADDY_ROUTES_PATH=/srv/infrastructure/compose/caddy/routes' \
    'CADDY_DATA_PATH=/srv/infrastructure/state/caddy/data' \
    'CADDY_CONFIG_PATH=/srv/infrastructure/state/caddy/config' \
    'CADDY_PROXY_NETWORK=infrastructure-dev-proxy' >"$caddy_validation_env"
  printf '%s\n' \
    'WEBSITE_PORTFOLIO_PROJECT_NAME=infrastructure-dev-website-portfolio' \
    'WEBSITE_PORTFOLIO_IMAGE_REF=ghcr.io/spencerrwood/website-portfolio:v0.6.0@sha256:743d194b77a7f54e8a4f454a22b0cdf5a36113e10c455af0088658175970740e' \
    'WEBSITE_PORTFOLIO_RUNTIME_ENV_FILE=/dev/null' \
    'WEBSITE_PORTFOLIO_MIGRATION_ENV_FILE=/dev/null' \
    'WEBSITE_PORTFOLIO_POSTGRES_NETWORK=infrastructure-dev-postgres' \
    'WEBSITE_PORTFOLIO_PROXY_NETWORK=infrastructure-dev-proxy' >"$website_validation_env"
  docker compose --env-file "$postgres_validation_env" -f compose/postgres/compose.yml config --quiet
  docker compose --env-file "$caddy_validation_env" -f compose/caddy/compose.yml config --quiet
  docker compose --env-file "$website_validation_env" -f compose/website-portfolio/compose.yml config --quiet
  # Syntax fixtures only: this image is never pulled or deployed by validation.
  printf '%s\n' \
    'EVENTS_SERVICE_PROJECT_NAME=syntax-events' \
    'EVENTS_SERVICE_IMAGE_REF=syntax-only/events:test' \
    'EVENTS_SERVICE_BROKER_ENV_FILE=/dev/null' \
    'EVENTS_SERVICE_NOTIFY_ENV_FILE=/dev/null' \
    'EVENTS_SERVICE_POSTGRES_NETWORK=syntax-postgres' \
    'EVENTS_SERVICE_PROXY_NETWORK=syntax-proxy' >"$events_validation_env"
  docker compose --env-file "$events_validation_env" -f compose/events-service/compose.yml config --quiet
  printf '%s\n' \
    'RAG_SERVICE_PROJECT_NAME=infrastructure-dev-rag-service' \
    'RAG_SERVICE_IMAGE_REF=ghcr.io/spencerrwood/rag-service:v0.1.0@sha256:83be558d8a7bb509d2b673f22d1b34438b354eb738ba7242a4157a9321653cf5' \
    'RAG_SERVICE_RELEASE_TAG=v0.1.0' \
    'RAG_SERVICE_SOURCE_REVISION=21380620d3c951863a5abadae5e528360cbb73c5' \
    'RAG_SERVICE_RUNTIME_ENV_FILE=/dev/null' \
    'RAG_SERVICE_MIGRATION_ENV_FILE=/dev/null' \
    'RAG_SERVICE_DAGSTER_ENV_FILE=/dev/null' \
    'RAG_SERVICE_DOCUMENTS_PATH=/tmp/rag-documents' \
    'RAG_SERVICE_DAGSTER_CONFIG_PATH=/tmp/dagster-config' \
    'RAG_SERVICE_DAGSTER_LOCAL_PATH=/tmp/dagster-local' \
    'RAG_SERVICE_POSTGRES_NETWORK=infrastructure-dev-postgres' \
    'RAG_SERVICE_PROXY_NETWORK=infrastructure-dev-proxy' >"$rag_validation_env"
  docker compose --env-file "$rag_validation_env" -f compose/rag-service/compose.yml config --quiet
  # Syntax fixture only; no image is pulled or deployed.
  printf '%s\n' \
    'AUTOMERGE_REPAIR_PROJECT_NAME=syntax-automerge-repair' \
    'AUTOMERGE_REPAIR_IMAGE_REF=syntax-only/automerge-repair:test' \
    'AUTOMERGE_REPAIR_RUNTIME_ENV_FILE=/dev/null' \
    'AUTOMERGE_REPAIR_POLICY_PATH=/tmp/policy.toml' \
    'AUTOMERGE_REPAIR_DAGSTER_CONFIG_PATH=/tmp/dagster-config' \
    'AUTOMERGE_REPAIR_DAGSTER_LOCAL_PATH=/tmp/dagster-local' \
    'AUTOMERGE_REPAIR_POSTGRES_NETWORK=syntax-postgres' \
    'AUTOMERGE_REPAIR_PROXY_NETWORK=syntax-proxy' >"$automerge_validation_env"
  docker compose --env-file "$automerge_validation_env" -f compose/automerge-repair/compose.yml config --quiet
  env \
    INFISICAL_PROJECT_NAME=infrastructure-dev-infisical \
    INFISICAL_IMAGE_TAG=test \
    INFISICAL_RUNTIME_ENV_FILE=/dev/null \
    INFISICAL_REDIS_PATH=/tmp/infisical-redis \
    INFISICAL_POSTGRES_NETWORK=infrastructure-dev-postgres \
    INFISICAL_PROXY_NETWORK=infrastructure-dev-proxy \
    docker compose -f compose/infisical/compose.yml config --quiet
  docker run --rm \
    -v "$repository_root/compose/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" \
    -v "$repository_root/compose/caddy/routes:/etc/caddy/routes:ro" \
    caddy:2.11.2-alpine caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
else
  echo 'Docker Compose is unavailable; Compose and Caddy validation skipped.'
fi

echo 'Checking patch whitespace...'
git diff --check

echo 'Validation completed.'
