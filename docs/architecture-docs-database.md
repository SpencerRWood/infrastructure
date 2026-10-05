# Architecture Docs database

The explicit dev `postgres_applications` entry provisions the `architecture_docs`
database and login role on Infrastructure PostgreSQL at `192.168.1.21:25433`.
Production is not selected. The shared PostgreSQL role validates the canonical
URL, refuses unsafe existing role privileges or ownership, revokes public access,
adds database-specific SCRAM connection rules, and verifies the password without
rotating it. Application code creates and versions its own tables.

`ARCHITECTURE_DOCS_DATABASE_URL` is stored in Infrastructure Dev's Infisical
`dev:/architecture-docs` folder. The PostgreSQL task resolves this exact key using
the protected dev bootstrap identity on the target. The existing resolver's
`--stdout-key` mode returns the value only to a `no_log` Ansible task and does not
create an environment cache. Failed resolution never falls back to a controller
environment value. Do not create an independent password or write the URL into
Git or diagnostic output. The protected controller contract still supplies
PostgreSQL administrator inputs. The bootstrap identity must have read access to
`dev:/architecture-docs` before release-tag deployment. Creating the Infisical
secret alone does not provision the role or database.

For an attended provisioning run from this repository, after loading the existing
administrator inputs and reviewing the inventory and PostgreSQL changes:

```sh
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
