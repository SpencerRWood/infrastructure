# Architecture and ownership

| Owner | Responsibility |
| --- | --- |
| Terraform | Cloud hosts, volumes, DNS, firewall/network primitives, future DigitalOcean resources |
| Ansible | Host configuration, canonical directories, protected environment files, Compose payloads, validation |
| Docker Compose | Portable platform-service lifecycle |
| Environment manifests | Explicit per-environment service selection |
| Application repositories | Source, migrations, tests, and releases |

## Deployment control plane

The always-on Beelink hosts two independent GitHub Actions runners. This repository owns
`github-runner-infrastructure` (labels include `beelink` and `infrastructure`); the
homelab repository independently owns `github-runner-homelab`. Each has a distinct
non-root account, registration, work directory, systemd unit, local secret scope, and
deployment concurrency group. The MacBook is not part of routine CI/CD execution.

After a PR (including a Renovate PR) is merged, semantic-release publishes an immutable
tag. The infrastructure runner checks out that tag through the centralized reusable
workflow contract, validates it, invokes the canonical local Ansible path for dev, and
performs health checks. Failures reapply the previous
successful configuration release once; database state is never blindly rolled back.
Production is deliberately excluded from this automatic path. Co-locating runner and
managed node is an intentional availability tradeoff, not a shared-runner model.

Components are a shared catalog, not a stack promotion mechanism. `dev` and
`prod` separately declare services in `environments/dev.yml` and
`environments/prod.yml`; production is opt-in. The canonical Postgres and Caddy
components are present in the catalog, but only dev enables them.

The dev Postgres state path is `/srv/infrastructure/state/postgres/data`; it uses
the internal-only `infrastructure-dev-postgres` network and restart policy
`unless-stopped`. It has no published host port. Future production Postgres will
be a fresh independent cluster—dev database state is never promoted to prod.

## Ingress ownership

On Beelink, homelab Caddy remains an independent edge proxy and owns LAN ports
`80` and `443` plus the homelab `proxy` Docker network. Infrastructure dev
Caddy is an independent runtime, bound only to `192.168.1.21:8080` and
`192.168.1.21:8443`, with UFW access limited to `192.168.1.0/24`, persistent
state under `/srv/infrastructure/state/caddy/`, and its own
`infrastructure-dev-proxy` network. `proxy != infrastructure-dev-proxy`; no
compatibility bridge exists. It currently exposes only `/healthz`. The initial
Caddyfile is HTTP-only, so `8443` is reserved for later reviewed TLS
configuration.

Future infrastructure services explicitly join the infrastructure proxy network
only as they migrate. Each route lives in `compose/caddy/routes/` as one
fragment per service, rather than being copied from homelab or accumulated in a
shared Caddyfile. The route moves only with its service: canonical Compose
definition, database dependency, secrets, proxy-network membership, route,
runtime validation, legacy shutdown, and rollback procedure are one migration
unit. Development URLs use `http://dev-<service>.woodhost.cloud:8080`; later TLS
URLs will use `https://dev-<service>.woodhost.cloud:8443`. No DNS or public-ingress change is
part of this model. On a dedicated production host, infrastructure-prod Caddy
may own `:80/:443` directly. Component availability never enables production
deployment by itself.

## Dagster ownership

Dagster is a dev-only infrastructure component. `compose/dagster/` owns its
webserver, daemon, gRPC user-code servers, workspace, and storage configuration.
The webserver alone joins `infrastructure-dev-proxy`; all services join the
isolated infrastructure Postgres network. Its Caddy route is an infrastructure
fragment and is independent of homelab Caddy. The external
`synthetic_website_poc` gRPC location remains configuration-only and is not
migrated in this release. The Codex usage location runs in a Beelink container
with local profile mounts, an outbound proxy network route, and persistent slot
claims. The existing legacy database/runtime and a protected
custom-format backup are retained for rollback; do not run both daemons. The
attended cutover restored the final backup to infrastructure-dev Postgres,
stopped the legacy project, and verified 9 historical runs and 179 event logs
through the infrastructure Caddy route.
