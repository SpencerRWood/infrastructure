# PostgreSQL infrastructure ownership migration

Infrastructure is the canonical owner of the PostgreSQL Compose payload. Terraform
may provision hosts, storage, DNS, and cloud resources, but it does not manage the
PostgreSQL container. Ansible creates `/srv/infrastructure/compose/postgres`, writes
`/srv/infrastructure/secrets/postgres.env` as `root:root` mode `0600`, validates the
existing cluster, and deploys the Compose payload. Docker Compose owns lifecycle.

## Audited development runtime (2026-09-21)

The live container is the source of truth for this cutover. It is `wood-data-postgres`
from Compose project `wood-data-platform`, image
`pgvector/pgvector:0.8.2-pg16-bookworm` (image ID
`sha256:be2dedd215733ac25f6d3d2413f5f579f35c82bd659e09ef47fc0f2a4bada0eb`).
It is PostgreSQL 16.14 with `PGDATA=/var/lib/postgresql/data`, restart policy
`unless-stopped`, no explicit resource limits, and a healthy `pg_isready` check every
10 seconds (5-second timeout, 5 retries).

It bind-mounts the initialized cluster at `/srv/data-platform/postgres/data`
(`dnsmasq:root`, `0700`), the read-only legacy init directory at
`/srv/docker/wood-data-platform/platform/postgres/init`, and the existing password
file at `/srv/docker/secrets/files/wood-data-platform/postgres/password`. The data
path contains `PG_VERSION=16`; it is deliberately neither copied nor initialized.
The current deployment publishes `192.168.1.21:25432 -> 5432`, exposes 5432, and is
attached to external `wood-data-platform-db` (internal) and
`wood-data-platform-lan` networks. Its service and container aliases are `postgres`
and `wood-data-postgres`.

The bootstrap identity is `wood` with the default database `wood_data`; the password
is supplied only through `POSTGRES_PASSWORD_FILE`. No password value is stored in
this repository or output by Ansible.

Observed non-template databases: `dagster`, `grafana`, `infisical`, `keycloak`,
`mealie`, `openproject`, `openwebui`, `portfolio_website`,
`synthetic_website_data`, `vaultwarden`, `vikunja`, `wood_data`, and `postgres`.
Observed login roles are `cloudbeaver_readonly`, `dagster`, `dbt_editor`, `grafana`,
`infisical`, `keycloak`, `mealie`, `openproject`, `openwebui`,
`portfolio_migrator`, `portfolio_runtime`, `synthetic_website_editor`,
`vaultwarden`, `vikunja`, and superuser `wood`. All observed application roles are
non-superuser, non-CREATEDB, non-CREATEROLE login roles. Built-in monitoring-role
memberships are retained. Extensions are `plpgsql` everywhere, plus `pg_trgm` in
`mealie` and `btree_gist`, `pg_trgm`, and `unaccent` in `openproject`.

The database network currently has Dagster, Keycloak, Mealie, OpenWebUI, OpenProject,
Vaultwarden, Vikunja, Infisical, CloudBeaver, and related workers connected. The
canonical definition preserves their Docker DNS contract and host port. No backup job
was found in the legacy data-platform tree; backups remain an operational follow-up,
not part of this ownership change. Website-portfolio and RudderStack are explicitly
out of scope and are not changed by this migration.

## Environment and deployment workflow

`~/.config/wood/dev.env` and `~/.config/wood/prod.env` remain untracked and are
loaded by direnv from `.envrc`. Add the names in the matching
`environments/*/postgres.env.example` file. The `postgres` Ansible role reads only
the required variables and writes them to the protected server-side file. Tasks that
read or write secret-adjacent values use `no_log`.

Validate and deploy the development payload from this repository after direnv loads
the development environment:

```sh
ansible-inventory -i ansible/inventory/dev.yml --graph
ansible-playbook -i ansible/inventory/dev.yml ansible/playbooks/postgres.yml --syntax-check
ansible-playbook -i ansible/inventory/dev.yml ansible/playbooks/postgres.yml --tags postgres --check --diff
ansible-playbook -i ansible/inventory/dev.yml ansible/playbooks/postgres.yml --tags postgres
```

## Attended cutover and rollback

Immediately before cutover record the running container ID, image ID, mounts,
networks, status, and this rollback command:

```sh
cd /srv/docker/wood-data-platform
docker compose --env-file .env up -d --no-deps --force-recreate postgres
```

After the canonical payload has rendered successfully, stop and remove only the old
container (never the bind-mounted state), then start the new owner:

```sh
docker stop wood-data-postgres
docker rm wood-data-postgres
docker compose --env-file /srv/infrastructure/secrets/postgres.env \
  -f /srv/infrastructure/compose/postgres/compose.yml up -d postgres
```

Do not run `down -v`. Confirm the health check, PostgreSQL version, databases, roles,
extensions, database sizes, schemas/tables, application connections, dbt, and
migration tooling using read-only checks. Restart the container and, when operationally
reasonable, the host; verify the same cluster and consumer reconnection each time.
Keep `/srv/docker/wood-data-platform` and its secret material as clearly legacy
rollback artifacts until deliberate retirement.
