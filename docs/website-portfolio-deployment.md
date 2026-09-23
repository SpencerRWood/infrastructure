# Website Portfolio development deployment

The `dev` manifest pins the previously validated GHCR artifact at
`ghcr.io/spencerrwood/website-portfolio:v0.6.0@sha256:743d194b77a7f54e8a4f454a22b0cdf5a36113e10c455af0088658175970740e`.
Change this checked-in value through an infrastructure PR for each future image.
The Beelink never builds application source or looks up a moving tag.
The existing local website containers remain untouched during this dev rollout;
the new hostname validates the Beelink runtime separately.

The application joins `infrastructure-dev-postgres` and
`infrastructure-dev-proxy`. It exposes port 8000 to those Docker networks only.
Infrastructure Caddy routes `dev-website-portfolio.woodhost.cloud` to the
container; edge Caddy provides the normal HTTPS hostname. The authoritative
deployment health gate waits for HTTP 200 at both `/health` and `/` through
infrastructure Caddy, in addition to checking container liveness.

## Protected deployment input

Add these entries to the untracked administrator file
`/home/spencerwood/.config/wood/infrastructure/dev.env` on the Beelink and to
the runner-local copy at
`/home/github-runner-infrastructure/.secrets/dev.env` (owner
`github-runner-infrastructure`, mode `0600`). The `github_runner` role copies
the administrator file only on initial bootstrap; later changes require an
explicit protected copy. Local validation may use the matching
`~/.config/wood/infrastructure/dev.env` on the control machine.

| Name | Purpose |
| --- | --- |
| `WEBSITE_PORTFOLIO_DATABASE_URL` | `postgresql+psycopg://portfolio_runtime:...@postgres:5432/portfolio_website` |
| `WEBSITE_PORTFOLIO_MIGRATION_DATABASE_URL` | Same database via `portfolio_migrator` |
| `WEBSITE_PORTFOLIO_GHCR_TOKEN` | Pull-only classic GitHub token |
| `WEBSITE_PORTFOLIO_RUDDERSTACK_WRITE_KEY` | Optional public browser key |
| `WEBSITE_PORTFOLIO_RUDDERSTACK_DATA_PLANE_URL` | Optional public data plane URL |

The existing `portfolio_website` database and separate runtime and migration
roles are reused. `portfolio_migrator` owns the schema; existing default grants
give `portfolio_runtime` access to migration-created tables and sequences.
The runtime environment sets `WEBSITE_ENV=production`. The migration environment
uses the migration URL as `DATABASE_URL` because the image's Alembic entrypoint
reads that name. The role writes separate root-owned `0600` files under
`/srv/infrastructure/secrets/dev/` and never prints their values.

## Private GHCR pull

The package is private. Use GitHub username `SpencerRWood` and a dedicated
personal access token **(classic)** with only `read:packages`, held by an
account with read access to the `website-portfolio` package. GitHub Packages
does not currently accept fine-grained personal access tokens for registry
authentication. Do not reuse the operator's broader GitHub CLI token. The
Ansible `community.docker.docker_login` task authenticates idempotently to
`ghcr.io` using the protected runner input and stores Docker credentials in
`/srv/infrastructure/secrets/dev/ghcr-docker/config.json` under a root-only
directory. Compose pull, migration, and start use that host-side Docker config;
no credential appears in Compose YAML or the application environment.

Before merging, provision the protected input, then verify the pinned image
pulls on the Beelink with this Docker config. The normal release deployment
checks out the infrastructure release tag, applies Ansible, runs the one-shot
`alembic upgrade head` container from the exact pinned image, and only then
starts the long-running service. Migration failure fails the apply step.

The deployment workflow records durable state only after apply and route
readiness succeed. Its existing release rollback reapplies the prior successful
infrastructure tag and rechecks health. Future image rollbacks therefore use
the previous tag's checked-in image reference. Database migrations are not
automatically downgraded.
