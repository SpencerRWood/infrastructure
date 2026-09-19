#!/usr/bin/env bash

# Run only during a deliberate service/database onboarding operation.
set -euo pipefail

required_variables=(
  POSTGRES_ADMIN_URL
  POSTGRES_APP_DATABASE
  POSTGRES_RUNTIME_USER
  POSTGRES_RUNTIME_PASSWORD
  POSTGRES_MIGRATION_USER
  POSTGRES_MIGRATION_PASSWORD
)

for variable_name in "${required_variables[@]}"; do
  if [[ -z "${!variable_name:-}" ]]; then
    printf 'Missing required environment variable: %s\n' "$variable_name" >&2
    exit 1
  fi
done

script_directory="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

psql "$POSTGRES_ADMIN_URL" \
  --set ON_ERROR_STOP=1 \
  --set app_database="$POSTGRES_APP_DATABASE" \
  --set runtime_role="$POSTGRES_RUNTIME_USER" \
  --set runtime_password="$POSTGRES_RUNTIME_PASSWORD" \
  --set migration_role="$POSTGRES_MIGRATION_USER" \
  --set migration_password="$POSTGRES_MIGRATION_PASSWORD" \
  --file "$script_directory/bootstrap.sql"
