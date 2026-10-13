# OP-500 provider-independent monthly preparation

The existing generic Recovery Verification lifecycle SDK owns ordered execution,
fail-stop behavior and independent provider cleanup. The current consumer
declarations remain unsupported. No unit test or successful weekly restore can
enable them or attest to a completed monthly bootstrap.

scripts/monthly_bootstrap.py now implements current-group/source preparation,
strict copied/transported artifact verification, VM ownership/expiry checks,
offline image loading, protected guest-only credentials, PostgreSQL globals and
all databases, archives, MongoDB restoration/validation, Redis loading/query,
strict guest-local Compose execution, health/query checks and bounded cleanup.
It rejects live-controller execution, shared/NAS filesystems, default routes,
host networking, host ports, socket mounts, privileged services, missing resource
limits and incomplete phase proofs. Required service sets are declared in each
consumer's recovery/monthly-workloads.v1.json; production background workers are
excluded. These are disabled execution helpers, not a complete installed backend.

scripts/stage-recovery-transport.py binds a newly owned transport directory to
the SDK resource ID, clean source revision and current group manifest. The
original private age identity stays at its existing protected controller path.
The guest generates an ephemeral identity and returns only its public recipient.
Controller age-decrypt/age-encrypt streams produce no plaintext controller files
and send no original private key. Transport evidence binds original ciphertext,
plaintext and guest ciphertext identities. Guest decryption must use its own
recipient, explicitly different from the original DR recipient.

Provider-specific work remains blocked on the exact approved VM/template:
QEMU launcher/virtio-channel and independent lease-reaper bindings; offline Linux
packages and architecture; exact guest workload recipes; numeric file ownership,
locale/extension and storage bindings; and drill-only runtime credentials. The
recipe fields stay null until that binding is reviewed. Do not invoke normal host
roles against an invented inventory or relabel preparation as full capability.

Proposed execution is one offline amd64 VM on the Mac, 4vCPU/16GiB/100GiB and
120-minute maximum lifetime, sequential consumers and no bridged/user network,
host folders, host Docker socket or forwarded ports. QEMU is not installed or
approved. Admit only after reserving memory and at least40GiB disk beyond staged
inputs and the maximum guest disk. Do not use the capacity-constrained live
Beelink. Cost is local resources/time, with no cloud charge. Operator/provider
approval must include bounded VM creation, ephemeral credential handling and
destruction of only owned VM/disk/state resources, including partial provisioning.

Before any execution, recheck source, group freshness, independent image exports,
credential availability and recovery operation concurrency. After approval bind
the SDK to the selected backend, test failure/expiry/destruction, then prove actual
blank-host bootstrap and all required phases. Only afterward review capability
declaration changes and the production monthly rollout. Retain durable sanitized
evidence and preserve OP-542/OP-543/OP-544 histories and live automation.
