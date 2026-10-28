# Architecture metadata reader (DA-R1-S07)

This opt-in playbook provisions `architecture_reader`; it is not included in
routine environment deployment. Generation remains gated on successful
provisioning and verification. No target database or Infisical folder is inferred.

`environments/architecture-reader-dev.yml` records the owner-selected development
scope: `events_service`, `portfolio_website`, and `rag_service` each use `public`;
`synthetic_website_data` uses `public`, `raw`, `staging`, `intermediate`, and
`marts`. Live schema names were verified through read-only catalogs. The secret
folder is `/documentation-automation` in the existing infrastructure Infisical
project. This file is not loaded automatically by routine deployment.

Supply a non-secret `architecture_reader_input` mapping with `databases` (a
nonempty list of distinct `{name, schemas}` entries) and `infisical_path`.
Every schema list must be nonempty. Explicitly choose
`infrastructure_environment` and its matching inventory. All selected databases
and schemas must already exist. The host must have the existing protected
Infisical bootstrap identity and `POSTGRES_USER` must name its administrator.

The sole credential is `ARCHITECTURE_POSTGRES_PASSWORD`. Generate a strong random
URL-safe value (at least 48 characters) directly into the approved Infisical
scope using an authenticated secret-management process. Never copy it into
extra vars, shell history, files, Git, logs, or a second baseline-only secret.
Credential creation and target access must be explicitly scoped before execution.
The playbook retrieves this one value through the existing Infisical resolver
on every invocation, under `no_log`, and sends SQL over stdin. It does not
cache plaintext on the host. Check mode validates scope without resolving secrets
or changing PostgreSQL.

```sh
ANSIBLE_CONFIG=ansible/ansible.cfg uv run ansible-playbook \
  -i ansible/inventory/dev ansible/playbooks/architecture-reader.yml \
  -e @environments/architecture-reader-dev.yml
```

The role receives CONNECT and USAGE only, no table, column or sequence grants.
It cannot own databases/schemas/tables or belong to another role. Unexpected
privilege, ownership, PUBLIC data access, PUBLIC CREATE/TEMP privileges or
callable security-definer application functions fail closed. The playbook does
not revoke PUBLIC privileges or alter application owners to repair these cases:
review such remediation separately because it can affect existing services.
PostgreSQL's shared system catalogs expose schema metadata without granting
application-table SELECT. Metadata is not a security boundary between schemas;
the generator must apply the approved database/schema scope to its output.

Database/server statement auditing must be reviewed before live provisioning.
The SQL disables ordinary statement, duration and error-statement logging for
its session; an external audit extension or proxy may impose additional logging
outside those controls. Credential-bearing Ansible tasks use `no_log`.

Repeat provisioning with an unchanged password: authentication succeeds, the
password is not rewritten, and already-satisfied grants remain unchanged. A
single cluster-wide role and password serve every allowed database; password
creation/rotation runs only on the first database. Each database independently
verifies metadata visibility and application-data denial. HBA rules allow only
the explicit database list and reject all others for this role.
For rotation, update the SAME Infisical secret, rerun the playbook, and rerun
metadata/data-denial verification. Only an explicit password-authentication
failure permits password reconciliation; connection failures stop the playbook.
Both manual baseline and subsequent weekly Dagster execution must resolve that
same secret at invocation time, with non-secret endpoint settings kept separate.
No application configuration edit or schedule activation accompanies rotation.

The SQL verifies effective table and column privileges, sequence access and
unsafe functions, then actually attempts zero-row application SELECTs and
requires permission denial. Test with a disposable local PostgreSQL cluster
before the selected live environment. The initial manual baseline must wait
for these checks, and S06 stays blocked until all of S07 is accepted.
