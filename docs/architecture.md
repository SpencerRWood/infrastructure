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
`environments/prod.yml`; production is opt-in. The canonical Postgres and Caddy
components are present in the catalog, but only dev enables them.

The dev Postgres state path is `/srv/infrastructure/state/postgres/data`; it uses
the internal-only `infrastructure-dev-postgres` network and restart policy
`unless-stopped`. It has no published host port. Future production Postgres will
be a fresh independent cluster—dev database state is never promoted to prod.

## Ingress ownership

On Beelink, homelab Caddy remains the outer edge and owns LAN ports `80` and
`443` plus the homelab `proxy` Docker network. Infrastructure dev Caddy is a
separate runtime, with loopback-only `127.0.0.1:8080` and `127.0.0.1:8443`
bindings, persistent state under `/srv/infrastructure/state/caddy/`, and its own
`infrastructure-dev-proxy` network. It currently exposes only its `/healthz`
verification endpoint. The initial Caddyfile is HTTP-only; the loopback HTTPS
binding is reserved for later reviewed TLS configuration.

Future infrastructure services will explicitly join the infrastructure proxy
network as they migrate. During a transitional Beelink migration, the intended
path is `homelab Caddy -> infrastructure-dev Caddy -> infrastructure service`;
any outer-edge forwarding remains a separate, service-specific change. On a
dedicated production host, infrastructure-prod Caddy may own `:80/:443`
directly. Component availability never enables production deployment by itself.
