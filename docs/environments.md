# Environments

## dev

`environments/dev` represents the current local/home-server environment. It
will eventually compose shared services and development/staging workloads.
Its Compose file is a deliberately empty topology scaffold: no services are
started or provisioned by this repository initialization.

Use `environments/dev/.env.example` as the shape for a local, untracked
`environments/dev/.env` only when a service is intentionally introduced.

## prod

`environments/prod` represents the future DigitalOcean production environment.
It will eventually compose production shared services and application
workloads. The planned host root is `/srv/wood`; this repository does not
create or modify that directory in Step 6.

Use `environments/prod/.env.example` only as a placeholder contract. The
actual production credentials are created when a service is onboarded.

## Shared principles

- Docker Compose is the runtime composition model in both environments.
- Configuration and credentials are environment-specific and never committed.
- Production consumes immutable image versions or digests, never `latest`.
- CloudBeaver is not part of either environment topology.
- Terraform implementation and cloud resources are deferred to Step 7.
