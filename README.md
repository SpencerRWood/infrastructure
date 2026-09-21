# infrastructure

Infrastructure topology and runtime composition for Wood environments. This
repository owns environment-level configuration; application repositories keep
their source code, Dockerfiles, tests, migrations, and application releases.

## Scope

This repository owns the standalone PostgreSQL runtime definition and its
minimal Ansible deployment path. It does not contain real credentials.

The repository owns:

- Docker Compose topology for `dev` and `prod`, including canonical PostgreSQL
- Ansible deployment and validation of the PostgreSQL runtime
- shared PostgreSQL provisioning conventions
- deployment-facing environment contracts
- future Terraform configuration and state conventions
- infrastructure validation

It does not own application source code or application-specific migrations.
Website-portfolio and RudderStack remain out of scope.

## Layout

```text
docs/                 Architecture, environment, secret, and database guidance
environments/dev/     Local/home-server Compose topology and placeholders
environments/prod/    Future DigitalOcean Compose topology and placeholders
postgres/             Parameterized, least-privilege database bootstrap scripts
services/postgres/    Shared PostgreSQL service ownership notes
compose/postgres/     Canonical PostgreSQL Docker Compose payload
ansible/              Minimal host deployment and validation for PostgreSQL
scripts/validate.sh   Lightweight repository validation
terraform/            Future Terraform ownership and state conventions
```

## Environments

- `dev` is the current local/home-server environment. It will eventually host
  shared services and development/staging workloads.
- `prod` is the future DigitalOcean environment. It will eventually host
  production shared services and application workloads.

Both environments use Docker Compose as the runtime composition model. This
repository deliberately does not introduce Kubernetes or CloudBeaver.

## Future deployment boundary

```text
application release
  -> immutable container image
  -> deployment workflow
  -> runtime host (/srv/wood)
  -> docker compose update
  -> health check
  -> success or rollback
```

Production deployments will use immutable image references; `latest` is not a
production source of truth.

## Secrets

Only names-only examples are committed. `~/.config/wood/dev.env` and
`~/.config/wood/prod.env` are loaded locally with direnv; Ansible writes only the
required PostgreSQL values to `/srv/infrastructure/secrets/postgres.env` as root
mode `0600`. See [the migration runbook](docs/postgres-ownership-migration.md).

## Validation

Run the repository checks locally:

```sh
bash scripts/validate.sh
```

## Release workflow

`workflows@v1` is intentionally not adopted in this initial repository. Its
current contract is for repositories with an established release configuration
and validation toolchain. This repository currently contains Compose, shell,
and documentation scaffolding only; adding a synthetic Python or
semantic-release configuration would be misleading. Re-evaluate adoption when
this repository gains a clean, supported release configuration without
special-casing the centralized workflow.
