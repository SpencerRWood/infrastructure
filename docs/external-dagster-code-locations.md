# External Dagster code locations

Declare externally published application code servers in `environments/dev.yml`.
The service image must include an immutable `@sha256:` digest and a Dagster gRPC
server that reads `DAGSTER_GRPC_PORT` (or listens on the declared port). The
image must contain the `dagster api grpc-health-check` command. Distinct
containers can use the same internal gRPC port.

For an application with no infrastructure-managed application configuration:

```yaml
dagster_code_locations:
  - name: data_cleanup
    service_name: data-cleanup-code
    image: ghcr.io/example/data-cleanup:v1.0.0@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    port: 4000
```

For an application that needs the existing outbound/proxy network:

```yaml
dagster_code_locations:
  - name: api_ingestion
    service_name: api-ingestion-code
    image: ghcr.io/example/api-ingestion:v1.0.0@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    port: 4000
    capabilities:
      outbound_network: true
```

For application secrets, reference an entry in the existing Infisical runtime
configuration layer. The example uses `/dagster` because that is where the
current OpenProject Reports keys live; a new project may use its own path.

```yaml
dagster_code_locations:
  - name: openproject_reports
    service_name: openproject-reports-code
    image: ghcr.io/example/openproject-reports:v1.0.0@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    port: 4000
    runtime_env: openproject_reports
    capabilities:
      outbound_network: true

dagster_runtime_environments:
  openproject_reports:
    environment: dev
    path: /dagster
    output: /srv/infrastructure/secrets/runtime/openproject-reports.env
    required_keys:
      - OPENPROJECT_BASE_URL
      - OPENPROJECT_API_TOKEN
      - GOOGLE_DRIVE_CREDENTIALS_JSON
      - GOOGLE_DRIVE_FOLDER_ID
```

The Dagster role renders the Compose service and workspace entry from this
declaration and publishes the service names for the remote deployment health
gate. Every external location receives restart policy `unless-stopped`, UID/GID
`1000:1000`, the shared static and Dagster PostgreSQL runtime environment,
read-only `DAGSTER_HOME` config mount, writable shared local artifact/compute-log
mount, PostgreSQL network, gRPC port exposure, and a health check with a 10-second
timeout, 10 retries, and 30-second start period. Outbound networking and the
application runtime environment are optional. The application owns its keys,
business configuration, image contents, and release process. Infrastructure
owns the shared Dagster participation contract.

The infrastructure-built `dagster-user-code` and host-integrated
`dagster-codex-usage` servers remain separate service classes. The retained
on-host pre-Infisical Compose snapshot remains the rollback source; new
external locations use the rendered dev definition.

The normal `dev.yml` release installs the current resolver, reconciler, and
runtime-service metadata from this same manifest. It starts the desired
Compose services, then retires obsolete external code-server containers before
publishing the new health target list. Reboot and secret-rotation reconciliation
use the installed `external_code_locations` metadata and apply the same
retirement. The root-owned deployed ownership manifest records the complete
external declarations after a successful release. Retirement compares that
manifest with the desired declaration and removes only services in the
difference. Docker inspection locates containers for those proven services;
image, port, environment, and labels do not establish ownership. Unknown and
infrastructure-owned services are ignored. The desired Compose service set
also protects a service whose name has moved from external to infrastructure
ownership. The first normal release establishes
this ownership record from the canonical declaration before rewriting Compose.

Before rewriting the protected Dagster Compose env file, the normal release
retains `compose.pre-infisical.env` beside the existing rollback Compose
snapshot and records which external declarations belong to that snapshot.
The latter is derived from the snapshot service set and the prior deployed
ownership record; it is never manually maintained or overwritten on later
releases. Rollback checks that the retained env supplies every variable used
by the target snapshot and validates Compose before disabling the boot unit or
replacing the active definition. It removes obsolete generated workspace
entries using the current and retained ownership manifests, recreates the
snapshot services, then retires external code servers absent from the target.
This works even when a container is already absent. An unfamiliar obsolete
workspace format blocks
rollback before service changes. The retained env is
root-owned mode `0600`; it is never committed. On the dev host on 2026-09-28,
the retained snapshot required `DAGSTER_PROJECT_NAME`, `DAGSTER_IMAGE`,
`DAGSTER_VERSION`, `DAGSTER_LIB_VERSION`, `PYTHON_VERSION`,
`DAGSTER_RUNTIME_ENV_FILE`, `DAGSTER_CONFIG_PATH`, `DAGSTER_LOCAL_PATH`,
`DAGSTER_POSTGRES_NETWORK`, and `DAGSTER_PROXY_NETWORK`. All ten were in the
protected Compose env file. The snapshot contained only user-code, daemon,
and webserver services. The retained env copy did not yet exist, so the first
normal release must capture the current protected env before
rewriting it; if the snapshot or its required env values have changed, rollback
validation fails before any service changes.
