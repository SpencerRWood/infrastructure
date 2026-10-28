#!/usr/bin/env bash
# Restore only Events, refusing any schema downgrade that could discard evidence.
set -euo pipefail
previous_release=${1:?previous Infrastructure release required}
[[ "$previous_release" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]
previous_image=$(git -c safe.directory="$PWD" show "$previous_release:environments/dev.yml" | \
  /usr/bin/python3 -c 'import sys,yaml; print(yaml.safe_load(sys.stdin)["events_service_image_ref"])')
[[ "$previous_image" =~ ^ghcr\.io/spencerrwood/events-service:v[0-9]+\.[0-9]+\.[0-9]+@sha256:[0-9a-f]{64}$ ]]
compose_env=/srv/infrastructure/secrets/dev/events-service-compose.env
compose_file=/srv/infrastructure/compose/events-service/compose.yml
export DOCKER_CONFIG=/srv/infrastructure/secrets/dev/ghcr-docker
compose=(docker compose --env-file "$compose_env" -f "$compose_file")
target_schema=$(docker run --rm --network none --entrypoint python "$previous_image" -c '
from pathlib import Path
from alembic.script import ScriptDirectory
import events_service
print(ScriptDirectory(str(Path(events_service.__file__).parent / "migrations")).get_current_head())
')
[[ "$target_schema" == 0005_recovery_parts || "$target_schema" == 0006_interactive_edits ]]
# Quiesce both application writers before checking/downgrading the schema.
# Otherwise a new edit could race the migration's empty-table retention guard.
"${compose[@]}" stop wood-broker wood-notify
if ! "${compose[@]}" --profile migration run --rm --no-deps events-migrate python -c '
import sys
from events_service.config import Settings
from events_service.migrate import migrate
from sqlalchemy import create_engine, text
try:
    url = Settings().database_url.get_secret_value()
    engine = create_engine(url, hide_parameters=True)
    with engine.connect() as connection:
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    engine.dispose()
    target = sys.argv[1]
    if (revision, target) not in {
        ("0005_recovery_parts", "0005_recovery_parts"),
        ("0006_interactive_edits", "0005_recovery_parts"),
        ("0006_interactive_edits", "0006_interactive_edits"),
    }:
        raise RuntimeError("unreviewed schema rollback")
    migrate(url, target, downgrade=True)
except Exception:
    raise SystemExit("Events schema rollback blocked; retain evidence and investigate") from None
' "$target_schema"; then
  # Preserve all evidence and attempt to restore the current runtime when a
  # guarded downgrade refuses. This remains a failed rollback observation.
  "${compose[@]}" up -d --wait --wait-timeout 90 wood-broker wood-notify || true
  exit 1
fi
/usr/bin/ansible-playbook --connection=local -i ansible/inventory/dev \
  ansible/playbooks/dev.yml --tags events_service \
  --extra-vars "events_service_image_ref=$previous_image"
bash scripts/health-check-events-service.sh
