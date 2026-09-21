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
compose/postgres/     Canonical standalone PostgreSQL Compose component
environments/*.yml    Explicit dev/prod service-selection manifests
environments/*.env.example  Names-only local secret contracts
docs/                 Ownership, environment, and migration guidance
terraform/            Future cloud-infrastructure ownership
```

## Environments and secrets

`dev` enables the standalone PostgreSQL component; `prod` explicitly disables
it and contains no host. Production services are opt-in through reviewed changes.
direnv loads one untracked local file:
`~/.config/wood/infrastructure/dev.env` by default, or `prod.env` when
`INFRASTRUCTURE_ENV=prod`. Ansible writes server-side values under
`/srv/infrastructure/secrets/<environment>/` as `root:root` mode `0600`.

Website-portfolio and RudderStack are out of scope. No application database was
migrated; the existing shared wood-data-platform PostgreSQL remains the migration
source and rollback instance.

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
releases from conventional commits; it does not deploy infrastructure.
