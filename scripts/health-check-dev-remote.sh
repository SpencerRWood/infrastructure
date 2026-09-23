#!/usr/bin/env bash
set -euo pipefail

# Project labels are the runtime contract written by the dev Ansible roles.
# These checks establish container liveness; HTTP probes below establish application readiness.
for project in infrastructure-dev-postgres infrastructure-dev-caddy infrastructure-dev-dagster infrastructure-dev-openwebui infrastructure-dev-keycloak infrastructure-dev-infisical infrastructure-dev-website-portfolio; do
  ids=$(docker ps -q --filter "label=com.docker.compose.project=$project")
  test -n "$ids"
  while IFS= read -r id; do
    inspection=$(docker inspect "$id")
    grep -q '"Running": true' <<<"$inspection"
    if grep -q '"Status": "unhealthy"' <<<"$inspection"; then
      echo "container $id is unhealthy" >&2
      exit 1
    fi
  done <<< "$ids"
  echo "OK $project"
done

caddy_env_file=${HEALTH_CHECK_CADDY_ENV_FILE:-/srv/infrastructure/secrets/dev/caddy.env}
caddy_http_bind=$(sed -n 's/^CADDY_HTTP_BIND=//p' "$caddy_env_file")
test -n "$caddy_http_bind"
caddy_endpoint="http://${caddy_http_bind}"

route_attempts=${HEALTH_CHECK_ROUTE_ATTEMPTS:-16}
route_retry_interval=${HEALTH_CHECK_RETRY_INTERVAL:-4}

wait_for_route() {
  local host=$1 path=$2 attempt response curl_status last_failure
  echo "Checking infrastructure Caddy route ${host}${path}"
  for ((attempt = 1; attempt <= route_attempts; attempt++)); do
    if response=$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
      --connect-timeout 2 --max-time 3 -H "Host: $host" "${caddy_endpoint}${path}" 2>&1); then
      if [[ "$response" == 200 ]]; then
        echo "OK infrastructure Caddy route ${host}${path}"
        return 0
      fi
      last_failure="HTTP $response"
    else
      curl_status=$?
      last_failure="curl exit ${curl_status}: ${response//$'\n'/ }"
    fi
    if ((attempt < route_attempts)); then
      sleep "$route_retry_interval"
    fi
  done
  echo "FAILED infrastructure Caddy route ${host}${path} after ${route_attempts} attempts: ${last_failure}" >&2
  return 1
}

wait_for_route "${caddy_http_bind}" /healthz
wait_for_route dev-dagster.woodhost.cloud /server_info
wait_for_route dev-openwebui.woodhost.cloud /health
wait_for_route dev-keycloak.woodhost.cloud /realms/master/.well-known/openid-configuration
wait_for_route dev-infisical.woodhost.cloud /api/status
wait_for_route dev-website-portfolio.woodhost.cloud /health
wait_for_route dev-website-portfolio.woodhost.cloud /
