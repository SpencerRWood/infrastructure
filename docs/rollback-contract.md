# Previous-known-good rollback contract v1 (OP-480)

Infrastructure and homelab expose the same `scripts/rollback.py` CLI and
`.github/workflows/rollback.yml` endpoint. The result schema is
[rollback-result.schema.json](rollback-result.schema.json). Repo-specific identity,
environment, deployment state, privileged entrypoint, and policy live in
`rollback.toml` in each consumer. No rollback implementation or exceptions belong
in automerge-repair. Its current notification-only policy remains unchanged.

## Invocation

Dispatch `rollback.yml` in either repository with identical input names:
`environment`, `failed_target` (an immutable `vX.Y.Z` release tag), and `apply`
(boolean, default false). Use `infrastructure-dev` for infrastructure and `homelab`
for homelab. The reusable workflow accepts the same inputs and exposes `result`.
Every completed CLI invocation prints one JSON object on stdout; operation logs
go to stderr. The workflow retains `rollback-result.json` as the `rollback-result`
artifact, including blocked and failed results. Always inspect that JSON, not
only job success. Preview `ready` is not a completed rollback.

From a clean, trusted runner checkout, the equivalent CLI is:

```sh
python3 scripts/rollback.py --environment infrastructure-dev \
  --failed-target v0.20.2 --json
# Add --apply to execute; use environment homelab in the homelab repository.
```

Use the workflow for operational calls. It checks out the authoritative `main`
contract, runs on the isolated consumer runner, and serializes with normal
deployment via the existing `deploy-infrastructure-dev` or `deploy-homelab`
concurrency group. CLI callers must provide equivalent deployment serialization;
the additional local lock only serializes contract clients. Production is
unsupported. This Story implements no orchestration, notifications, repair,
promotion, database restoration, or incident provenance correlation.

## Selection and execution

The existing protected runner-local deployment state is the sole known-good
authority. `deployment_target` must match the configured environment;
`last_attempt_release` must match the failed tag and `last_attempt_state` must be
`failure`. A newer successful or unrelated failed deployment blocks a stale
request. Missing/corrupt state, policy, tags, wrong repository, dirty checkout,
unsupported environment, and concurrent clients all fail closed before apply.
There is no guessed latest release, operator tag override, or API-history fallback.

Select `current_release` (the last successfully applied and health-checked tag).
If that is the failed tag itself (a failed redeploy), select
`previous_successful_release`. Resolve full tag names to commit SHAs. The selected
commit must differ from and be an ancestor of the failed commit. Branches, aliases
of the failed commit, unrelated release lines, and absent known-good targets are
blocked. This relies on the existing immutable release-tag policy and trusted
runner state; legacy deployment metadata does not attest to image digests or
database compatibility. Selection does not prove a database/schema downgrade safe.

With consumer policy `enabled` or `required` and `--apply`, persist an incomplete
attempt first, check out the pinned known-good commit, and invoke the existing
root-owned wrapper's `check`, `apply`, and `health` operations once each.
Check/apply use the selected commit; health uses the authoritative contract
checkout so an older tag cannot silently weaken verification. The health gates
check the restored runtime using its protected deployed environment inputs.
Both modes execute identically; `required` tells the caller that unavailable or
failed rollback must stop its incident. `notification_only` never executes.
Absent or unknown policy blocks. The normal runner-local secret resolution and
privilege boundaries remain authoritative. Each operation has a bounded timeout.

If existing automatic deployment recovery already restored the selected release,
or this contract previously succeeded for the same targets, only re-run health.
Return `already_restored` plus fresh verification. A failed or interrupted contract
attempt cannot automatically apply again. Conflicting saved target evidence blocks.
An operator must investigate and reconcile state before another attempt.

Restore the original Git checkout afterward, preserving the actual recovered host
configuration. Atomically retain the result in `rollback_contract` alongside the
existing `rollback_release`/`rollback_state`. Preserve the original failed attempt
and unrelated deployment metadata. A write/checkout-restore failure is a failed
operation even if host health passed. Never infer success solely from apply.

## Results

All results include repository/environment, failed target, previous known-good
target (null when unavailable), policy, observation time, reason, execution
outcome, and verification result. Targets include tag and resolved commit SHA.

| Status | Execution / verification | Exit | Meaning |
| --- | --- | --- | --- |
| `ready` | `not_attempted` / `not_run` | 0 | Preview selected a safe target |
| `notification_only` | `not_attempted` / `not_run` | 3 | Policy prevents execution |
| `blocked` | `not_attempted` / `not_run` | 3 | Prerequisite absent or unsafe |
| `failed` | Individual stage outcomes | 1 | Check/apply/health/evidence failed |
| `succeeded` | `succeeded` or `already_restored` / `passed` | 0 | Recovery verified |

Only `status=succeeded` **and** `verification_result=passed` attest to recovery.
Invalid CLI syntax exits 2 before creating a result; use the documented inputs.

## Audit of existing recovery (2026-10-05)

Audited current `origin/main` at infrastructure `ab6619a` and homelab `c0166cb`,
plus the shared `deploy-ansible.yml@v1` implementation in the workflows checkout.
Both consumers call the same release resolver/deployment workflow, with separate
runner labels, protected inputs, environment metadata, and concurrency groups.
The shared deployment workflow checks release tags, validates, applies, checks
health, and reapplies the previously successful release once on apply/health
failure. It records runner-local `current_release`, `previous_successful_release`,
the failed attempt, and rollback state. It does not blindly restore databases.

Gaps: previous selection mixes local state, optional override, and GitHub history;
an absent target skips rollback without a rollback result; output is shell text
and step outcomes rather than a complete versioned result. A consumer caller
cannot distinguish execution from verification using that interface alone.
The new endpoint closes these gaps for remediation consumption and can normalize
and verify an already completed automatic recovery. Normal release deployment
continues through the existing shared workflow; automerge-repair must consume
this endpoint, not infer recovery from legacy step outcomes.

Infrastructure's `rollback-infrastructure-infisical-service` and homelab's
`rollback-infisical-service`/`rollback-mealie-infisical` restore retained migration
Compose/secret sources. Storage/media/database migration runbooks also contain
attended recovery procedures. These sources are not attested release targets and
are deliberately excluded from the common release rollback contract.

Health differs by consumer: infrastructure validates explicitly selected dev
services and readiness; homelab checks migrated containers while allowing staged
services to be absent. Consumer health commands stay behind the contract. The
homelab readiness check must require its deployed Caddy baseline and reject
non-running, starting/unhealthy, and unavailable Docker inspection states.

Tests in each repository cover real Git/tag selection, missing/stale/unsafe
evidence, policy modes, preview, failure stages, atomic state preservation,
duplicate recovery, interrupted attempts, and concurrent clients. No live rollback
is executed by development validation. Requirement coverage: FR-005/006/026 and
QR-005/007/010 for this prerequisite only; subsequent incident orchestration and
repair tests belong to their own Stories.

See [rollback exercise preparation](rollback-exercise.md) for isolated target
prerequisites, approval inputs, execution evidence, and the remaining runtime
verification gap. That runbook does not attest to an executed recovery drill.
