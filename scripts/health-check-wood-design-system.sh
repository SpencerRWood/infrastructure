#!/usr/bin/env bash
set -euo pipefail

env_file=/srv/infrastructure/secrets/dev/wood-design-system-compose.env
image=$(sed -n 's/^WDS_IMAGE_REF=//p' "$env_file")
[[ "$image" =~ ^ghcr.io/spencerrwood/wood-design-system:v[0-9]+\.[0-9]+\.[0-9]+@sha256:[a-f0-9]{64}$ ]]
container=$(docker ps -q --filter label=com.docker.compose.project=infrastructure-dev-wood-design-system \
  --filter label=com.docker.compose.service=wood-design-system)
test -n "$container"
test "$(docker inspect --format '{{.Config.Image}}' "$container")" = "$image"
test "$(docker inspect --format '{{.State.Health.Status}}' "$container")" = healthy
caddy_bind=$(sed -n 's/^CADDY_HTTP_BIND=//p' /srv/infrastructure/secrets/dev/caddy.env)
test -n "$caddy_bind"
for path in /health / /foundations /components /patterns /resources \
  /examples/website /examples/analytics /examples/developer /examples/document /component-manifest.json; do
  test "$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --connect-timeout 3 --max-time 10 -H 'Host: dev-design.woodhost.cloud' "http://$caddy_bind$path")" = 200
done
echo "WDS immutable image, health and application/documentation routes verified."
