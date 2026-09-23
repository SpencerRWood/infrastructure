# Secrets and credentials

Real secrets stay outside Git. Create `~/.config/wood/infrastructure/dev.env` or
`prod.env` from the names-only examples and let direnv load exactly the selected
environment. `POSTGRES_PASSWORD` is never stored in Compose or output by Ansible.

Ansible writes a root-owned environment file and a separate root-owned password
file under `/srv/infrastructure/secrets/<environment>/`, both mode `0600`; secret
tasks use `no_log`. Docker Compose reads the password through a Compose secret.

The Beelink infrastructure runner is bootstrapped from the existing untracked
development input at `/home/spencerwood/.config/wood/infrastructure/dev.env`.
Provisioning copies it to `/home/github-runner-infrastructure/.secrets/dev.env`
with mode `0600`. This runner-local copy supplies Ansible lookups during
release-tag deployments; it is distinct from the root-owned runtime files above.

Website Portfolio adds three required names to the same protected development
input: `WEBSITE_PORTFOLIO_DATABASE_URL`,
`WEBSITE_PORTFOLIO_MIGRATION_DATABASE_URL`, and
`WEBSITE_PORTFOLIO_GHCR_TOKEN`. The runner's input is copied only on initial
bootstrap, so update both the administrator's source file and the protected
runner-local copy before the first website release deployment. The role writes
separate root-owned runtime and migration environment files and an isolated
root-owned Docker login config under `/srv/infrastructure/secrets/dev/`.
See [Website Portfolio deployment](website-portfolio-deployment.md) for the
credential scope and provisioning steps.

Do not put credentials in documentation, CI logs, pull requests, Terraform state,
or application configuration. Rotate any credential that is exposed.
