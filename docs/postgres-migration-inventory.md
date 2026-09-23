# Legacy PostgreSQL remainder inventory

Live audit: Beelink `wood-data-postgres`, 2026-09-21. Runtime state, not the
old planning inventory, is authoritative. After the portfolio cutover, the
legacy server has zero active application sessions.

| Database | Owner | Size | User tables | Disposition | Active consumers | Retention / deletion blocker |
| --- | --- | ---: | ---: | --- | --- | --- |
| `dagster` | `dagster` | 9.6 MB | 22 | rollback-only copy | none | retain through approved rollback period |
| `infisical` | `infisical` | 66 MB | 752 | rollback-only copy | none | retain through approved rollback period |
| `keycloak` | `keycloak` | 12 MB | 88 | rollback-only copy | none | retain through approved rollback period |
| `openwebui` | `openwebui` | 10 MB | 43 | rollback-only copy | none | retain through approved rollback period |
| `synthetic_website_data` | `wood` | 388 MB | 15 | rollback-only copy | none on legacy after restore | retain source and final backup |
| `portfolio_website` | `portfolio_migrator` | 7.6 MB | 0 | rollback-only copy | none | retain source and final backup |
| `wood_data` | `wood` | 7.5 MB | 0 | administrative/bootstrap artifact | none | future deletion candidate; do not delete now |
| `postgres` | `wood` | 7.5 MB | 0 | administrative | PostgreSQL administration | required while cluster exists |
| `template1` | `wood` | 7.6 MB | 0 | administrative template | PostgreSQL administration | required while cluster exists |

All databases have only `plpgsql`. `pg_tables` reports 68 PostgreSQL-system
tables in an empty database; the figures above subtract that baseline. No
Grafana, Mealie, OpenProject, Vaultwarden, or Vikunja database exists on this
cluster. Those running services are homelab-owned and were not changed.

## Synthetic Website Analytics migration record

The source contract had login roles `synthetic_website_editor` and `dbt_editor`;
schemas `raw`, `staging`, `intermediate`, and `marts`; 15 tables, 9 views, no
materialized views or sequences. `synthetic_website_editor` owns `raw` and
`dbt_editor` owns the transformation schemas. Both have required DML grants.

A custom-format backup and globals capture were taken before restore at
`/srv/infrastructure/backups/wood-data-platform/2026-09-21-synthetic-website-data/`.
SHA-256: `0783aab8a7c297c76987baede2956c5928aa29d29ea2fe433704938c441d554f`
for the dump and `40c85ffc6880fb1b8baceb53a056801d6ad067c820804af14994bdf684aead50`
for globals. The restored target has 15 user tables, 9 user views, and zero
sequences. The legacy source remains unchanged for rollback.

## Portfolio Website migration record

The legacy `portfolio_website` source is an intentionally empty application
database: `plpgsql`, `public` owned by `portfolio_migrator`, no user tables,
views, sequences, or Alembic version table. `portfolio_migrator` is the
LOGIN-owning/migration role; `portfolio_runtime` is a separate LOGIN role with
CONNECT access only. The target preserves that model and empty schema state.

Its custom-format dump and globals capture are retained at
`/srv/infrastructure/backups/wood-data-platform/2026-09-21-portfolio-website/`.
SHA-256: `119f6796816b7d40d10e77c6d3ce78833c6cdad5188a4d69003478966b46c399`
for the dump and `042e39350ebc437075af8c7f11f55ceeaeabb9c47895212583098d9386df486a`
for globals. The existing independently owned local website runtime receives its
`DATABASE_URL` from its local Compose configuration and targets
`192.168.1.21:25433`. The new infrastructure-owned runtime uses the same target
database through the private `infrastructure-dev-postgres` network. Its first
deployment applies the pending Alembic migration with `portfolio_migrator`.

The contact endpoint's existing unavailable response remains expected until the
new infrastructure deployment applies that migration.

## Consumer mapping

| Consumer | Database | Host | State |
| --- | --- | --- | --- |
| infrastructure Dagster, Open WebUI, Keycloak, Infisical | named service database | `postgres:5432` on infrastructure-dev | active target |
| synthetic data, analytics, and dbt local checkouts | `synthetic_website_data` | `192.168.1.21:25433` | active target; direct read and dbt validation passed |
| existing local website runtime | `portfolio_website` | `192.168.1.21:25433` | remains online during Beelink validation |
| infrastructure Website Portfolio | `portfolio_website` | `postgres:5432` | selected dev target, migration before startup |
| migrated legacy copies | named above | legacy cluster | rollback only |

## Next release: wood-data-platform runtime decommission

1. Make a final full logical cluster backup and globals capture; checksum both.
2. Re-run `pg_stat_activity` and prove no non-administrative legacy clients.
3. Verify every migrated workload targets infrastructure Postgres.
4. Confirm the portfolio disposition and `wood_data` deletion decision.
5. Stop (do not delete) `wood-data-postgres`; observe jobs and logs.
6. Roll back by starting the retained Compose service and restoring the final backup if needed.
7. Retain legacy state and backups for the approved retention period.
8. Remove obsolete Compose/configuration and storage only after all criteria are signed off.
