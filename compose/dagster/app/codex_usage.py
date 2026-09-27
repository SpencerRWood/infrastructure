"""Minimal, at-most-once Codex activity for one scheduled slot."""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

PROMPT = "Reply with exactly OK. Do not use tools or inspect files."
TARGETS = ("codex", "codex2")
TIMEOUT_SECONDS = 90


@dataclass(frozen=True)
class PingResult:
    target: str
    scheduled_at: str
    executed_at: str
    duration_seconds: float
    status: str
    diagnostic: str


def profile_home(target: str, home: Path) -> Path:
    if target == "codex":
        return home / ".codex"
    if target == "codex2":
        return home / ".codex-secondary"
    raise ValueError("unknown Codex target")


def ping_target(
    target: str,
    scheduled_at: str,
    *,
    home: Path,
    state_dir: Path,
    executable: Path,
) -> PingResult:
    """Claim before launch: a retry never issues a second request for the slot."""
    profile = profile_home(target, home)
    slot = datetime.fromisoformat(scheduled_at)
    expected = {(6, 0), (11, 5), (16, 10)}
    eastern = ZoneInfo("America/New_York")
    if (
        slot.tzinfo is None
        or (slot.hour, slot.minute) not in expected
        or slot.utcoffset() != slot.astimezone(eastern).utcoffset()
        or slot.date() != slot.astimezone(eastern).date()
    ):
        raise ValueError("invalid scheduled slot")
    slot_key = slot.strftime("%Y%m%dT%H%M%z")
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    marker = state_dir / f"{slot_key}-{target}.json"
    now = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    try:
        descriptor = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        return PingResult(target, scheduled_at, now, 0.0, "skipped", "slot already claimed")
    with os.fdopen(descriptor, "w") as stream:
        json.dump({"scheduled_at": scheduled_at, "target": target, "claimed_at": now}, stream)
        stream.flush()
        os.fsync(stream.fileno())

    status = "failure"
    diagnostic = "unknown failure"
    try:
        if not executable.is_file() or not os.access(executable, os.X_OK):
            diagnostic = "Codex executable unavailable"
        elif not (profile / "auth.json").is_file():
            diagnostic = "Codex profile authentication unavailable"
        else:
            environment = os.environ.copy()
            environment.pop("CODEX_ACCESS_TOKEN", None)
            environment.pop("CODEX_API_KEY", None)
            environment["CODEX_HOME"] = str(profile)
            completed = subprocess.run(
                [
                    str(executable), "exec", "--ephemeral", "--sandbox", "read-only",
                    "--skip-git-repo-check", "-C", "/tmp", PROMPT,
                ],
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=TIMEOUT_SECONDS,
                check=False,
            )
            if completed.returncode == 0:
                status, diagnostic = "success", "request completed"
            else:
                diagnostic = f"Codex exited with status {completed.returncode}"
    except subprocess.TimeoutExpired:
        diagnostic = "Codex request timed out"
    except OSError as error:
        diagnostic = f"Codex launch failed: {type(error).__name__}"

    result = PingResult(target, scheduled_at, now, round(time.monotonic() - started, 3), status, diagnostic)
    # The marker is durable and remains claimed even on failure. No CLI output is stored.
    marker.write_text(json.dumps(result.__dict__) + "\n")
    return result
