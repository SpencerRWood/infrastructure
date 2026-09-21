# Environments

`ansible/playbooks/dev.yml` targets `ansible/inventory/dev` and loads
`environments/dev.yml`. It explicitly enables Postgres and Caddy. Dev Caddy is
limited to `127.0.0.1:8080` and `127.0.0.1:8443`, preserving homelab Caddy's
Beelink ownership of ports `80` and `443`. Its initial Caddyfile is HTTP-only;
the reserved loopback HTTPS binding is for later reviewed TLS configuration.
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
