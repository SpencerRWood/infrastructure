# Architecture Docs database

The explicit dev `postgres_applications` entry provisions the `architecture_docs`
database and login role on Infrastructure PostgreSQL at `192.168.1.21:25433`.
Production is not selected. The shared PostgreSQL role validates the canonical
URL, refuses unsafe existing role privileges or ownership, revokes public access,
adds database-specific SCRAM connection rules, and verifies the password without
rotating it. Application code creates and versions its own tables.

`ARCHITECTURE_DOCS_DATABASE_URL` is stored in Infrastructure Dev's Infisical
`dev:/architecture-docs` folder. Inject it into the Ansible controller process;
do not create an independent password or write the URL into Git or diagnostic
output. The existing protected controller contract still supplies PostgreSQL
administrator inputs. Before a release-tag deployment, ensure its controller
receives the application URL from Infisical; selecting the application without
this input deliberately fails. Creating the Infisical secret alone does not
provision the role or database.

For an attended provisioning run from this repository, after loading the existing
administrator inputs and reviewing the inventory and PostgreSQL changes:

```sh
infisical run --domain=https://dev-infisical.woodhost.cloud/api \
  --projectId=7ea10433-2eeb-4c57-95a9-b793dd40c7a4 \
  --env=dev --path=/architecture-docs -- \
  uv run ansible-playbook -i ansible/inventory/dev \
    ansible/playbooks/dev.yml --tags postgres
```

Use the repository's `ANSIBLE_CONFIG=ansible/ansible.cfg`. Verify the dedicated
role has no superuser, database-creation, role-creation, inheritance, replication,
or RLS-bypass privileges; verify its database owner and connection restrictions.
Then run Architecture Docs' application migration/import procedure. This change
does not deploy or schedule an Architecture Docs application runtime.

Back up the application database before application cutover or future schema
changes. Withdrawing the manifest entry does not drop the database or role.
Preserve their state on rollback; never rotate an existing password implicitly
or restore stale database state over accepted publication intents.
