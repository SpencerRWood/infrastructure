#!/usr/bin/env bash
set -euo pipefail

# Project labels are the runtime contract written by the dev Ansible roles.
for project in infrastructure-dev-postgres infrastructure-dev-caddy infrastructure-dev-dagster infrastructure-dev-openwebui infrastructure-dev-keycloak infrastructure-dev-infisical; do
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

caddy_env_file=/srv/infrastructure/secrets/dev/caddy.env
caddy_http_bind=$(sed -n 's/^CADDY_HTTP_BIND=//p' "$caddy_env_file")
test -n "$caddy_http_bind"
caddy_endpoint="http://${caddy_http_bind}"

curl --fail --silent --show-error "$caddy_endpoint/healthz" >/dev/null
echo "OK infrastructure Caddy /healthz"
for host in dev-dagster.woodhost.cloud dev-openwebui.woodhost.cloud dev-keycloak.woodhost.cloud dev-infisical.woodhost.cloud; do
  curl --fail --silent --show-error -H "Host: $host" "$caddy_endpoint/" >/dev/null
  echo "OK infrastructure Caddy route $host"
done
