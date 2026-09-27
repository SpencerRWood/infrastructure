# Codex usage-window schedule (dev)

The infrastructure Dagster daemon and `infrastructure_codex_usage` code
location both run on Beelink. The code location is the
`dagster-codex-usage` Compose service on the private Postgres and outbound
proxy networks, at
internal port `4002`. It runs as the Beelink user `spencerwood` (UID 1000),
using that user's standalone Codex CLI and two independently authenticated
profiles at `/home/spencerwood/.codex` and
`/home/spencerwood/.codex-secondary`. The existing synthetic website Mac
location on port `4000` is separate and remains in the workspace.

The schedule runs every day at `06:00`, `11:05`, and `16:10` in
`America/New_York`. Dagster uses those wall-clock times across daylight-saving
changes. Each run requests a short `OK` reply from each profile in ephemeral,
read-only mode, with no repository work. CLI output is sent to `/dev/null`.
The job reports each target's scheduled and actual execution times, duration,
status, and a bounded diagnostic that excludes CLI output and credentials.

Before starting a target, the adapter atomically creates a marker in
`/srv/infrastructure/state/dagster/codex-usage/` on Beelink. The marker is
keyed by Eastern scheduled slot and target. A retry or second run for the same
slot skips that target. Markers remain claimed on failure or timeout, since a
failed process may have already reached the service. An interruption after
claiming a slot may miss an activation and requires investigation rather than
automatic replay.

## Deployment and authentication

The normal dev Ansible deployment builds and starts the code server alongside
Dagster. It mounts the two Beelink profile directories into the code server;
credentials stay in those protected host directories and are never placed in
the repository, Compose environment, or Dagster logs. The standalone CLI is
the executable under the primary profile's `packages/standalone/current/bin`.
The snap-installed CLI is not used because its confinement cannot read the
profile configuration.

Before deploying, verify each profile on Beelink without printing credentials:

```sh
for profile in "$HOME/.codex" "$HOME/.codex-secondary"; do
  CODEX_HOME="$profile" "$HOME/.local/bin/codex" login status
done
```

If a profile needs interactive authentication, sign in on Beelink as
`spencerwood` with `CODEX_HOME` set to the profile directory before deploying.
Do not copy a Mac credential or substitute an API key.

## Manual verification

Use a past, unused schedule slot in a manual Dagster run configuration so the
smoke test cannot consume a future slot. Run `codex_usage_window` in the
`infrastructure_codex_usage` location. Check separate Codex and Codex2 events,
then repeat with the same slot and verify both targets are skipped. For example:

```yaml
ops:
  activate_codex_targets:
    config:
      scheduled_at: '2026-09-26T06:00:00-04:00'
```

Choose a different past slot if that example has already been used. The
schedule is enabled by default when the code location is first loaded.
