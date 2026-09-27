"""Focused safety and scheduling checks for the Mac Codex code location."""

from __future__ import annotations

import logging
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch
from zoneinfo import ZoneInfo

from dagster import build_schedule_context
from dagster._utils.schedules import schedule_execution_time_iterator

APP = Path(__file__).resolve().parents[1] / "compose/dagster/app"
sys.path.insert(0, str(APP))

from codex_definitions import CRON_SCHEDULE, TIMEZONE, codex_usage_schedule, run_targets  # noqa: E402
from codex_usage import PingResult, ping_target  # noqa: E402


class CodexScheduleTests(unittest.TestCase):
    def test_schedule_times_and_dst(self) -> None:
        self.assertEqual(TIMEZONE, "America/New_York")
        self.assertEqual(CRON_SCHEDULE, ["0 6 * * *", "5 11 * * *", "10 16 * * *"])
        for day in (datetime(2026, 3, 7), datetime(2026, 3, 8), datetime(2026, 11, 1)):
            start = day.replace(tzinfo=ZoneInfo(TIMEZONE)).timestamp()
            iterator = schedule_execution_time_iterator(start, CRON_SCHEDULE, TIMEZONE)
            ticks = [next(iterator) for _ in range(3)]
            self.assertEqual([(tick.hour, tick.minute) for tick in ticks], [(6, 0), (11, 5), (16, 10)])
            self.assertTrue(all(tick.tzinfo is not None for tick in ticks))
            request = codex_usage_schedule.evaluate_tick(
                build_schedule_context(scheduled_execution_time=ticks[0])
            ).run_requests[0]
            self.assertEqual(request.run_key, ticks[0].isoformat())
            self.assertEqual(
                request.run_config["ops"]["activate_codex_targets"]["config"]["scheduled_at"],
                ticks[0].isoformat(),
            )


class CodexAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.home = Path(self.temporary.name)
        self.state = self.home / "slots"
        self.executable = self.home / "codex"
        self.executable.write_text("#!/bin/sh\n")
        self.executable.chmod(0o700)
        for profile in (".codex", ".codex-secondary"):
            directory = self.home / profile
            directory.mkdir()
            (directory / "auth.json").write_text("private credential")
        self.slot = "2026-09-27T06:00:00-04:00"

    @patch("codex_usage.subprocess.run")
    def test_two_profiles_and_retry_claim(self, run: Mock) -> None:
        run.return_value = Mock(returncode=0, stdout="private response", stderr="secret diagnostic")
        results = [
            ping_target(target, self.slot, home=self.home, state_dir=self.state, executable=self.executable)
            for target in ("codex", "codex2")
        ]
        self.assertEqual([result.status for result in results], ["success", "success"])
        self.assertEqual(run.call_count, 2)
        self.assertTrue(
            all(
                call.kwargs["stdout"] == subprocess.DEVNULL
                and call.kwargs["stderr"] == subprocess.DEVNULL
                for call in run.call_args_list
            )
        )
        self.assertEqual(
            [call.kwargs["env"]["CODEX_HOME"] for call in run.call_args_list],
            [str(self.home / ".codex"), str(self.home / ".codex-secondary")],
        )
        retry = ping_target("codex", self.slot, home=self.home, state_dir=self.state, executable=self.executable)
        self.assertEqual(retry.status, "skipped")
        self.assertEqual(run.call_count, 2)
        self.assertNotIn("private response", "".join(path.read_text() for path in self.state.iterdir()))
        self.assertNotIn("secret diagnostic", "".join(path.read_text() for path in self.state.iterdir()))

    @patch("codex_usage.subprocess.run")
    def test_failure_is_claimed_and_diagnostics_are_safe(self, run: Mock) -> None:
        run.return_value = Mock(returncode=17, stdout="secret output", stderr="token data")
        result = ping_target("codex", self.slot, home=self.home, state_dir=self.state, executable=self.executable)
        self.assertEqual(result.status, "failure")
        self.assertEqual(result.diagnostic, "Codex exited with status 17")
        self.assertEqual(
            ping_target("codex", self.slot, home=self.home, state_dir=self.state, executable=self.executable).status,
            "skipped",
        )
        self.assertEqual(run.call_count, 1)

    @patch("codex_definitions.ping_target")
    def test_one_target_failure_still_attempts_the_other(self, ping: Mock) -> None:
        ping.side_effect = [
            PingResult("codex", self.slot, "now", 1.0, "failure", "exit status 17"),
            PingResult("codex2", self.slot, "now", 1.0, "success", "request completed"),
        ]
        logger = Mock(spec=logging.Logger)
        with self.assertRaisesRegex(RuntimeError, "codex"):
            run_targets(self.slot, logger)
        self.assertEqual([call.args[0] for call in ping.call_args_list], ["codex", "codex2"])
        self.assertEqual(logger.info.call_count, 2)

    @patch("codex_definitions.ping_target")
    def test_adapter_exception_does_not_suppress_second_or_log_message(self, ping: Mock) -> None:
        ping.side_effect = [
            RuntimeError("credential=private"),
            PingResult("codex2", self.slot, "now", 1.0, "success", "request completed"),
        ]
        logger = Mock(spec=logging.Logger)
        with self.assertRaisesRegex(RuntimeError, "codex"):
            run_targets(self.slot, logger)
        self.assertEqual(ping.call_count, 2)
        self.assertNotIn("credential=private", str(logger.info.call_args_list))


if __name__ == "__main__":
    unittest.main()
