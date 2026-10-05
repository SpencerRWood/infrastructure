# Rollback exercise preparation

This runbook prepares an attended exercise of the OP-480 rollback endpoint.
It is not evidence that a recovery drill ran. OpenProject Story #498 owns the
isolated end-to-end recovery drill, following #497; consumer onboarding is #495.
Do not duplicate their orchestration in automerge-repair or reopen #480.

## Consumer boundaries

| Repository | Environment | Deployment serialization | Protected state | Privileged wrapper |
| --- | --- | --- | --- | --- |
| infrastructure | infrastructure-dev | deploy-infrastructure-dev | /var/lib/github-actions-deployments/github-runner-infrastructure/infrastructure-dev.json | /usr/local/sbin/github-runner-infrastructure-deploy |
| homelab | homelab | deploy-homelab | /var/lib/github-actions-deployments/github-runner-homelab/homelab.json | /usr/local/sbin/github-runner-homelab-deploy |

Read `rollback.toml` and the [contract](rollback-contract.md) from the exact
consumer revision being exercised. Never substitute API history for protected
state or modify a live runner's failure metadata to make the endpoint run.
A successful deployment without a confirmed failed attempt should produce
`blocked` / `stale_or_unconfirmed_failure`; that negative check does not prove
recovery. Preview also takes the consumer's local lock and requires normal
workflow serialization even though it does not apply configuration.

The existing `rollback.yml` selects the live dedicated consumer runner. It has no
isolated-target input. Do not dispatch it to perform this isolated drill or give
a temporary runner labels shared with a live runner. Onboarding must provide a
consumer-owned isolated runner/workflow, or an attended CLI invocation on the
disposable host with equivalent deployment serialization and trusted inputs.

## Required exercise proposal

Before provisioning or changing a target, record and obtain approval for:

1. A disposable Linux provider, host identity, ownership, expiry, and cleanup
   procedure. The target must be isolated from live runners, data volumes,
   production networks, public DNS, scheduled jobs, and production credentials.
   Provider access and an isolated inventory must exist before calling the plan
   executable. Neither repository currently declares an approved ephemeral
   provider; report that capability as unavailable until onboarding supplies it.
2. The consumer commit, immutable failed and previous-known-good release tags,
   their resolved SHAs, the authoritative health-check revision, and target
   environment. Verify distinct commits and ancestry before creating the incident.
   Refresh these values at execution time; current release numbers are not
   permanent drill inputs.
3. Normal bootstrap, runner and root-owned wrapper installation, standard secret
   resolution using drill-only credentials, and normal deployment to the isolated
   inventory. Keep repository-specific bootstrap and recovery in this consumer.
   Environment labels alone are insufficient isolation: confirm the protected
   inventory, secrets, state path, and privileged wrapper all address this host.
4. The representative workload set, fixture/backup identifier and timestamp,
   restore procedure, deterministic application assertions, and expected recovery
   duration. Require at least Caddy in homelab; exercise every workload claimed
   recovered. Infrastructure checks must use the explicitly deployed dev services.
   Do not count skipped or undeployed services as restored workloads.
5. A reversible, configuration-only failure after a successful known-good deploy.
   Exclude schema migrations, irreversible data changes, and external side effects.
   Create the incident through the normal isolated deployment path, which records
   the real failed attempt. Never forge production state to bypass prerequisites.
6. An operator, approved time window, bounded timeouts, retained evidence path,
   abort conditions, and an attended recovery route if the contract fails. A failed
   or interrupted attempt requires investigation; do not clear its marker and retry
   automatically. Keep normal deployment and rollback mutually exclusive.

## Execution and evidence

1. Record UTC start time, provider/host identity, repository/contract revisions,
   selected tags/SHAs, environment, and sanitized protected-state fields. Record
   bootstrap, secret resolution, representative restore, and workload start
   results separately. Do not retain resolved secrets or production data in logs.
2. Establish a healthy known-good deployment on the disposable target and record
   its state. Introduce the approved failed configuration through normal deployment.
   Check the actual protected state's failed tag, failure status, and known-good
   target. If legacy automatic recovery already ran, preserve its evidence: the
   endpoint should verify `already_restored`, rather than apply a second time.
3. On the isolated target, run `python3 scripts/rollback.py --environment <environment>
   --failed-target <failed-tag> --json` from its clean trusted consumer checkout,
   without `--apply`, under equivalent deployment serialization. If an approved
   isolated workflow exists, retain its exact run ID/attempt and JSON artifact;
   otherwise retain the CLI result and operation log. Continue only for `ready`
   with the expected tags and SHAs.
4. Invoke the same isolated CLI with `--apply` only on the approved target.
   Retain complete operation logs and validate the result against
   [rollback-result.schema.json](rollback-result.schema.json). Require both
   `status=succeeded` and `verification_result=passed`. Check the original checkout
   was restored, unrelated state survived, and the original failed attempt remains.
5. Observe actual running workloads and representative application/data assertions
   independently of the rollback result. Bind the observation to recovered revision,
   environment, time, and authority. Deployment-job success and contract health
   alone do not fill Wood's independent runtime-verification evidence field.
6. Repeat the same incident once and verify `already_restored`, fresh health, and
   no second apply. Distinguish this from a full apply: a drill in which legacy
   recovery already restored the target has exercised verification, not the new
   endpoint's check/apply path. A separate approved scenario is needed to prove it.
7. Record end time and recovery duration; retain the restore-point timestamp for
   freshness/RPO evaluation. Destroy temporary hosts, containers, volumes,
   credentials, restored fixtures, and provider resources. Verify cleanup and
   report cleanup failure separately from recovery success.

Any bootstrap, dependency, restore, workload, or cleanup failure is visible in
its own stage. Unsupported ephemeral targets report the strongest tier actually
performed and the missing capability. Local tests with simulated operations are
contract validation, not an isolated rebuild or a live recovery result.

## Delivery applicability and remaining work

The release contract declares container-image and infrastructure-promotion
artifacts inapplicable because this repository applies versioned configuration
with Ansible. Deployed revision and independent runtime verification still apply.
The declaration takes effect for merges containing it; it does not waive earlier
Story requirements retroactively.

No `[tool.wood.verify]` contract or revision-bound runtime attestation is supplied
by this runbook. Those checks need consumer-owned application semantics and an
approved target. Follow #495/#497/#498 to establish and exercise them. Until then,
report runtime verification and an end-to-end drill as unavailable, even when
repository validation and release deployment health checks pass.
