# Recovery Verification code location (OP-500)

## Reviewed consumer selection

The checked-in orchestration manifest selects infrastructure revision
`68bee36d8a21b9e103cc9d01605e02b2d307253b` and homelab revision
`54d2ed7db82d8296efee2e88a652f9953f479f13`. Both declare the consumer-owned
`current_recovery_group` pointer under the approved recovery NFS namespace.
The producer atomically advances that pointer; no backup group ID is selected
in deployment configuration. Consumer preflight verifies the group inventory,
source timestamps, ciphertext checksums, age recipient and off-source copies.

Before updating active orchestration or resolving secrets, the role runs
`scripts/verify-recovery-consumers.py` as verifier UID 10001. Its reviewed manifest
must exactly match each clean checkout's export, including repository revision,
backup sources, dependency declarations and real-backup weekly arguments.
An old checkout or old manifest fails deployment instead of evaluating migration
fixtures. The verifier never fetches, resets or changes these checkouts.

Checkout advancement is a separate attended deployment operation. Retain the
previous clones and configuration for rollback, inspect active Dagster/backup
operations and acquire the existing recovery operation lock before swapping
reviewed clean clones. Preserve notification activation/cutoff, policy, cadence,
history and sensor state from the current reviewed runtime configuration. The
change sensor can select weekly verification when consumer recovery code changes;
coordinate its cursor with the approved advancement rather than allowing an
unreviewed restore run. Do not fabricate history entries from OP-542 evidence.

The source selection check is a deployment gate, not operational readiness.
OP-543 independent custody and unsupported isolated bootstrap remain unresolved;
weekly fixture evidence does not attest to current production backup restoration.

The optional `recovery_verification` role deploys an independently versioned,
digest-qualified `ghcr.io/spencerrwood/recovery-verification:vX.Y.Z@sha256:...`
release through the existing explicitly authorized infrastructure deployment
path. It does not build or publish the provider. The dev manifest selects the
published v0.6.1 digest and `environments/recovery-verification-dev.json`;
production remains disabled. Deployment does not start schedules or the change
sensor, which remain stopped by default. Live notifications and isolated monthly
test mode are disabled in this configuration.

Before separate activation approval, supply `recovery_verification_image_ref`
from a verified published artifact and `recovery_verification_config_source` from
the reviewed non-secret provider orchestration configuration. No placeholder
image digest is committed. Existing Dagster/Postgres must already be selected;
the role is dev-control-plane scoped, matching existing code-location conventions.
Production selection is a separate infrastructure decision, not implied by this
component. Provider releases follow their approved release branch; consumers
retain their existing trunk targets.

Before deploying this selection, verify that the existing Infisical resolver can
read `DAGSTER_POSTGRES_PASSWORD` from `Infrastructure Dev`, environment `dev`,
path `/recovery-verification`. This must be the canonical shared Dagster database
credential; never generate an independent password or copy credentials into Git.
Prepare independent, clean clones of `SpencerRWood/infrastructure` and
`SpencerRWood/homelab` in the checkout directory below, at reviewed immutable
revisions. The initial exported manifests record infrastructure
`00a42cf569b617d4953f8829dc079435106b231e` and homelab
`40962d7b2fb6bb05da469336bd05549d7175b858`; explicit consumer manifest exports
refresh the actual clean revisions for each run. Advancing these clones is an
attended operation under the shared operation lock.

The configuration declares existing consumer backup references exactly as
exported. Infrastructure state and bootstrap paths outside the mounted NAS are
not visible in this container; readiness must report them unavailable. Missing
or stale backup inputs, metadata credentials and unresolved artifact catalogs
prevent full operational acceptance and must be resolved before enabling cadence.

Runtime inputs are resolved only from `/recovery-verification` by the existing
Infisical resolver into a protected runtime env file. Prepare scoped
`DAGSTER_POSTGRES_PASSWORD`, metadata-only `RECOVERY_INFISICAL_URL`,
`RECOVERY_INFISICAL_PROJECTS`, `RECOVERY_INFISICAL_CLIENT_ID` and
`RECOVERY_INFISICAL_CLIENT_SECRET`, and, only after live alert
approval, source-bound `RECOVERY_EVENTS_URL`/`RECOVERY_EVENTS_TOKEN`. The selected
role registers this service with the existing secret-refresh contract after the
other components; disabled selection does not alter that runtime registry.
The backup decryption identity is provisioned separately through the approved
operator SSH channel, owned by UID/GID 10001 with mode 0600. It is mounted read
only into the verifier and must derive the configured public recipient. Recovery
key custody does not use Infisical or Bitwarden. Explicit temporary operator
custody permits initial verification while independent custody and disaster
recovery readiness remain false. The verifier-only
`ansible/playbooks/dev-recovery-verification.yml` preserves existing orchestration
settings when supplied the reviewed current configuration.

