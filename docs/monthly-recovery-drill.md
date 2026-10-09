# Monthly recovery capability (OP-498)

The consumer manifest explicitly declares ephemeral rebuild unsupported, with
reason `isolated_bootstrap_not_supported`. Bootstrap currently returns a plan;
the recovery/storage/runtime contracts require an existing managed host. No
isolated Linux provider has been approved for a complete rebuild.

The generic `recovery_drill_monthly` job uses the same target contract and runs
this consumer's executable weekly verification as its strongest supported tier.
It retains representative restore and cleanup evidence and reports the missing
monthly capability. Successful weekly verification does not establish full-drill
success. Monthly readiness remains UNKNOWN unless another required check fails,
in which case it is NOT_READY.

Enabling support requires a reviewed disposable Linux provider, normal bootstrap
and recovery execution entirely inside that environment, runtime secret resolution,
representative backup timestamps and hashes, deterministic workload validation,
and destruction of every temporary resource and credential after success or
failure. Production inventories, storage and destructive modes are outside this
interface. The consumer must then declare the approved provider/environment and
a drill validation command with complete phase evidence.

Until those capabilities exist, retain the explicit unsupported declaration.
The provider repository's `docs/monthly-drill.md` defines the wire contract and
optional lifecycle SDK. Existing weekly verification behavior remains the scope
documented in `docs/weekly-recovery-verification.md`.
