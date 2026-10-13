# Recovery backups

The canonical development playbook includes `ansible/roles/backups` when
`services.backups` is selected. The role owns one root cron job at 02:45, separate
from Dagster's daily, weekly and monthly verification. It installs
`/usr/local/sbin/infrastructure-recovery-backup` and a protected credential-free
`/etc/infrastructure/recovery-backup.json`.

## Coverage and prerequisites

The active source is `infrastructure-dev-postgres-postgres-1`, not the retired
wood-data-platform cluster. Every non-template database receives a custom-format
logical dump. Required application databases are Dagster, Open WebUI, Keycloak,
Infisical, portfolio_website, synthetic_website_data, RAG, events_service and
architecture_docs. Cluster roles and ACL prerequisites are captured separately.
Physical PostgreSQL data directories are never archived.

Application writers must be quiesced to capture consistent Dagster local state,
Open WebUI files, RAG documents, Overleaf editor files and Overleaf MongoDB.
Only containers actually running before the backup are restarted afterward,
including on failure. This is a service interruption: rollout must explicitly
approve `backups_quiesce_authorized`. Its default is false and fails closed.
Infisical recovery requires both its database and bootstrap encryption/auth keys.
The bootstrap archive requires an existing `age` recipient; keep its private
identity independently available outside this host and Infisical.

Credentials are resolved from the active container's existing
`POSTGRES_PASSWORD_FILE` contract inside the container. No new credential store,
credential rotation or secret-loader fallback is introduced. Ansible retains
the existing Infisical-managed PostgreSQL bootstrap contract.