Never put token values in Git, Dagster run config or evidence. The role uses the
existing runner registry credential and changes no publication/deployment trigger.

Prepare clean consumer-owned clones under `/srv/infrastructure/recovery-checkouts`,
reviewed current backup sources and read-only NAS visibility. The container reads
the clones as `/opt/recovery/checkouts` and NAS as `/mnt/wood-server-nas`. Check UID
10001 read access/Git ownership and do not mount host worktree `.git` indirections.
It writes only its durable `/opt/recovery/state`, temporary isolated restore
resources, and shared Dagster local logs through the existing supplementary group
1000. Its root filesystem, source and NAS are read-only; no Docker socket is granted.

The existing workspace template includes `recovery-verification-code:4000` only
when explicitly selected. The role waits for gRPC/registration health before
restarting the existing webserver/daemon. Verify actual code-location load, all
three job/schedule registrations, stopped defaults, writable instance storage and
evidence directories, clock configuration, mounts, source updates and notification
authorization before enabling schedules. Current legacy migration backup paths
and unresolved local/variable image catalogs must be reconciled against real
artifacts; do not change them to invented current backups or fake registry inputs.

For rollback, stop provider schedules/sensor, restore the previous approved image
and configuration via the existing infrastructure release rollback, verify health
and retain execution/archive files. A component/configuration rollback does not
authorize database restore, backup deletion, or competing Dagster daemons.

## Terminal notification rollout (OP-500 follow-up)

The notification integration requires separately published provider and Events
Service artifacts; keep existing digest selections until their exact releases
are verified and approved. No source overlay, additional scheduler or new
Telegram bot is required. The existing role gains explicit notification inputs,
and the queued coordinator gains a limit of one for the existing
`recovery/operation=verification` tag. Other runs retain the global concurrency
default. Provider job defaults supply that tag even for UI launches.

Enable provider notification configuration only with
`recovery_verification_notifications_enabled=true` and an explicit ISO8601
`recovery_verification_notification_start_time` defining the approved terminal
event backlog. The role merges only these notification fields into the reviewed
orchestration JSON; consumer manifests, cron expressions, checkout/state paths,
probe policy and isolated mode are preserved. The required key list is the same
authority for initial resolution and registered refresh. It requires
RECOVERY_EVENTS_URL and RECOVERY_EVENTS_TOKEN in addition to the canonical
Dagster database password when notifications are selected.

Use Infrastructure Dev / dev / `/recovery-verification` for those runtime keys.
The existing private-network broker URL is `http://wood-broker:8000`; no public
event ingestion route is opened. A dedicated token must authorize source
`recovery-verification` with events:write and notifications:read. Register it in
the existing WES_PRODUCER_CREDENTIALS arrays for both broker and notify without
replacing other entries. Keep its value only in Infisical and the protected
existing runtime resolver output. Never use another producer's source token.

Append this entry to the existing WES_NOTIFICATION_POLICIES in the Events Service
Infisical folder, preserving acceptance/workflow policies:

```json
{
  "name": "recovery-scorecards",
  "channels": ["telegram"],
  "sources": ["recovery-verification"],
  "event_types": ["recovery.run-completed"]
}
```

The existing broker-to-notify subscription is reused. The Events Service release
includes migration0004, which adds the durable dispatching state; apply it via
the existing migration lifecycle before starting the new notify image. It does
not alter historical messages or unrelated delivery policy. A downgrade must
first reconcile outstanding dispatching rows; it refuses to silently resend or
delete them. A timeout/server/transport ambiguity is retained for reconciliation,
not automatically resent. A normal delivered message has its Telegram message
ID and delivery attempt retained. Broker acknowledgment alone is insufficient.

After reviewed exact-digest deployment, enable `recovery_run_notifications`
through Dagster controls first. Submit one approved non-destructive readiness
run and inspect its one consolidated message, both backup/recovery statuses,
failure/prerequisite details, evidence link, broker receipt and Telegram receipt.
Re-submit the same frozen event to verify receipt.duplicate=true and no second
Telegram message. Only then enable the existing recovery schedules/change sensor
and read back RUNNING/next ticks. Do not run a destructive monthly drill to test
scheduling. Existing NOT_READY and unsupported recovery capabilities remain
visible limitations, and OP-543 key custody remains independent.
