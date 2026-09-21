# PostgreSQL migration boundary and next-release inventory

Dagster, Open WebUI, Keycloak, and Infisical are completed infrastructure-dev
database migrations. Their shared source databases and legacy runtimes are
retained exclusively as rollback material.
Homelab databases are already separate and must not be copied into
infrastructure-dev. Website-portfolio migration is deferred; RudderStack is out
of scope.

| Database | Owning service | Classification | Current role | Extensions | Current host/storage | Priority | Target action | Rollback |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `synthetic_website_data` | Synthetic Website Analytics | infrastructure-dev | application data | verify before migration | shared wood-data-platform / legacy bind mount | candidate | assess export/import and service cutover | retain source; tested restore |
| `dagster` | Dagster | infrastructure-dev | orchestration metadata | `plpgsql` | infrastructure-dev Postgres; legacy source retained | migrated | final custom-format backup restored; 9 runs and 179 event logs verified | stop infrastructure runtime; restart retained legacy project/database |
| `openwebui` | Open WebUI | infrastructure-dev | application state | `plpgsql` | infrastructure-dev Postgres; legacy source retained | migrated | logical backup restored; 43 public tables verified | stop infrastructure runtime; restart retained legacy container/database |
| `infisical` | Infisical | infrastructure-dev | system/internal | `plpgsql` | infrastructure-dev Postgres; legacy source retained | migrated | logical backup restored; 752 public tables verified | stop infrastructure runtime; restart retained legacy container/database |
| `keycloak` | Keycloak | infrastructure-dev | system/internal identity state | `plpgsql` | infrastructure-dev Postgres; legacy source retained | migrated | logical backup restored; 88 public tables verified | stop infrastructure runtime; restart retained legacy container/database |
| `wood_data` | unknown | unknown | historical default or application state | verify before migration | shared wood-data-platform / legacy bind mount | low | inspect ownership; do not delete | no action until identified |
| `portfolio_website` | website-portfolio | deferred | application data | out of scope | shared wood-data-platform / legacy bind mount | none | no action | preserve source |
| `postgres` | PostgreSQL | system/internal | administrative default database | `plpgsql` | shared wood-data-platform / legacy bind mount | none | do not migrate as app data | n/a |

The observed shared cluster also contains service databases outside this release,
including Grafana, Mealie, OpenProject, Vaultwarden, and Vikunja. They are
system/internal or unknown pending an owning-service decision. Before a candidate
migration, record owner, role grants, extensions, hostname, storage source, size,
backup/restore proof, dependencies, and tested rollback. Do not infer that every
remaining database belongs in infrastructure-dev.
