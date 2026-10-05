# RAG Service dev deployment

RAG's API, migration runner, and Dagster code server use the same release image,
pinned by `rag_service_image_ref` in `environments/dev.yml`. The API and code
server run as UID/GID 1000, share persistent documents under
`/srv/infrastructure/state/rag-service/documents`, and join the infrastructure
Postgres and proxy networks. Dagster discovers `rag-service-code:4000` as
`rag-service`. Caddy serves `dev-rag-service.woodhost.cloud`; health checks
require the code server and a successful knowledge-base read through Caddy.
Production remains unselected; the role deliberately accepts only dev.

## Reviewed first-time setup

Before merging the enabling manifest, provision database `rag_service` in the
infrastructure dev Postgres cluster using the existing
`postgres/scripts/provision-database.sh` contract. Use distinct non-superuser
roles `rag_service_runtime` and `rag_service_migration`. The migration role owns
schema objects; runtime receives DML through the bootstrap's default grants.
Do not rerun the one-time bootstrap against existing roles or databases.

Store these separately in **Infrastructure Dev**, environment `dev`:

| Infisical folder | Required key | Value contract |
| --- | --- | --- |
| `/rag-service` | `RAG_DATABASE_URL` | `postgresql+psycopg2://rag_service_runtime:<password>@postgres:5432/rag_service` |
| `/rag-service-migrations` | `RAG_DATABASE_URL` | Same database, using `rag_service_migration` and its separate password |
| `/dagster` | `DAGSTER_POSTGRES_PASSWORD` | Existing platform Dagster storage credential |

The existing root-only deployer identity must read these folders. Ansible
resolves credentials into separate protected runtime files before pulling or
starting the service. Only the migration runner receives the migration URL;
only the code server receives the Dagster storage password. The code server
does not receive OpenProject or Google Drive credentials from the platform's
Dagster environment.

The role uses the existing protected GHCR Docker config established by the
Website Portfolio role earlier in the dev playbook. Verify its credential can
pull the private `rag-service` package before enabling the first deployment.
No registry token is mounted into application containers. Existing Dagster
configuration and local-artifact directories must be present; the Dagster role
runs before RAG in the same playbook.

## Apply, health, and promotion

The normal versioned dev deployment resolves secrets, pulls the exact image,
checks its OCI source revision, runs `alembic upgrade head` with the migration
identity, and waits for both the API and gRPC server to become healthy. Before
application migrations, the infrastructure role enables pgvector in the selected
RAG database using the platform database identity. This extension requires an
administrator; application runtime and migration roles remain non-superusers.
The operation checks installed extensions first and is a no-op on repeat deploys.
`rag_service_database_name` defaults to `rag_service`, and
`rag_service_postgres_container` selects the dev PostgreSQL container. Overrides
must match the database and cluster selected by the protected migration URL.
The extension and database survive application image rollback. Readiness
uses `/knowledge-bases?limit=1`, so an unmigrated database or invalid runtime
credential fails the deployment. `/version` reports the artifact's source
revision and semantic release tag. The database and documents survive container
replacement.

After the reviewed infrastructure onboarding has deployed, retry only the
failed RAG promotion job. Its successful release outputs identify the exact
validated digest. A matching image pin is a successful no-op; later application
releases update that pin through the existing scoped infrastructure PR flow.

## Rollback

The infrastructure release workflow can reapply the previous configuration
release. RAG's application migration deliberately rejects downgrade; rollback
never deletes or restores its database or document directory. A pre-onboarding
configuration does not remove the newly created RAG containers automatically.
If rolling back the initial onboarding, explicitly stop the RAG Compose project
after reviewing the target release, and retain its database, runtime files, and
documents. Subsequent image rollbacks require compatibility with the current
schema and should use a reviewed digest pin.
