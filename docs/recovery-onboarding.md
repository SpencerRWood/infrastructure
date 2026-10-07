# Recovery consumer v1 (OP-495)

This repository owns portable development infrastructure. Recovery Verification owns
generic orchestration and evaluates this repository's declarations; it contains
none of our Ansible, storage, Compose, rollback or restore implementation.

## Versioned manifest

`recovery/consumer.v1.json` is the version-controlled manifest recipe.
Its `target` contains the v1 wire fields except `revision`; the exporter adds
the exact current Git revision. This avoids a self-referential commit hash.
Operational export requires a clean checkout at the repository root and the
matching GitHub origin. Unknown schema versions and supplied revision overrides
are rejected; the provider's strict v1 parser validates the exported wire manifest.

```sh
python3 scripts/recovery.py manifest > /tmp/infrastructure-recovery.v1.json
python3 scripts/recovery.py preflight
python3 scripts/recovery.py bootstrap
```

Only the first command exports a manifest. Preflight prints sanitized JSON with
`schema_version`, `mode`, `readiness_state` and unique `checks` of
`id/state/reason`. It checks consumer entrypoint/runbook existence, then runs the
normal Ansible inventory parser and playbook syntax check. These commands do not
connect to the host, mount storage, load runtime credentials, or execute restore
operations. Raw command output is discarded and application environment values
are not inherited. Each external command has a 60-second timeout and no retry.

Exit codes: 1 for failed local checks, 2 for unsafe/invalid input, 3 for a bootstrap
plan which has not executed, and 4 for unavailable prerequisites. Manifest export
exits 0. A zero manifest export result attests only to export, never recoverability.

## Recovery paths and limits

Bootstrap emits the exact normal deployment playbook/inventory in a machine-readable
plan and exits 3 with `isolated_recovery_test_required`. It does not provide an
alternate provisioning implementation or an apply flag. Ansible check mode is
deliberately excluded: some existing tasks can execute even in check mode.
A blank-host apply needs a separately reviewed isolated target, bootstrap inputs,
network/storage isolation and cleanup contract before stronger levels are enabled.

The manifest's recovery entrypoint is the existing `scripts/rollback.py`, directly.
The caller must supply its mandatory `--failed-target vX.Y.Z`; there is no guessed
release or invented failure evidence. Preview is the default. Operational use
must follow the [rollback contract](rollback-contract.md), including the protected
runner state, privilege boundary and deployment serialization. This endpoint can
restore previous-known-good configuration. It does not restore a database,
bootstrap missing secrets, or prove recovery after host loss.

The existing health commands remain domain-owned; their source is referenced by
the contract/runbooks. Host health and application usability checks are not
executed by this onboarding preflight. Only `readiness` is currently declared;
`verification` and `drill` fail closed in the provider's capability selector.
No live recovery, storage mutation, deployment or production operation was run.

## Dependency scope

The recipe declares Git ownership, deployment artifact sources, Infisical names
and paths, storage/mount prerequisites, known backup locations, expected service/
endpoint sources, tools and runbooks. `repo://path#section` refers to an authoritative
file in the exact exported checkout, not a second inventory. In particular, service
selection, image pins, required secret keys and ingress routes stay with their
existing Ansible/Compose declarations. `path:///` and `mount:///` are storage
references; `infisical://` references names/scopes and never credential values.

Image source declarations do not prove that image tags are immutable or available.
Known migration backups are retained recovery inputs, not evidence of a recurring
current backup policy. The initial `max_age_seconds = 86400` is a conservative
one-day freshness requirement, not an assertion that those historical artifacts
meet it. Later readiness work must report stale/missing inputs explicitly and
resolve the current authoritative backup policy; no archive is silently treated
as the latest backup.

External secrets, artifact retrievability, mount access, backup freshness/integrity,
and isolation are not probed by this Story. Preflight retains an explicit
`external_prerequisites: unavailable` check, so successful syntax never produces
a passed recovery-readiness result. Live prerequisite probes belong to #496;
isolated verification and drills belong to #497/#498.

## Tests

The declared repository validation includes `tests/test_recovery.py`. Its Git
commits are disposable fixtures only. Tests cover revision/owner binding, dirty
checkouts, absent/symlinked interfaces, safe default bootstrap, sanitized output,
environment exclusion, timeouts and unavailable dependencies. Recovery Verification
also keeps wire fixtures and a generic invocation test; its cross-consumer checker
copies only Git source inputs into temporary snapshots and exercises both real
consumer interfaces without loading ignored credential files.
