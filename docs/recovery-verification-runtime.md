# Recovery Verification code location (OP-500)

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
`RECOVERY_INFISICAL_PROJECTS`, `RECOVERY_INFISICAL_TOKEN`, and, only after live alert
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
