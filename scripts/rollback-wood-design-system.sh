#!/usr/bin/env bash
set -euo pipefail
test "${WDS_ROLLBACK_APPROVED:-false}" = true || { echo 'Explicit WDS rollback authorization required.' >&2; exit 1; }
project_dir=/srv/infrastructure/compose/wood-design-system
env_file=/srv/infrastructure/secrets/dev/wood-design-system-compose.env
docker compose --env-file "$env_file" -f "$project_dir/compose.yml" down
rm -f /srv/infrastructure/compose/caddy/routes/wood-design-system.caddy
rm -f /srv/docker/proxy/config/sites/wood-design-system.caddy
for proxy in infrastructure-dev-caddy-caddy-1 caddy; do
  docker exec "$proxy" caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
  docker exec "$proxy" caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile
done
echo 'WDS stopped and its routes removed. Restore the reviewed disabled manifest before later deployment.'
