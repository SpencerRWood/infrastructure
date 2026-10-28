#!/usr/bin/env bash
set -euo pipefail

compose_env=${HEALTH_CHECK_EVENTS_ENV_FILE:-/srv/infrastructure/secrets/dev/events-service-compose.env}
expected_image=$(sed -n 's/^EVENTS_SERVICE_IMAGE_REF=//p' "$compose_env")
project=$(sed -n 's/^EVENTS_SERVICE_PROJECT_NAME=//p' "$compose_env")
[[ "$expected_image" =~ ^ghcr\.io/spencerrwood/events-service:v[0-9]+\.[0-9]+\.[0-9]+@sha256:[0-9a-f]{64}$ ]]
test -n "$project"
for service in wood-broker wood-notify; do
  container=$(docker ps -q --filter "label=com.docker.compose.project=$project" \
    --filter "label=com.docker.compose.service=$service")
  test -n "$container"
  test "$(docker inspect --format '{{.Config.Image}}' "$container")" = "$expected_image"
  test "$(docker inspect --format '{{.State.Health.Status}}' "$container")" = healthy
done
for port in 18000 18001; do
  for path in /health/live /health/ready; do
    curl --fail --silent --show-error --connect-timeout 3 --max-time 10 \
      "http://127.0.0.1:$port$path" >/dev/null
  done
done
echo 'Events immutable image, broker/notify health and schema readiness verified.'
