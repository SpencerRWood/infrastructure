# Shared PostgreSQL service

The shared PostgreSQL runtime is defined by
[`../../compose/postgres/compose.yml`](../../compose/postgres/compose.yml) and
deployed by the `postgres` Ansible role. This is an ownership transfer of the
existing PostgreSQL 16 cluster, not a bootstrap or rebuild.

Normal applications use their runtime role; migrations use their migration
role; neither receives PostgreSQL superuser credentials.
