# PostgreSQL bootstrap scaffold

`scripts/provision-database.sh` validates the six required provisioning
variables and invokes `scripts/bootstrap.sql` using `psql` variables. It is a
parameterized template for a deliberately scheduled onboarding operation; it
is not executed by validation or by Docker Compose.

The script creates an application database, a runtime role, and a migration
role. The bootstrap/admin identity is required only to perform that controlled
setup and must not be reused by the application or migration process.

See [database provisioning](../docs/database-provisioning.md) for the
privilege model and required variables.
