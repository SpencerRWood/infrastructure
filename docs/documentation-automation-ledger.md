# Documentation Automation development ledger

OP-583 / DA-R1-S07 uses a dedicated `documentation_automation` database and login
on the existing swood-server PostgreSQL service. This is the application state
ledger, separate from the metadata-only `architecture_reader` and its single shared
password. Preserve the existing `architecture_docs` application and all other
databases. The new role owns only its assigned ledger so the application's existing
`Ledger.migrate()` can create/update its state tables. It has no superuser,
database/role creation, replication, RLS bypass or other role memberships.

The opt-in playbook `ansible/playbooks/documentation-automation-db.yml` calls only
the existing PostgreSQL role's `application` tasks for this selected database. It
does not run the PostgreSQL deployment tasks, recreate containers, modify Compose,
restart the cluster, or select the other `postgres_applications` from dev.yml.
It uses the established SCRAM connection restrictions, safe password parsing,
server log suppression and Ansible `no_log` behavior. Existing credentials are
verified, never silently reset; unsafe existing roles/ownership fail closed.

## Before the attended operation

1. Obtain explicit approval for this concrete ledger provisioning operation.
2. Verify fresh recovery/backup readiness for the existing cluster and record
   its actual evidence. A reference string alone is not verification.
3. Check whether database/role and the Infisical key already exist. Stop on an
   unexpected partial setup or ownership; do not overwrite credentials.
4. If absent, generate a strong random password in memory and securely create
   `DOCUMENTATION_AUTOMATION_DATABASE_URL` in Infrastructure Dev project
   `7ea10433-2eeb-4c57-95a9-b793dd40c7a4`, environment `dev`, path
   `/documentation-automation`. Its URI has scheme `postgresql`, matching user and
   database `documentation_automation`, and endpoint `192.168.1.21:25433`. Use a
   securely encoded password of at least 32 characters; no URI query or fragment.
   Do not place the URI/password in Git, chat, argv, logs or a temporary env file.
5. Supply existing protected bootstrap `POSTGRES_USER` and `POSTGRES_DB` values to
   the command process. Reuse the server's established Infisical bootstrap identity;
   no replacement admin password or PostgreSQL restart is needed.

## Apply only the selected ledger

From the reviewed infrastructure checkout, with its normal Ansible dependencies:

```sh
ANSIBLE_CONFIG=ansible/ansible.cfg uv run --frozen ansible-playbook \
  -i ansible/inventory/dev ansible/playbooks/documentation-automation-db.yml \
  -e infrastructure_environment=dev \
  -e documentation_automation_ledger_apply=true \
  -e documentation_automation_ledger_approval_reference=NON_SECRET_APPROVAL_REFERENCE
```

The preflight requires existing PostgreSQL TLS to be on. The application process
must separately set `PGSSLMODE=verify-full` and point `PGSSLROOTCERT` to the approved
public CA certificate. Do not put TLS settings into a URI query to bypass the
existing credential validator. The bootstrap's local administrative connection is
not the application client connection.

Repeat provisioning and verify no changes. Through the dedicated application URI
and verified TLS, run the merged application's `Ledger.migrate()` through version
6, repeat migration, and verify the schema/checksum and all expected tables. Check
role flags, ownership, absence of memberships, authentication and denial of
connections to unrelated databases. Keep full redacted operational logs and bounded
results as Story evidence. Run no LLM or architecture generator during migration.

## Recovery and delivery boundary

Do not delete an existing application ledger or restore shared PostgreSQL data to
undo this onboarding. On a failure, stop consumers, retain the dedicated resources
and evidence, and diagnose the exact failed phase. Revoke a newly issued unused
credential only after determining its consumers; secret replacement does not
invalidate an already provisioned database password. A later intentional rotation
needs a separately reviewed synchronization operation.

This playbook remains opt-in; normal dev/prod deployments do not activate it.
Infrastructure preserves its existing main-only branching and pinned release
workflow. Source integration does not authorize this attended operation, runtime
registration, a baseline publication, schedule activation or S06 release/deployment.
