# Shared PostgreSQL provisioning

PostgreSQL is shared infrastructure. Each onboarded application receives one
application database and three deliberately distinct identities.

| Identity | Purpose | Privilege boundary |
| --- | --- | --- |
| Bootstrap/admin | Creates roles and databases during controlled provisioning | Administrative only; never used by applications or migrations |
| Migration role | Applies schema migrations | Owns application schema objects and can perform DDL there |
| Runtime role | Runs the application | Connects and performs only the DML privileges required by the application |

The bootstrap identity is a short-lived operational credential. It is not a
normal application account and is not supplied to migration tools.

## Provisioning flow

When PostgreSQL is deliberately deployed, an operator supplies untracked
environment variables to `postgres/scripts/provision-database.sh`. The script
passes explicitly named variables to `bootstrap.sql`, which:

1. creates the runtime and migration roles without superuser, role-creation, or
   database-creation privileges;
2. creates the application database owned by the migration role;
3. revokes default public access;
4. grants the runtime role connection and schema data privileges; and
5. sets default privileges so migration-created tables, sequences, and
   functions remain usable by the runtime role.

The scaffold is a one-time bootstrap template. Before using it operationally,
review the target application’s required schema privileges and database naming.
It deliberately performs no database connection during Step 6.

## Required operator variables

```text
POSTGRES_ADMIN_URL
POSTGRES_APP_DATABASE
POSTGRES_RUNTIME_USER
POSTGRES_RUNTIME_PASSWORD
POSTGRES_MIGRATION_USER
POSTGRES_MIGRATION_PASSWORD
```

Do not reuse the PostgreSQL superuser/bootstrap password for runtime or
migration credentials.

## Events Service development exception

Events Service runs Alembic itself and uses one canonical `WES_DATABASE_URL`.
Its approved dev exception uses the `events_service` role as owner of only
the `events_service` database. It has no superuser, database creation, role
creation, replication, bypass-RLS, or role membership privileges. Role-specific
`pg_hba.conf` rules reject connections to other databases. PUBLIC access to
its database and public schema is revoked. Its ownership permits migrations
and runtime DML within its assigned database.

`environments/dev.yml` declares the resource in `postgres_applications`.
The PostgreSQL Ansible role provisions it during the normal dev playbook;
production selects no application entries. This declarative path is separate
from the older one-time bootstrap scaffold above.

The sole credential source is the existing Events Service Infisical project
`7ea10433-2eeb-4c57-95a9-b793dd40c7a4`, environment `dev`, path
`/events-service`, key `WES_DATABASE_URL`. An attended deployment exports that
key without printing it and synchronizes a protected deployment copy to the
administrator's `/home/spencerwood/.config/wood/infrastructure/dev.env` and
`/home/github-runner-infrastructure/.secrets/dev.env`, mode `0600`, following
the existing protected input convention. No independent password is stored.
Ansible requires this input on clean deployment and decodes its URL password
in memory. The dev URL uses LAN endpoint `192.168.1.21:25433` for the existing
repository launcher; PostgreSQL does not require SSL in this dev deployment.

Provisioning creates missing resources and converges schema and connection
permissions. It rejects unexpected existing ownership or elevated role flags.
An existing password is never reset: an authentication check fails if the
protected input differs. Intentional rotation requires a separate operation
and synchronization of the canonical URL and protected deployment copies.
Repeat the dev playbook to verify convergence; application data and migrations
are never rolled back by this provisioning path.
