# Architecture and ownership

| Owner | Responsibility |
| --- | --- |
| Terraform | Cloud hosts, volumes, DNS, firewall/network primitives, future DigitalOcean resources |
| Ansible | Host configuration, canonical directories, protected environment files, Compose payloads, validation |
| Docker Compose | Portable platform-service lifecycle |
| Environment manifests | Explicit per-environment service selection |
| Application repositories | Source, migrations, tests, and releases |

Components are a shared catalog, not a stack promotion mechanism. `dev` and
`prod` separately declare services in `environments/dev.yml` and
`environments/prod.yml`; production is opt-in. The canonical Postgres component
is present in the catalog, but only dev enables it.

The dev Postgres state path is `/srv/infrastructure/state/postgres/data`; it uses
the internal-only `infrastructure-dev-postgres` network and restart policy
`unless-stopped`. It has no published host port. Future production Postgres will
be a fresh independent cluster—dev database state is never promoted to prod.
