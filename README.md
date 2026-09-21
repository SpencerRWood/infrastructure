# infrastructure

Infrastructure topology and portable runtime components for Wood environments.
Application repositories keep source code, migrations, and releases.

## Ownership

Terraform provisions cloud infrastructure: hosts, volumes, DNS, firewall/network
primitives, and future DigitalOcean resources. Ansible configures hosts, creates
canonical directories, deploys protected environment files and Compose payloads,
and validates configuration. Docker Compose owns portable service lifecycle.

Components are a shared catalog. Environment manifests explicitly select which
components run. Repository component availability != production deployment.

## Layout

```text
ansible/              Inventory, environment playbooks, and implemented roles
compose/              Canonical reusable Compose components
environments/*.yml    Explicit dev/prod service-selection manifests
environments/*.env.example  Names-only local secret contracts
docs/                 Ownership, environment, and migration guidance
terraform/            Future cloud-infrastructure ownership
```

## Environments and secrets

`dev` enables the standalone PostgreSQL, Caddy, Dagster, Open WebUI, Keycloak,
and Infisical components; `prod` explicitly disables every component and contains
no host. Production services are opt-in through reviewed changes.
direnv loads one untracked local file:
`~/.config/wood/infrastructure/dev.env` by default, or `prod.env` when
`INFRASTRUCTURE_ENV=prod`. Ansible writes server-side values under
`/srv/infrastructure/secrets/<environment>/` as `root:root` mode `0600`.

RudderStack is out of scope. Dagster, Open WebUI, Keycloak, Infisical, Synthetic
Website Analytics, and the portfolio database run on infrastructure-dev
PostgreSQL. The website runtime itself remains independently owned. The shared
wood-data-platform PostgreSQL remains online only for administrative databases
and rollback copies; it has no active application workloads.

## Development ingress

The reusable infrastructure Caddy runs on the Beelink LAN address at
`192.168.1.21:8080` and `192.168.1.21:8443`, restricted by the host firewall to
the trusted `192.168.1.0/24` LAN. It serves only HTTP `GET /healthz`; the
reserved HTTPS binding has no route until a future reviewed TLS configuration.
Dagster, Open WebUI, Keycloak, and Infisical are behind it. Their development
URLs are `https://dev-dagster.woodhost.cloud`,
`https://dev-openwebui.woodhost.cloud`,
`https://dev-keycloak.woodhost.cloud`, and
`https://dev-infisical.woodhost.cloud`. Edge Caddy owns those normal HTTPS
URLs and proxies their requests to the isolated infrastructure Caddy listener.
Its state lives below `/srv/infrastructure/state/caddy/`, and it owns the
isolated `infrastructure-dev-proxy` Docker network.

Homelab Caddy remains the independent Beelink edge proxy and exclusively owns
its LAN `:80/:443` bindings and `proxy` network. Infrastructure Caddy owns only
its alternate ports and `infrastructure-dev-proxy`; the networks are never
shared and no compatibility bridge exists. Future services join that network and
receive one Caddy route fragment only when they migrate. Development URLs use
`http://dev-<service>.woodhost.cloud:8080` (and, after TLS is configured,
`https://dev-<service>.woodhost.cloud:8443`); DNS does not hide these alternate ports.

## Dagster dev migration

Dagster's canonical dev runtime is `compose/dagster/` (webserver, daemon, and
the existing gRPC user-code server). Its webserver alone joins
`infrastructure-dev-proxy` and is reached at
`http://dev-dagster.woodhost.cloud:8080`; the other services use only
`infrastructure-dev-postgres`. The legacy runtime and source database remain
available for rollback until the attended database restore and cutover are
completed.

## Remaining dev-service migration

Open WebUI, Keycloak, and Infisical now run as infrastructure-owned dev
components on isolated PostgreSQL and proxy networks. Their legacy `chat` and
`private` containers are stopped but retained with their source databases,
Compose trees, named volumes, and protected logical backups for rollback.
Keycloak's development hostname is `dev-keycloak.woodhost.cloud`. Open WebUI's
first infrastructure deployment preserves an existing legacy signing key when
available; otherwise it creates a protected replacement key.

## Validation

```sh
bash scripts/validate.sh
ANSIBLE_CONFIG=ansible/ansible.cfg ansible-inventory -i ansible/inventory/dev --graph
ANSIBLE_CONFIG=ansible/ansible.cfg ansible-playbook -i ansible/inventory/dev ansible/playbooks/dev.yml --syntax-check
```

See [environment ownership](docs/environments.md) and the
[next-release migration inventory](docs/postgres-migration-inventory.md).

## Repository workflow

Run `uv sync --group dev` once, then `uv run pre-commit install`. Pre-commit blocks
local commits directly to `main` and validates YAML, secrets/private keys,
Ansible inventories and syntax, Ansible lint, and Compose configuration. Work on
a branch and merge through a reviewed pull request; local hooks complement, but
do not replace, GitHub branch protection.

The pull-request workflow runs the same pre-commit suite in GitHub Actions. The
shared release workflow runs only after changes reach `main`. It creates semantic
releases from conventional commits. A published release invokes the shared
deployment workflow on the trusted self-hosted control node, checks out the exact
tag, validates it, applies `ansible/playbooks/dev.yml`, and runs
`scripts/health-check-dev.sh`. Deployments are serialized by
`deploy-infrastructure-dev`; a newer run never interrupts an active apply.

On deployment or health failure the workflow restores the prior successful
`infrastructure-dev` Environment release once and validates it. Rollback restores
prior repository-defined runtime configuration only; it does not perform a blind
database rollback. Use **Actions → Deploy released infrastructure development
configuration → Run workflow** for a controlled redeploy of an existing release
(or leave the input empty for the latest). The runner loads the ignored
`/Users/spencerwood/.config/wood/infrastructure/dev.env`; workflow YAML has no secrets.

Automatic release deployment is dev-only. `prod.yml` is never called automatically
and production remains an explicit/manual operation.

Renovate follows this same validated release path. Docker patch and vulnerability
updates may auto-merge after GitHub's required checks pass; minor and major updates
remain manual. PostgreSQL compatibility-major changes remain manual. Routine
Renovate commits are `fix(deps)`, producing semantic-release patch releases.