Infisical and Overleaf Redis receive validated RDB snapshots through
[`redis-cli --rdb -`](https://redis.io/docs/latest/develop/tools/cli/).
No source persistence files are copied and no CONFIG or SAVE command is issued.
The supported replication export may trigger Redis's background snapshot.
Compiler output, model caches, container
layers and historical migration artifacts are not authoritative recovery copies.
Caddy certificate state and complete
application restart remain explicit full-application acceptance work; database
and archive restoration alone must not claim these passed.

## Storage and publication

The audited development destination is
`/mnt/wood-server-nas/backup_server/swood-server/infrastructure-dev` on exactly
`192.168.1.10:/volume1/recovery_backups/infrastructure-dev`, filesystem `nfs`.
The destination itself must be the dedicated mount; the old parent
`backup_server` mount cannot satisfy this identity check. A wrong or absent mount
fails before destination creation. A local host directory is not a substitute.
The backup-only role persists and mounts this export before installing the
producer schedule. Its systemd mount requires the existing parent mount; that
parent and unrelated NFS entries retain their existing definitions. Test
persistence by stopping and starting only the dedicated mount unit, then
checking its exact source. No production reboot is required.
The NAS survives application-host failure. An off-NAS copy and NAS encryption at
rest are currently unverified; full NAS disaster recovery remains unaccepted.
All new PostgreSQL, file, MongoDB, Redis and Infisical recovery-key artifacts
are encrypted with the YAML age recipient before publication. Existing backups
remain untouched. Encryption and extra copies run after application writers resume.

Runs take an exclusive lock and stage under `.in-progress-*`. Each artifact is
nonempty, format-checked and SHA-256 hashed. A complete immutable group is renamed
into place, then `current.json` is atomically replaced. Verifiers follow this
pointer and never scan temporary directories. Failure preserves the previous
pointer and all historical artifacts without refreshing their source timestamp.
Temporary artifacts are private. Completed directories are producer-owned `0750`
and files `0640` for verifier GID 10001; that group receives read access, not write
access. No secret contents appear in manifests or diagnostics.

An explicit `historical_sqlite_members` list preserves specified historical
copies in encrypted archives without treating them as current recovery inputs.
It cannot overlap required SQLite members. All unclassified SQLite databases
remain integrity-gated, and manifests disclose the historical classification.

The dedicated export retains root squash and preserves verifier UID/GID10001.
The producer adds the configured reader GID only to its own supplementary groups
before destination writes, permitting its required group assignment after root
mapping without changing NAS account membership. Actual producer publication,
private staging, verifier write-denial and unrelated-user denial tests must pass
before rollout. The existing backup_server export and historical artifacts remain
unchanged; a read-only container bind is not the NAS permission test.

The proposed retention is 14 daily, 8 weekly and 12 monthly recovery points.
Pruning is not implemented or enabled: existing backup deletion requires separate
approval. Check NAS capacity before rollout. A one-hour attempt deadline bounds
normal execution; kernel-blocked hard NFS I/O can require operator intervention.

## Run and verify

After the approved rollout and encryption/consistency prerequisites are set:

The focused `ansible/playbooks/dev-backups.yml` installs only the backup role
using the canonical development environment. Preview it with `--check --diff`
before the separately approved apply. It does not run a backup.

```sh
sudo /usr/local/sbin/infrastructure-recovery-backup --config /etc/infrastructure/recovery-backup.json
scripts/weekly_recovery.py --real-backups
```

The backup command emits sanitized JSON and writes independent attempt status to
`/var/lib/infrastructure/backups/last-attempt.json`. A running or failed attempt
is distinct from the last completed recovery group. Check that record, root cron,
the exact NFS mount, and `current.json` after deployment.

`scripts/recovery.py preflight --local-only` validates the current group's actual
timestamps, consumer/environment, required sources, sizes and SHA-256 checksums.
Missing, stale, corrupt and incomplete groups fail. `recovery/backup-policy.yml`
is the repository authority for coverage, rather than the producer's own list.
The existing consumer weekly interface selects real groups. The unflagged weekly
command remains a local fixture development check and is not operational evidence.

The real restore creates disposable storage and a private socket-only PostgreSQL
cluster under an unprivileged user. It copies source artifacts read-only, restores
roles, the original database, ownership and ACLs, runs schema checks, `pg_amcheck`
and representative queries, restores representative RAG file state, then removes
temporary resources. It starts no application workload and uses no live database
URI or production credential. Required engine binaries, extensions and original
database locale must be available. Cleanup failure is reported independently.
Restoration failure is a failed check; missing tools/extensions are unavailable
prerequisites. Source manifests never infer restore success from checksums.

The immutable manifest reports restoration state at publication (`not_run`).
Later actual restore results are separately recorded by Recovery Verification,
bound to the restored artifact checksum and source completion time. The provider
owns readiness evidence; it never writes back to source backup artifacts.

## Operator restoration

Use `recovery/backup-policy.yml` and `scripts/recovery_manifest.py` to validate a
complete group first. Decrypt key archives only inside protected disposable
storage with the independently held identity. Restore globals before databases
using a compatible PostgreSQL engine and required extensions. Preserve original
ownership and ACLs; do not use `--no-owner` or `--no-acl` to disguise failure.
Restore Overleaf MongoDB with a compatible `mongorestore --archive --gzip` into
an isolated database; pair it with editor files from the same group. Never restore
a live database as a test. Live recovery, application startup, production secret
resolution and full-system readiness require their separate operational gates.

If mount identity, required database, file state, encryption recipient, dump
validation or writer restart fails, investigate the sanitized reason and preserve
the last good group. Do not change credentials, delete backups, or substitute
historical migration artifacts to make readiness green.

## Declarative configuration and validation

Backup targets, container identities, credential source contracts, paths,
schedule references, retention, freshness, recovery prerequisites and group
names are declared in `environments/dev.yml` under
`backups_configuration`. Verification expectations and representative queries
are in `recovery/backup-policy.yml`. Both have JSON Schema validation; the
coverage check rejects missing targets, duplicate identities and mismatched
producer/verifier origin, destination or freshness. Duplicate YAML keys fail.
Adding a supported target changes YAML and its verification coverage policy;
it requires no adapter code change.

Ansible renders protected runtime JSON from canonical YAML, installs its schema,
and validates it before replacing configuration. The producer also validates
before destination writes or service interruption. Runtime JSON is a deployment
artifact, never a separate configuration authority. No deprecated JSON source
configuration is consulted. Run:

```sh
uv run --frozen python scripts/validate-backups.py environments/dev.yml
```

Retention counts are declarative planning policy; destructive pruning is
schema-forbidden. The current writer-quiescence default remains false. Local
schema/test success does not authorize rollout or establish operational recovery.

Missing or unreadable artifacts are unavailable evidence. Empty, corrupt, stale
or incomplete groups are failed evidence. Both prevent readiness; only successful
isolated restoration establishes restore evidence.
