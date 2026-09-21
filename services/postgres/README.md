# Shared PostgreSQL service

The standalone PostgreSQL component is defined by
[`../../compose/postgres/compose.yml`](../../compose/postgres/compose.yml) and
deployed only when selected by an environment manifest. In this release it is
enabled for `dev` and creates a fresh, independent PostgreSQL 16 cluster.

No application database is provisioned or migrated by this component. The
existing shared wood-data-platform PostgreSQL server remains the source and
rollback instance for the next migration phase.
