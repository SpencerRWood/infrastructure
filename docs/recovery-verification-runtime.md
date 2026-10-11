# Recovery Verification code location (OP-500)

The optional `recovery_verification` role deploys an independently versioned,
digest-qualified `ghcr.io/spencerrwood/recovery-verification:vX.Y.Z@sha256:...`
release through the existing explicitly authorized infrastructure deployment
path. It does not build or publish the provider. Both environment selectors are
false; adding the component never activates it or production schedules.

Before separate activation approval, supply `recovery_verification_image_ref`
from a verified published artifact and `recovery_verification_config_source` from
the reviewed non-secret provider orchestration configuration. No placeholder
image digest is committed. Existing Dagster/Postgres must already be selected;
the role is dev-control-plane scoped, matching existing code-location conventions.
Production selection is a separate infrastructure decision, not implied by this
component. Keep provider Story integration on release/v0.6.0 and consumers on main.

Runtime inputs are resolved only from `/recovery-verification` by the existing
Infisical resolver into a protected runtime env file. Prepare scoped
`DAGSTER_POSTGRES_PASSWORD`, metadata-only `RECOVERY_INFISICAL_URL`,
`RECOVERY_INFISICAL_PROJECTS`, `RECOVERY_INFISICAL_TOKEN`, and, only after live alert
approval, source-bound `RECOVERY_EVENTS_URL`/`RECOVERY_EVENTS_TOKEN`. The selected
role registers this service with the existing secret-refresh contract after the
other components; disabled selection does not alter that runtime registry.
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
