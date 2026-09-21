# Environments

`ansible/playbooks/dev.yml` targets `ansible/inventory/dev` and loads
`environments/dev.yml`. It explicitly enables Postgres and Caddy. Dev Caddy is
bound to Beelink's LAN address `192.168.1.21` on `8080` and `8443`; UFW limits
these ports to `192.168.1.0/24`. Homelab Caddy retains Beelink ports `80` and
`443`. The proxies and their Docker networks are intentionally independent—no
compatibility bridge exists. Its initial Caddyfile is HTTP-only; `8443` is
reserved for later reviewed TLS configuration.
`ansible/playbooks/prod.yml` targets
the separate, currently empty `ansible/inventory/prod` and loads
`environments/prod.yml`, where both components are false. The prod manifest
records future direct `:80/:443` bindings without enabling deployment; TLS
configuration remains an explicit reviewed change.

Adding a component definition does not deploy it to production. A production host,
secret contract, and `services.<name>: true` are all deliberate future work.

Local secrets are names-only examples in `environments/dev.env.example` and
`environments/prod.env.example`. direnv loads one untracked file from
`~/.config/wood/infrastructure/<environment>.env`, then Ansible deploys protected
server-side files. Never commit credentials or print them in logs.

The dev Postgres instance is intentionally empty except for standard PostgreSQL
administrative databases. It is independent from the existing shared
wood-data-platform cluster and has no application schema or bootstrap payload.

Caddy requires no secrets for this initial internal health route. Its runtime
configuration is still written as a protected host file, following the component
deployment convention. No application ingress route is created or migrated.
Route fragments under `compose/caddy/routes/` are added only as part of an
individual service migration, together with its Compose definition, database,
secrets, `infrastructure-dev-proxy` membership, validation, legacy shutdown,
and rollback plan. Dev URLs explicitly include alternate ports, for example
`http://dev-<service>.woodhost.cloud:8080`; DNS does not conceal the port.

Dagster is selected only in `dev`; production remains disabled. Its protected
runtime environment reads `DAGSTER_POSTGRES_PASSWORD` and
`MACBOOK_DAGSTER_HOST` from the untracked dev environment. Its route moves only
with the runtime and does not alter homelab Caddy.
