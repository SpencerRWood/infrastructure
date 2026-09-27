# Codex usage-window schedule (dev)

The infrastructure Dagster daemon on Beelink owns the schedule. Its
`infrastructure_codex_usage` gRPC code location runs on the development Mac at
port `4001`, beside the existing synthetic website location on port `4000`.
This placement is necessary because the Mac has both authenticated Codex CLI
profiles. Beelink currently has only one Codex profile. The Mac's `codex1`
and `codex2` shell functions select `~/.codex` and `~/.codex-secondary`;
the code location makes that same selection directly with `CODEX_HOME` and
uses the observed `~/.local/bin/codex` binary. No token is copied to Dagster.

The schedule runs every day at `06:00`, `11:05`, and `16:10` in
`America/New_York`. Dagster uses those wall-clock times across daylight-saving
changes. Each run requests a short `OK` reply from each profile in ephemeral,
read-only mode, with no repository work. CLI output is sent to `/dev/null`.
The job reports each target's scheduled and actual execution times, duration,
status, and a bounded diagnostic that excludes CLI output and credentials.

Before starting a target, the adapter atomically creates a marker under
`~/.local/state/wood/infrastructure/codex-usage/`. The marker is keyed by
Eastern scheduled slot and target. A retry or second run for the same slot
skips that target. Markers remain claimed on failure or timeout, since a
failed process may have already reached the service. This gives at-most-once
attempts; an interruption after claiming a slot may miss an activation and
requires investigation rather than automatic replay.

## Mac deployment

The code location uses the repository's existing protected
`~/.config/wood/infrastructure/dev.env` input, specifically
`DAGSTER_POSTGRES_PASSWORD`, and the existing Mac Dagster instance config at
`~/.dagster/dagster.yaml`. The launcher constructs the Dagster database URL
and the component variables required by remotely launched runs for the
published dev Postgres endpoint in memory. The environment file must
be mode `0600`. Codex authentication remains in each profile's existing home.

From this repository checkout on the Mac:

```sh
UV_PROJECT_ENVIRONMENT=.venv-codex-usage uv sync --group dev --python /opt/homebrew/bin/python3.14
bash scripts/install-codex-usage-dagster
```

The installer creates a boot-time LaunchDaemon that runs as the invoking user,
keeps the machine awake while on AC power, and restarts the code location if it
exits. The installer needs administrator authorization for `/Library/LaunchDaemons`.
If administrator authorization is unavailable, run
`bash scripts/install-codex-usage-dagster-agent` for a login-only service.
The login agent starts after this user signs in and does not cover a reboot
before login.
Check `launchctl print system/com.wood.infrastructure-codex-usage-dagster`
and `~/Library/Logs/infrastructure-codex-usage-dagster-error.log` if it fails.
The Beelink Dagster workspace already uses `MACBOOK_DAGSTER_HOST` for the
existing Mac code location and adds this one on port `4001`; deploy the dev
Dagster component after the Mac service is healthy. Production is not enabled.

When updating the code location, update this Mac checkout and restart the
LaunchDaemon. The Beelink release runner does not deploy Mac code.

## Manual verification

Use a past, unused schedule slot in a manual Dagster run configuration so the
smoke test cannot consume a future slot. Run the `codex_usage_window` job in
the `infrastructure_codex_usage` location and verify separate Codex and Codex2
events. Repeat with the same slot to verify both are skipped. A manual run
should use this configuration shape:

```yaml
ops:
  activate_codex_targets:
    config:
      scheduled_at: '2026-09-26T06:00:00-04:00'
```

Choose a different past slot if that example has already been used. The
schedule is enabled by default when the code location is first loaded.
