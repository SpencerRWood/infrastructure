#!/usr/bin/env bash
set -euo pipefail

# Project labels are the runtime contract written by the dev Ansible roles.
uv run ansible -i ansible/inventory/dev infrastructure_hosts -b -m shell -a '
set -euo pipefail
for project in infrastructure-dev-postgres infrastructure-dev-caddy infrastructure-dev-dagster infrastructure-dev-openwebui infrastructure-dev-keycloak infrastructure-dev-infisical; do
  ids=$(docker ps -q --filter "label=com.docker.compose.project=$project")
  test -n "$ids"
  while IFS= read -r id; do
    health=$(docker inspect --format "{{if .Config.Healthcheck}}{{.State.Health.Status}}{{else}}none{{end}}" "$id")
    test "$health" != unhealthy
  done <<< "$ids"
  echo "OK $project"
done
curl --fail --silent --show-error http://127.0.0.1:8080/healthz >/dev/null
echo "OK infrastructure Caddy /healthz"
for host in dev-dagster.woodhost.cloud dev-openwebui.woodhost.cloud dev-keycloak.woodhost.cloud dev-infisical.woodhost.cloud; do
  curl --fail --silent --show-error -H "Host: $host" http://127.0.0.1:8080/ >/dev/null
  echo "OK infrastructure Caddy route $host"
done
'
