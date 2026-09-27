"""Beelink-hosted Codex activity location for the infrastructure Dagster instance."""

from __future__ import annotations

import time
import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dagster import DefaultScheduleStatus, Definitions, RunRequest, job, op, schedule

from codex_usage import TARGETS, PingResult, ping_target

TIMEZONE = "America/New_York"
CRON_SCHEDULE = ["0 6 * * *", "5 11 * * *", "10 16 * * *"]


def run_targets(scheduled_at: str, log) -> None:
    home = Path(os.environ.get("CODEX_USAGE_HOME", str(Path.home())))
    state_dir = Path(os.environ.get("CODEX_USAGE_STATE_DIR", str(home / ".local/state/wood/infrastructure/codex-usage")))
    executable = Path(os.environ.get("CODEX_USAGE_EXECUTABLE", str(home / ".local/bin/codex")))
    failed = []
    for target in TARGETS:
        started = time.monotonic()
        executed_at = datetime.now(timezone.utc).isoformat()
        try:
            result = ping_target(
                target, scheduled_at, home=home, state_dir=state_dir, executable=executable
            )
        except Exception as error:
            result = PingResult(
                target, scheduled_at, executed_at,
                round(time.monotonic() - started, 3), "failure",
                f"adapter failed: {type(error).__name__}",
            )
        log.info(
            "codex_usage scheduled_at=%s executed_at=%s target=%s duration_seconds=%.3f status=%s diagnostic=%s",
            result.scheduled_at, result.executed_at, result.target,
            result.duration_seconds, result.status, result.diagnostic,
        )
        if result.status == "failure":
            failed.append(target)
    if failed:
        raise RuntimeError("Codex activity failed for: " + ", ".join(failed))


@op(config_schema={"scheduled_at": str})
def activate_codex_targets(context) -> None:
    run_targets(context.op_config["scheduled_at"], context.log)


@job
def codex_usage_window():
    activate_codex_targets()


@schedule(
    job=codex_usage_window,
    cron_schedule=CRON_SCHEDULE,
    execution_timezone=TIMEZONE,
    default_status=DefaultScheduleStatus.RUNNING,
)
def codex_usage_schedule(context):
    scheduled = context.scheduled_execution_time.astimezone(ZoneInfo(TIMEZONE))
    slot = scheduled.isoformat()
    return RunRequest(
        run_key=slot,
        run_config={"ops": {"activate_codex_targets": {"config": {"scheduled_at": slot}}}},
    )


defs = Definitions(jobs=[codex_usage_window], schedules=[codex_usage_schedule])
