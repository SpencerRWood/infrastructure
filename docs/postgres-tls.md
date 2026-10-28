# Managed development PostgreSQL TLS

S07 extraction requires `verify-full` at `192.168.1.21:25433`. This change makes
TLS available on the existing PostgreSQL listener. Existing application HBA rules
and non-TLS clients remain supported; this rollout does not force their migration
or create another database server. Architecture extraction must use verified TLS.

The development manifest enables TLS for future PostgreSQL deployments. Until a
valid bundle is installed, those deployments fail before changing the service.
Production retains its existing disabled setting. The canonical Compose contract
now explicitly requires `POSTGRES_TLS_ENABLED` and `POSTGRES_TLS_DIRECTORY`, both
written by the PostgreSQL role. Do not invoke an old cached Compose environment
against the new payload or deploy the new payload independently of its role.

## Prerequisites and attended deployment

Obtain a server certificate from the approved issuer with IP SAN `192.168.1.21`,
serverAuth purpose and at least 30 days remaining validity. Supply the leaf and
any intermediates as `server.crt`, its unencrypted private key as `server.key`, and
the approved trust bundle as `ca.crt` in an operator-owned protected directory
outside Git. Keep the directory mode 0700 and key mode 0600 or 0400. The code
does not generate a CA, private key or self-signed trust exception. Issuer choice,
key custody and certificate issuance require the existing administrator process.
Use the same trusted CA in the manual and Dagster execution environments.
Install trust in both clients before switching issuers or trust bundles.

The opt-in playbook selects only PostgreSQL and clears application provisioning.
It does not deploy Infisical, change application passwords or activate schedules.
It uses the existing PostgreSQL environment contract: inject the existing
`POSTGRES_DB`, `POSTGRES_USER`, and `POSTGRES_PASSWORD` through the approved
process-only loader; never invent replacement administrator credentials.

After reviewing the deployment/rollback window and recording explicit approval:

```sh
export POSTGRES_TLS_SOURCE_DIRECTORY=/protected/issued-postgres-bundle
ANSIBLE_CONFIG=ansible/ansible.cfg uv run --frozen ansible-playbook \
  -i ansible/inventory/dev ansible/playbooks/postgres-tls.yml \
  -e infrastructure_environment=dev \
  -e postgres_tls_deployment_approval=<recorded-approval-reference>
```

Initial deployment recreates the existing PostgreSQL container to add its TLS
mount/startup options: plan a brief shared-service interruption and check
consumers afterward. It uses the same pinned image, data directory and port.
Ansible first validates chain, endpoint identity, lifetime, key match, ownership
and permissions. Private copies have `no_log` and `diff: false`. Certificate
generations are stored under `postgres-tls/releases/<public-bundle-sha256>`;
the `current` symlink selects the validated generation. The directory is mounted
read-only into PostgreSQL. The key is mode 0400 and owned by its container UID.
Normal deployments without source material require a valid installed generation.

The role probes the actual LAN listener using PostgreSQL's SSL negotiation and
hostname/CA validation without database credentials. It fails if the listener
rejects TLS, the CA is wrong, or identity validation fails. This server-side probe
does not attest client trust installation: run the same probe from the manual
runner and the actual Dagster execution network before generating architecture.
Set `PGSSLROOTCERT` to the approved CA bundle for both extraction processes.

## Renewal, failure and rollback

Use the same attended playbook with a newly issued bundle before the 30-day
deployment threshold. A stable public certificate/CA digest makes unchanged
input idempotent. A new validated generation changes `current` and sends SIGHUP
to PostgreSQL after Compose reconciliation. Invalid candidates fail before
activation. Old generations are retained; do not automatically delete them.
Installed generation files are never overwritten; a digest mismatch stops for
explicit remediation before changing `current`.

Before initial rollout retain the current protected Compose environment and
payload in root-only rollback storage, record the existing image digest/data
mounts and service health, and verify a current recovery point. Never print or
commit the protected environment. Deployment approval must cover the shared
container restart and its rollback. No live rollout is authorized by code review.

If renewed TLS fails, stop extraction, atomically restore `current` to the
previous validated generation, send SIGHUP, and rerun the trusted endpoint and
consumer checks. Do not fall back to `sslmode=disable`, `require` or plaintext
for architecture generation. After a failed initial rollout, the separately
approved rollback restores the old protected Compose environment and payload
and recreates only PostgreSQL against the unchanged data volume. That restores
the pre-rollout server while architecture extraction remains blocked. Do not
restore database data or rotate passwords as part of transport rollback.

The TLS deployment deliberately leaves other services' connection policy alone.
Once both architecture execution environments verify the endpoint, provision the
single Infisical credential and reader with `docs/architecture-reader.md` and
complete its metadata/data-denial checks. Nothing in this change creates a
development-push generator trigger or a second weekly schedule.

`wood repo validate --json` runs the infrastructure suite, including synthetic
certificate and TLS-negotiation tests. `wood repo verify --json` additionally
requires the real local PostgreSQL TLS fixture alongside the existing recovery
verification. Missing PostgreSQL/OpenSSL binaries fail that required check
rather than being reported as a passing skipped test. All fixtures are disposable
and use no live certificates, application data or credentials.
