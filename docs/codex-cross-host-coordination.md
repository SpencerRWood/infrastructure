# Scoped development usage coordination

S07's MacBook runner shares the primary server Codex account. Inspection on
October 29 found that the live usage container retained an older adapter without
the shared-file lock, despite the reviewed repository source having that lock.
Independent local MacBook and Linux locks do not serialize those processes.

`ansible/playbooks/codex-usage-coordination.yml` deploys only the reviewed
`codex_usage.py` into the existing development usage container as a read-only
mount. It preserves its observed immutable image, schedules, profiles, state
directory, service name and network configuration. It builds/pulls no image and
reconciles no other service or dependency. The existing schedule remains unchanged.
This is an explicitly approved runtime operation, separate from source delivery.

After source review/merge, use the normal infrastructure Ansible environment and
dev inventory. Require `infrastructure_environment=dev`,
`codex_coordination_apply=true`, a non-secret approval reference, and
`codex_coordination_expected_image` set to the freshly observed image ID. The
October 29 observation was
`sha256:bf20607ff39cdcc97f326bb8cfb19e8bd0ff0473014836097508bda8e65f4802`.
Do not replace a changed image observation with that historical value. Verify no
usage target is currently running and retain container/mount/state/schedule
observations before applying. Apply during an idle interval, away from schedule
ticks; no live inference is needed to verify the adapter or lock.

The MacBook trusted supervisor makes a fixed outbound SSH request using the
existing dedicated server identity and strict host-key checking. That operation
executes only a fixed Docker/Python lease protocol in the existing usage container
as UID/GID 1000. It verifies the exact reviewed adapter hash before acquiring the
same lock inode used by the usage job. It forwards no prompt, queue command or
application credential. The model cannot execute SSH or read the SSH identity.
There is no incoming MacBook listener or second generation schedule.

Verify the source hash, active code location health and unchanged schedule. Hold
the supervisor lease and test nonblocking contention against the container's
same state file; release and verify acquisition succeeds again. Disconnect/death
must release the lease, and missing/mismatched code or lost SSH must block the
MacBook inference. File locking coordinates participating processes; it is not a
quota reservation or proof that an interrupted upstream request has stopped.

Rollback uses the same base Compose file and env file with a separate private
rollback override that sets only this service's image to the saved immutable image
ID and `pull_policy: never`, without the adapter mount. Exclude the coordination
override from that command. Reconcile only `dagster-codex-usage` with
`--no-deps --no-build --pull never --wait`; verify the original image is still
locally present first. Do not rely on a mutable base image tag. Keep the MacBook runner
disabled during rollback because the old adapter does not coordinate its account.
Do not remove lock/state/slot markers or reset prior usage claims. Retain the
override and immutable adapter for recovery. A future normal Dagster release must
explicitly reconcile this temporary reviewed override and reverify coordination.
