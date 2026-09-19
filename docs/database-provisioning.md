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
