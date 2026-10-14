# Offline QEMU recovery provider preparation

OP-500 authorizes one offline amd64 QEMU VM on the 32 GiB Mac, adaptive resources,
a 120-minute total exercise budget, sequential consumers and no cloud expenditure.
Every profile has no NIC, host/NAS folders, host Docker socket,
host monitor, forwarded ports or production credentials/notifications/workers.
The existing generic Recovery Verification SDK remains the lifecycle coordinator.

scripts/qemu_recovery_provider.py implements capacity admission, checksum-bound
template/input selection, a single-VM lock, registration before allocation,
copy-on-write owned disks, an offline fixed QEMU argv, a virtio serial-only phase
channel, an independent expiry reaper, PID/resource identity checks, partial
allocation cleanup, durable sanitized evidence and the LinuxProvider SDK adapter.
Snapshots derive from the verified current group manifest/time after actual
guest restore proof; callers cannot supply arbitrary passing snapshot evidence.
Unreconciled resources and reused PIDs prevent another launch or unsafe cleanup.

| Profile | RAM | vCPUs | Initial sparse disk | Purpose |
| --- | --- | --- | --- | --- |
| Small | 2 GiB | 2 | 40 GiB | Linux bootstrap and artifact checks |
| Standard (default) | 4 GiB | 2 | 40 GiB | PostgreSQL and individual applications |
| Large | 8 GiB | 4 | 80 GiB | More demanding measured workloads |
| Full | 16 GiB | 4 | 100 GiB | Full environment when justified |

`scripts/qemu_resources.py` selects the smallest profile at or above the planning
profile satisfying the workload estimate. Small requires explicit selection.
RAM estimates include the guest OS and all services required to operate together.
Unknown estimates fail closed. Configurable disks from 40 through 100 GiB must
cover measured base image, container images, encrypted staging, databases,
application state, temporary extraction, filesystem overhead and cleanup space.
Streaming encrypted inputs avoids duplicate host plaintext.

Admission measures physical and conservative reclaimable RAM, memory pressure,
swap usage/activity, query responsiveness and disk capacity. Inactive/speculative
reclaimable pages are capped at file-backed pages to avoid double counting and
depending on compressed anonymous memory. Normal pressure and no swap-in/out
activity during the sample are mandatory. Guest RAM plus 2 GiB headroom means
6 GiB for Standard. Existing swap usage is recorded, never ignored in favor of
free RAM alone. Warning, critical or unknown pressure rejects launch.
Apple's [sysctl implementation](https://github.com/apple-oss-distributions/xnu/blob/main/bsd/kern/kern_memorystatus_notify.c)
returns dispatch values 1 normal, 2 warning and 4 critical, not the internal enum.

Disk admission reserves full potential sparse growth, at least 40 GiB of host
storage reserve, and staged bundle bytes. Admission is repeated under the exclusive
slot before allocation. Use one private state root for every exercise; another
root must never bypass an occupied slot. The independent reaper samples pressure,
swap activity, responsiveness and reserve every 15 seconds; unsafe or unavailable
monitoring destroys only its registered owned VM. Host and destruction evidence
survive VM removal. No unrelated application or shared service is terminated.

Adaptive attempts retain failure evidence before assessing cleanup. Only observed
OOM events with measured RAM exhaustion or ENOSPC with measured disk exhaustion
permit one-profile escalation. Restore defects, missing measurements, failed
cleanup and unsafe host conditions stop execution. Every retry retains the same
acceptance criteria and uses the remaining shared 120-minute budget. The callback
must execute the actual SDK lifecycle with fresh admission and independent
destruction proof; the helper never skips phases or creates a passing result.

The resource manager is not a complete, verified consumer provider. It requires a
reviewed blank Linux qcow2 template containing offline tools and the sealed phase
agent, a checksum-bound read-only offline input disk, and an explicit prepare_guest
bridge. That bridge must obtain only the guest's ephemeral public recipient,
stage approved decrypt/re-encrypt transport for the SDK-assigned resource ID,
verify transfer hashes, and return the bound inputs/programs. The original
private recovery identity stays in its protected controller location. There is
no inherited token, host restore-role invocation or replacement loader.

Exact workload recipes, offline package/image staging and the guest ready/transfer
bridge remain incomplete. Actual trials must measure peak guest RAM, CPU utilization,
disk consumption, OOM/ENOSPC, duration and every restoration/service result.
Dedicated GHCR credentials remain an external prerequisite. Monthly declarations and capability_verified
remain false. Unit tests prove admission/argv/ownership/expiry/cleanup contracts,
not a Linux bootstrap or application restore.

When normal pressure, adequate workload capacity and scoped credentials are available,
recheck admission and
complete the reviewed template/guest bridge and exact offline recipes under the
existing scope D authorization. Run containment/failure/expiry cleanup tests, then
the two real sequential bootstraps. Retain all phase/restoration/destruction proof
before requesting capability activation or runtime deployment. Full-environment
success requires all essential services and health checks together; individual
restores do not prove it. Preserve schedules, both sensors and Telegram deduplication.
