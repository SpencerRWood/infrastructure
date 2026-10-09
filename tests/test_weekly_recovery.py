"""Executable recovery safety and failure-path tests; no live service inputs."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("weekly_recovery", ROOT / "scripts/weekly_recovery.py")
WEEKLY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(WEEKLY)


class WeeklyTests(unittest.TestCase):
    def test_real_deadline_interrupts_subprocess_and_cleans(self):
        def slow(workspace_checks, workspace):
            WEEKLY.command(["python3", "-c", "import time; time.sleep(30)"], workspace)
        with patch.object(WEEKLY, "automation", side_effect=slow):
            with patch.object(WEEKLY, "restore_postgres") as restore:
                result = WEEKLY.verify(deadline_seconds=1)
        restore.assert_not_called()
        self.assertEqual("unavailable", result["readiness_state"])
        self.assertEqual("passed", result["checks"][-1]["state"])

    def test_interruption_stops_phases_and_enters_cleanup(self):
        with patch.object(WEEKLY, "automation", side_effect=WEEKLY.VerificationInterrupted()):
            with patch.object(WEEKLY, "restore_postgres") as restore:
                result = WEEKLY.verify()
        restore.assert_not_called()
        self.assertEqual("unavailable", result["readiness_state"])
        self.assertEqual("passed", result["checks"][-1]["state"])

    def test_unavailable_temporary_storage_has_no_false_cleanup_claim(self):
        with patch.object(WEEKLY.tempfile, "mkdtemp", side_effect=OSError("secret")):
            result = WEEKLY.verify()
        self.assertEqual("unavailable", result["readiness_state"])
        self.assertEqual("unavailable", result["checks"][-1]["state"])
        self.assertNotIn("secret", json.dumps(result))

    def test_check_mode_unsupported_tasks_fail_closed(self):
        recap = b"localhost : ok=1 changed=0 unreachable=0 failed=0 skipped=1 rescued=0 ignored=0"
        with tempfile.TemporaryDirectory(prefix="rv-", dir="/tmp") as directory:
            with patch.object(WEEKLY, "command", return_value=recap):
                with self.assertRaises(WEEKLY.VerificationFailure) as error:
                    WEEKLY.approved_automation(Path(directory), check_mode=True)
        self.assertEqual("unsupported_check_mode_task", error.exception.reason)

    def test_idempotence_drift_and_approval_are_enforced(self):
        with tempfile.TemporaryDirectory(prefix="rv-", dir="/tmp") as directory:
            with patch.object(WEEKLY, "approved_automation", side_effect=[2, 1]):
                with self.assertRaises(WEEKLY.VerificationFailure) as error:
                    WEEKLY.idempotence(Path(directory))
            self.assertEqual("idempotence_drift", error.exception.reason)
            with patch.object(WEEKLY.json, "loads", return_value={
                "idempotence_safe": False, "allowed_second_run_changes": 0,
            }):
                with self.assertRaises(WEEKLY.VerificationFailure) as error:
                    WEEKLY.approved_automation(Path(directory))
            self.assertEqual("idempotence_not_approved", error.exception.reason)

    def test_timeout_unavailable_tool_and_output_are_bounded(self):
        with tempfile.TemporaryDirectory(prefix="rv-", dir="/tmp") as directory:
            workspace = Path(directory)
            for argv, reason in (
                (["definitely-missing-weekly-tool"], "tool_unavailable"),
                (["python3", "-c", "import time; time.sleep(30)"], "command_timeout"),
                (["python3", "-c", "print('secret-do-not-echo' * 7000)"], "output_limit_exceeded"),
                (["python3", "-c", "raise SystemExit(1)"], "command_failed"),
            ):
                with self.assertRaises(WEEKLY.VerificationFailure) as error:
                    WEEKLY.command(argv, workspace, timeout=1)
                self.assertEqual(reason, error.exception.reason)
                self.assertNotIn("secret-do-not-echo", str(error.exception))

    def test_commands_do_not_inherit_secret_or_connection_settings(self):
        with tempfile.TemporaryDirectory(prefix="rv-", dir="/tmp") as directory:
            with patch.dict(os.environ, {"SENSITIVE_TOKEN": "secret", "PGHOST": "live"}):
                output = WEEKLY.command(
                    ["python3", "-c", "import os; print('SENSITIVE_TOKEN' in os.environ or 'PGHOST' in os.environ)"],
                    Path(directory),
                )
        self.assertEqual(b"False\n", output)

    def test_cleanup_failure_is_independent_of_restore_result(self):
        captured = []
        real_mkdtemp = tempfile.mkdtemp
        def allocate(*args, **kwargs):
            value = real_mkdtemp(*args, **kwargs)
            captured.append(Path(value))
            return value
        with patch.object(WEEKLY.tempfile, "mkdtemp", side_effect=allocate):
            with patch.object(WEEKLY, "automation"):
                with patch.object(WEEKLY, "restore_postgres"):
                    with patch.object(WEEKLY.shutil, "rmtree", side_effect=OSError("secret")):
                        result = WEEKLY.verify()
        try:
            cleanup = next(check for check in result["checks"] if check["phase"] == "cleanup")
            self.assertEqual("failed", cleanup["state"])
            self.assertEqual("failed", result["readiness_state"])
            self.assertNotIn("secret", json.dumps(result))
        finally:
            for path in captured:
                shutil.rmtree(path)

    def test_transient_dependency_failure_preserves_unknown_and_cleans(self):
        captured = []
        real_mkdtemp = tempfile.mkdtemp
        def allocate(*args, **kwargs):
            value = real_mkdtemp(*args, **kwargs)
            captured.append(Path(value))
            return value
        with patch.object(WEEKLY.tempfile, "mkdtemp", side_effect=allocate):
            with patch.object(WEEKLY, "automation"):
                with patch.object(WEEKLY, "restore_postgres",
                                  side_effect=WEEKLY.VerificationFailure("dependency_unavailable", "unavailable")):
                    result = WEEKLY.verify()
        self.assertEqual("unavailable", result["readiness_state"])
        self.assertTrue(all(not path.exists() for path in captured))
        self.assertEqual("passed", result["checks"][-1]["state"])

    @unittest.skipUnless(shutil.which("ansible-playbook") and shutil.which("postgres"),
                         "local integration requires declared verification tools")
    def test_real_weekly_recovery_and_resource_cleanup(self):
        captured = []
        real_mkdtemp = tempfile.mkdtemp
        def allocate(*args, **kwargs):
            value = real_mkdtemp(*args, **kwargs)
            captured.append(Path(value))
            return value
        with patch.object(WEEKLY.tempfile, "mkdtemp", side_effect=allocate):
            result = WEEKLY.verify()
        self.assertEqual("passed", result["readiness_state"], result)
        self.assertTrue(all(not path.exists() for path in captured))
        restore = next(check for check in result["checks"] if check["phase"] == "restore")
        self.assertRegex(restore["artifact_sha256"], "^[0-9a-f]{64}$")

    def test_corrupt_backup_and_integrity_failures(self):
        with tempfile.TemporaryDirectory(prefix="rv-", dir="/tmp") as directory:
            workspace = Path(directory)
            checks = []
            with patch.object(WEEKLY, "digest_file", return_value="0" * 64):
                WEEKLY.restore_postgres(checks, workspace)
            self.assertEqual("backup_checksum_mismatch", checks[0]["reason"])
            self.assertEqual("skipped", checks[1]["state"])
        with tempfile.TemporaryDirectory(prefix="rv-", dir="/tmp") as directory:
            checks = []
            def output(argv, workspace, timeout=30):
                if argv[0] == "psql":
                    return b"incorrect"
                return b""
            with patch.object(WEEKLY, "command", side_effect=output):
                with patch.object(WEEKLY.shutil, "which", return_value="/fixture/postgres"):
                    WEEKLY.restore_postgres(checks, Path(directory))
            self.assertEqual("passed", checks[0]["state"])
            self.assertTrue(all(check["state"] == "failed" for check in checks[1:]))

    def test_unreadable_backup_cleans_after_failure(self):
        with patch.object(WEEKLY, "automation"):
            with patch.object(WEEKLY, "digest_file", side_effect=OSError("secret-path")):
                result = WEEKLY.verify()
        self.assertEqual("failed", result["readiness_state"])
        self.assertEqual("passed", result["checks"][-1]["state"])
        self.assertNotIn("secret-path", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
