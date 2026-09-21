# Environments

`ansible/playbooks/dev.yml` targets `ansible/inventory/dev` and loads
`environments/dev.yml`. It explicitly enables Postgres. `ansible/playbooks/prod.yml`
targets the separate, currently empty `ansible/inventory/prod` and loads
`environments/prod.yml`, where Postgres is false.

Adding a component definition does not deploy it to production. A production host,
secret contract, and `services.<name>: true` are all deliberate future work.

Local secrets are names-only examples in `environments/dev.env.example` and
`environments/prod.env.example`. direnv loads one untracked file from
`~/.config/wood/infrastructure/<environment>.env`, then Ansible deploys protected
server-side files. Never commit credentials or print them in logs.

The dev Postgres instance is intentionally empty except for standard PostgreSQL
administrative databases. It is independent from the existing shared
wood-data-platform cluster and has no application schema or bootstrap payload.
