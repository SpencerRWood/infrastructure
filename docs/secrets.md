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

Do not put credentials in documentation, CI logs, pull requests, Terraform state,
or application configuration. Rotate any credential that is exposed.
