# infrastructure-dev v0.15.6 deployment failure

## Diagnosis

Release v0.15.6 (25eca0c586134975464e9bd093f62eec8c2a4969), Actions
run 37010412362 / job 110849022886, applied successfully but failed health.
Container d4d6e9d0367c is `infrastructure-dev-dagster-dagster-daemon-1`,
using `local/infrastructure-dagster:1.13.16`, image ID
`sha256:6ce44f47893281711a7d417764e6123296b3caa71f70852cd88e35f3a793cadb`.
The Dagster webserver also crashed. Both logs end in
`ModuleNotFoundError: No module named 'psycopg'`; neither is OOM-killed.
The daemon restarts before retaining Docker health-check output.

The runtime contains Dagster 1.13.16, dagster-postgres 0.29.16,
SQLAlchemy 2.1.2 and psycopg2-binary 2.9.13. Dagster's PostgreSQL storage
configuration constructs a plain `postgresql://` URL. SQLAlchemy 2.1 selects
psycopg3 for that URL, while dagster-postgres installs psycopg2. Engine creation
reproduces the missing-driver failure without any database connection or secrets.
See [SQLAlchemy's migration notes](https://docs.sqlalchemy.org/en/21/changelog/migration_21.html).

The Dockerfile did not constrain SQLAlchemy. The image was built during the
failed deployment (13:06:34 UTC), selecting 2.1.2. Repository validation used
SQLAlchemy 2.0.52 from uv.lock and therefore did not exercise the runtime's
dependency set. v0.15.5 has the same unpinned Dockerfile. This is a latent
Dagster dependency-resolution defect exposed by rebuilding during deployment;
the evidence does not implicate the Keycloak version change.

## Rollback

The job checked out v0.15.5 (1fec83c) and Ansible completed with
ok=104 changed=5 unreachable=0 failed=0. Its subsequent health check failed
on the same Dagster daemon. Keycloak was restored to 26.7.4 and is healthy.
Rollback applied configuration but did not restore a healthy system, since
the previous release shares the defective image build definition.

The reusable deploy-ansible workflow uses `set -euo pipefail`, applies the
previous tag, and checks its health before reporting rollback success.
`continue-on-error` allows metadata recording; `steps.rollback.outcome`
still records failure. Durable metadata retained current_release=v0.15.5
(the last successful release), last_attempt_release=v0.15.6,
last_attempt_state=failure, rollback_release=v0.15.5, rollback_state=failure.
That current_release field is historical, not a claim of current health.
No separate rollback-control or outcome-reporting defect was established.

## Fix and recovery contract

Pin the image's SQLAlchemy to the repository-validated 2.0.52 and check
dependency consistency and Dagster engine/driver loading during image build.
The smoke check performs no database writes. Keep Keycloak 26.8.0, existing
health gates, Infisical resolution, immutable release checkout, freshness checks,
rollback and metadata behavior. Recover through a new normal release;
v0.15.6 must remain a failed attempt.
