#!/usr/bin/env bash
set -euo pipefail

# Project labels are the runtime contract written by the dev Ansible roles.
# These checks establish container liveness; HTTP probes below establish application readiness.
for project in infrastructure-dev-postgres infrastructure-dev-caddy infrastructure-dev-dagster infrastructure-dev-openwebui infrastructure-dev-keycloak infrastructure-dev-infisical infrastructure-dev-website-portfolio infrastructure-dev-rag-service; do
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

report_container=$(docker ps -q \
  --filter label=com.docker.compose.project=infrastructure-dev-dagster \
  --filter label=com.docker.compose.service=openproject-reports-code)
if [[ -z "$report_container" ]] || [[ $(docker inspect --format '{{.State.Health.Status}}' "$report_container") != healthy ]]; then
  echo 'OpenProject Reports Dagster code server is not healthy' >&2
  exit 1
fi
echo 'OK OpenProject Reports Dagster code server'

rag_code_container=$(docker ps -q \
  --filter label=com.docker.compose.project=infrastructure-dev-rag-service \
  --filter label=com.docker.compose.service=rag-service-code)
if [[ -z "$rag_code_container" ]] || [[ $(docker inspect --format '{{.State.Health.Status}}' "$rag_code_container") != healthy ]]; then
  echo 'RAG Service Dagster code server is not healthy' >&2
  exit 1
fi
echo 'OK RAG Service Dagster code server'

# This protected input exists only after the component has been deployed.
automerge_env=${HEALTH_CHECK_AUTOMERGE_ENV_FILE:-/srv/infrastructure/secrets/dev/automerge-repair-compose.env}
if [[ -f "$automerge_env" ]]; then
  automerge_image=$(sed -n 's/^AUTOMERGE_REPAIR_IMAGE_REF=//p' "$automerge_env")
  test -n "$automerge_image"
  automerge_container=$(docker ps -q \
    --filter label=com.docker.compose.project=infrastructure-dev-automerge-repair \
    --filter label=com.docker.compose.service=automerge-repair-code)
  test -n "$automerge_container"
  test "$(docker inspect --format '{{.Config.Image}}' "$automerge_container")" = "$automerge_image"
  test "$(docker inspect --format '{{.State.Health.Status}}' "$automerge_container")" = healthy
  docker exec "$automerge_container" dagster api grpc-health-check -p 4000
  echo 'OK Automerge Repair image and gRPC readiness'
fi

caddy_env_file=${HEALTH_CHECK_CADDY_ENV_FILE:-/srv/infrastructure/secrets/dev/caddy.env}
caddy_http_bind=$(sed -n 's/^CADDY_HTTP_BIND=//p' "$caddy_env_file")
test -n "$caddy_http_bind"
caddy_endpoint="http://${caddy_http_bind}"

route_attempts=${HEALTH_CHECK_ROUTE_ATTEMPTS:-16}
route_retry_interval=${HEALTH_CHECK_RETRY_INTERVAL:-4}

wait_for_route() {
  local host=$1 path=$2 max_attempts=${3:-$route_attempts} attempt response curl_status last_failure
  echo "Checking infrastructure Caddy route ${host}${path}"
  for ((attempt = 1; attempt <= max_attempts; attempt++)); do
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
    if ((attempt < max_attempts)); then
      sleep "$route_retry_interval"
    fi
  done
  echo "FAILED infrastructure Caddy route ${host}${path} after ${max_attempts} attempts: ${last_failure}" >&2
  if [[ $host == dev-keycloak.woodhost.cloud ]]; then
    for id in $(docker ps -aq --filter label=com.docker.compose.project=infrastructure-dev-keycloak); do
      docker inspect --format 'Keycloak container {{.Id}}: status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} restarts={{.RestartCount}}' "$id" >&2
      docker logs --tail 100 "$id" >&2
    done
  fi
  return 1
}

wait_for_route "${caddy_http_bind}" /healthz
wait_for_route dev-dagster.woodhost.cloud /server_info
wait_for_route dev-openwebui.woodhost.cloud /health
wait_for_route dev-keycloak.woodhost.cloud /realms/master/.well-known/openid-configuration "${HEALTH_CHECK_KEYCLOAK_ROUTE_ATTEMPTS:-60}"
for id in $(docker ps -q --filter label=com.docker.compose.project=infrastructure-dev-keycloak); do
  for ((attempt = 1; attempt <= 15; attempt++)); do
    if docker inspect "$id" | grep -q '"Status": "healthy"'; then
      echo "OK Keycloak container $id health"
      break
    fi
    if ((attempt == 15)); then
      echo "FAILED Keycloak container $id health" >&2
      docker logs --tail 100 "$id" >&2
      exit 1
    fi
    sleep "$route_retry_interval"
  done
done
wait_for_route dev-infisical.woodhost.cloud /api/status
wait_for_route dev-website-portfolio.woodhost.cloud /health
wait_for_route dev-website-portfolio.woodhost.cloud /

