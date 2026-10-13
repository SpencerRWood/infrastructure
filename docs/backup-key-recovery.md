# Backup encryption and recovery

The producer's canonical YAML has `encryption_recipient` (a dedicated age X25519
public recipient) and `independent_custody_verified`. The initial recipient is
`age1544rwqert2c0u5wks57lcgfw6saymcfmc7slhdr58js69w3m7d4st3la33`.
Each environment may use a different recipient, with the same value in its
`recovery/backup-policy.yml`. SSH recipients and private values are rejected.
The producer probes the age runtime before pausing writers and refuses to run
unless independent custody is verified or temporary operator custody is explicitly
authorized. Set the independent custody flag only after an
authorized independently recoverable destination passes a decryption check.

The user explicitly accepts temporary operator-held custody on the FileVault-enabled
MacBook for initial encrypted operations. The existing identity remains mode 0600;
its recipient and disposable encryption/decryption roundtrip are verified. Set
`temporary_operator_custody_authorized: true` only for this approved operational
exception. Keep `independent_custody_verified: false`: manifests record both facts
and never attest full disaster-recovery readiness. Independent encrypted USB
custody and recovery testing remain a separately tracked follow-up requirement:
[OP-543](https://projects.woodhost.cloud/work_packages/543).
This producer policy does not authorize key transfers or relax restore protections.

Initial independent custody is pending. A protected local identity was generated with
age-keygen on the operator machine, outside Beelink and Infisical. This local
file is not yet verified independent recovery custody. No private identity is
committed, documented, logged, sent to Drive or installed on backup services.
Use an existing approved password manager or encrypted offline recovery device;
record its non-secret location and the result of recovery/decryption testing.

The backup producer needs only the public recipient. The authorized verifier
gets a read-only identity at the policy's `decryption_identity_file`, default
`/run/recovery-verification/backup.agekey`, owned by its execution UID with mode
0600. Provision this file through the existing scoped Infisical integration only
after independent custody is verified. Do not put the identity in environment
variables, ordinary service credentials or Ansible output. The producer never
uses this file. Verifier copies and decrypts artifacts inside 0700 temporary
storage, restores only into a private socket-only PostgreSQL cluster, checks
extensions, schema, ownership, integrity and queries, and removes all plaintext.
Missing credentials, decryption failures and cleanup failures prevent success.

For manual recovery, validate the manifest and ciphertext checksum/freshness
first. Decrypt into protected disposable storage with `age --decrypt --identity
<protected-identity-file> --output <temporary-output> <artifact.age>`. Restore
globals before the custom-format database with compatible PostgreSQL, locales
and extensions. Pair files with their declared recovery group. Never test a
restore against a live database. Remove decrypted files after verification.

For rotation, generate a new dedicated identity with 0600 permissions, establish
and verify independent custody, then change producer and consumer YAML together.
Run encryption/decryption and isolated restore tests before activation. Retain
old private identities in approved custody for all retained old artifacts; use
the matching public-recipient policy when testing historical groups. Do not
delete old keys or re-encrypt/delete historical backups during initial rollout.

Nightly schedules and 14 daily / 8 weekly / 12 monthly planning retention are
described in `recovery-backups.md`. Pruning is disabled. Failures preserve the last
valid current pointer with its original age. Inspect protected last-attempt JSON
for failures and treat any writer restart/health failure as critical. Confirm
all writers are healthy before further backup work. Successful checksums or
Ansible installation alone do not establish restored application recovery.
