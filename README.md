# infrastructure

Infrastructure topology and portable runtime components for Wood environments.
Application repositories keep source code, migrations, and releases.

Automerge Repair's application source lives in its standalone repository.
The dev-only `automerge_repair` role deploys its digest-qualified GHCR release,
mounts the reviewed `compose/automerge-repair/policy.toml`, and resolves only
`DAGSTER_POSTGRES_PASSWORD` from the Infisical dev path `/automerge-repair`.
Its private gRPC location is registered in Dagster only when selected in dev.
Dev selects the runtime-validated `v0.1.0` image by immutable digest; its scoped
secret contains the existing Dagster storage credential.
The role waits for gRPC health; the normal dev health script also checks the
configured image and readiness after deployment. Application health is verified
by running `foundation_health_job` through the shared Dagster instance. After
the code location is ready, the role reloads the webserver and daemon when its
image, policy, or workspace changes.
The role registers its scoped path in the existing runtime refresh metadata.
No production component is enabled.

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
Infisical, and Website Portfolio components; `prod` explicitly disables every
component and contains no host. Production services are opt-in through reviewed
changes.
direnv loads one untracked local file:
`~/.config/wood/infrastructure/dev.env` by default, or `prod.env` when
`INFRASTRUCTURE_ENV=prod`. Ansible writes server-side values under
`/srv/infrastructure/secrets/<environment>/` as `root:root` mode `0600`.
For runner bootstrap, the Beelink administrator keeps the same untracked dev
input at `/home/spencerwood/.config/wood/infrastructure/dev.env`; Ansible copies
it once to the dedicated runner account as mode `0600`.

The RudderStack service is out of scope. Dagster, Open WebUI, Keycloak, Infisical, Synthetic
Website Analytics, and Website Portfolio run on infrastructure-dev
PostgreSQL. The shared
wood-data-platform PostgreSQL remains online only for administrative databases
and rollback copies; it has no active application workloads.

## Development ingress

The reusable infrastructure Caddy runs on the Beelink LAN address at
`192.168.1.21:8080` and `192.168.1.21:8443`, restricted by the host firewall to
the trusted `192.168.1.0/24` LAN. It serves only HTTP `GET /healthz`; the
reserved HTTPS binding has no route until a future reviewed TLS configuration.
Dagster, Open WebUI, Keycloak, Infisical, and Website Portfolio are behind it.
Their development URLs are `https://dev-dagster.woodhost.cloud`,
`https://dev-openwebui.woodhost.cloud`,
`https://dev-keycloak.woodhost.cloud`, and
`https://dev-infisical.woodhost.cloud`, and
`https://dev-website-portfolio.woodhost.cloud`. Edge Caddy owns those normal
HTTPS URLs and proxies their requests to the isolated infrastructure Caddy listener.
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

Dagster's canonical dev runtime is `compose/dagster/` (webserver, daemon, the
existing gRPC user-code server, the Codex usage code server, and the pinned
OpenProject Reports code server).
The report code server reads `OPENPROJECT_BASE_URL`, `OPENPROJECT_API_TOKEN`,
`GOOGLE_DRIVE_CREDENTIALS_JSON`, and `GOOGLE_DRIVE_FOLDER_ID` from the protected
Infisical-resolved Dagster environment file. Dagster loads it as the
`openproject_reports` location; its daily schedule runs at 06:00 America/New_York.
The webserver is reached through `infrastructure-dev-proxy` at
`http://dev-dagster.woodhost.cloud:8080`. The webserver, daemon, and Codex usage
code server join that proxy network; all Dagster services join
`infrastructure-dev-postgres`. The legacy runtime and source database remain
available for rollback until the attended database restore and cutover are
completed.

The dev-only [Codex usage-window schedule](docs/codex-usage-schedule.md) runs
from an infrastructure-owned Beelink code location connected to this Dagster daemon.

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
The [Website Portfolio deployment contract](docs/website-portfolio-deployment.md)
records the pinned artifact, protected inputs, migration, and route.
The [RAG Service deployment contract](docs/rag-service-deployment.md) records
its database bootstrap, Infisical folders, code location, and rollback boundary.

## Repository workflow

Run `uv sync --group dev` once, then `uv run pre-commit install`. Pre-commit blocks
local commits directly to `main` and validates YAML, secrets/private keys,
Ansible inventories and syntax, Ansible lint, and Compose configuration. Work on
a branch and merge through a reviewed pull request; local hooks complement GitHub
branch protection. The `main` ruleset requires PR validation. Semantic-release
tags the validated merged commit without writing a new commit to `main`; see
the [shared branch policy](https://github.com/SpencerRWood/workflows/blob/main/docs/branch-rules.md).

The pull-request wrapper calls `validate.yml@v1` using `.github/release.toml`.
It opts into the shared `infrastructure-validation` commit status on the PR head
so the Website Portfolio dev promotion can read the result with a narrowly
scoped token. The Actions check remains the normal CI result.
The shared release workflow runs the same checks after changes reach `main`,
then determines the next version from conventional commits. Its release job
tags that validated merged commit `vX.Y.Z` and publishes the GitHub Release.
The Git tag is the version source for this non-package repository. A published
release invokes the shared deployment workflow on the
dedicated Beelink infrastructure runner, which checks out the exact
tag, validates it, applies `ansible/playbooks/dev.yml`, and runs
`scripts/health-check-dev.sh`. Deployments are serialized by
`deploy-infrastructure-dev`; a newer run never interrupts an active apply.
Automatic and manual deployment enter the same `.github/workflows/deploy.yml`.
It holds the target's inventory, runner, protected file path, health command,
and durable state path. The shared resolver verifies an explicit published
release or selects the latest one for a manual run with no release input.

On deployment or health failure the workflow restores the prior successful
`infrastructure-dev` Environment release once and validates it. Rollback restores
prior repository-defined runtime configuration only; it does not perform a blind
database rollback. Use **Actions → Deploy released infrastructure development
configuration → Run workflow** for a controlled redeploy of an existing release
(or leave the input empty for the latest). The runner loads its protected local
deployment input outside the Actions checkout; workflow YAML has no secrets. It
has passwordless sudo only for its root-owned deployment wrapper, which accepts
only that runner's workspaces and `apply`, `check`, or `health` operations.

Automatic release deployment is dev-only. `prod.yml` is never called automatically
and production remains an explicit/manual operation.

Renovate follows this same release path. Docker patch and vulnerability
updates are configured for auto-merge. GitHub holds the merge until the required
PR validation check passes.
Minor and major updates remain manual. PostgreSQL compatibility-major changes
remain manual. Routine
Renovate commits are `fix(deps)`, producing semantic-release patch releases.