# The protected Compose input exists only after an Events deployment. Do not
# require the component on environments where it has never been selected.
events_env=${HEALTH_CHECK_EVENTS_ENV_FILE:-/srv/infrastructure/secrets/dev/events-service-compose.env}
if [[ -f "$events_env" ]]; then
  events_image=$(sed -n 's/^EVENTS_SERVICE_IMAGE_REF=//p' "$events_env")
  test -n "$events_image"
  for service in wood-broker wood-notify; do
    ids=$(docker ps -q --filter label=com.docker.compose.project=infrastructure-dev-events-service \
      --filter "label=com.docker.compose.service=$service")
    test -n "$ids"
    while IFS= read -r id; do
      test "$(docker inspect --format '{{.Config.Image}}' "$id")" = "$events_image"
      docker exec "$id" python -c "import json, urllib.request; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/live', timeout=3))['status'] == 'ok'; assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/health/ready', timeout=3))['status'] == 'ready'"
    done <<< "$ids"
    echo "OK Events Service $service image and readiness"
  done
fi
wait_for_route dev-rag-service.woodhost.cloud /health
wait_for_route dev-rag-service.woodhost.cloud /knowledge-bases?limit=1

# The API and code server must use the selected immutable artifact. Core
# readiness is checked inside the API so this probe does not widen ingress.
rag_env=${HEALTH_CHECK_RAG_ENV_FILE:-/srv/infrastructure/secrets/dev/rag-service-compose.env}
rag_image=$(sed -n 's/^RAG_SERVICE_IMAGE_REF=//p' "$rag_env")
rag_revision=$(sed -n 's/^RAG_SERVICE_SOURCE_REVISION=//p' "$rag_env")
rag_release=$(sed -n 's/^RAG_SERVICE_RELEASE_TAG=//p' "$rag_env")
test -n "$rag_image" && test -n "$rag_revision" && test -n "$rag_release"
embedding_image=$(sed -n 's/^RAG_EMBEDDING_IMAGE_REF=//p' "$rag_env")
embedding_revision=$(sed -n 's/^RAG_EMBEDDING_SOURCE_REVISION=//p' "$rag_env")
embedding_release=$(sed -n 's/^RAG_EMBEDDING_RELEASE_TAG=//p' "$rag_env")
test -n "$embedding_image" && test -n "$embedding_revision" && test -n "$embedding_release"
embedding_container=$(docker ps -q --filter label=com.docker.compose.project=infrastructure-dev-rag-service \
  --filter label=com.docker.compose.service=embedding-service)
test -n "$embedding_container"
test "$(docker inspect --format '{{.State.Health.Status}}' "$embedding_container")" = healthy
test "$(docker inspect --format '{{.Config.Image}}' "$embedding_container")" = "$embedding_image"
test "$(docker inspect --format '{{.Image}}' "$embedding_container")" = "$(docker image inspect --format '{{.Id}}' "$embedding_image")"
test "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$embedding_image")" = "$embedding_revision"
docker exec "$embedding_container" python -m rag_embedding.verification \
  --url http://127.0.0.1:8080 --source-revision "$embedding_revision" --release-revision "$embedding_release"
echo 'OK embedding immutable image, health, readiness, and Qwen vectors'
for service in rag-service rag-service-code; do
  ids=$(docker ps -q --filter label=com.docker.compose.project=infrastructure-dev-rag-service \
    --filter "label=com.docker.compose.service=$service")
  test -n "$ids"
  while IFS= read -r id; do
    test "$(docker inspect --format '{{.Config.Image}}' "$id")" = "$rag_image"
    test "$(docker inspect --format '{{.Image}}' "$id")" = "$(docker image inspect --format '{{.Id}}' "$rag_image")"
    test "$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$rag_image")" = "$rag_revision"
    docker exec "$id" python -c 'import json,os,urllib.request; endpoint=os.environ["RAG_EMBEDDING_ENDPOINT"]; assert endpoint == "http://embedding-service:8080/v1"; assert os.environ["RAG_EMBEDDING_MODEL"] == "Qwen/Qwen3-Embedding-0.6B"; base=endpoint.removesuffix("/v1"); assert json.load(urllib.request.urlopen(base+"/health", timeout=3))["status"] == "ok"; ready=json.load(urllib.request.urlopen(base+"/ready", timeout=3)); assert ready["status"] == "ready" and ready["dimensions"] == 1024'
    if [[ "$service" == rag-service ]]; then
      docker exec "$id" python -c 'import json,sys,urllib.request; ready=json.load(urllib.request.urlopen("http://127.0.0.1:8000/ready", timeout=8)); assert ready["status"] == "ready"; version=json.load(urllib.request.urlopen("http://127.0.0.1:8000/version", timeout=3)); assert version["source_revision"] == sys.argv[1]; assert version["release_revision"] == sys.argv[2]; assert version["version"] == sys.argv[2].removeprefix("v")' "$rag_revision" "$rag_release"
    fi
  done <<< "$ids"
done
echo 'OK RAG immutable image, revision, and core readiness'
