"""Consumer contract safety checks; all Git commits below are disposable fixtures."""

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
SPEC = importlib.util.spec_from_file_location("consumer_recovery", ROOT / "scripts/recovery.py")
RECOVERY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECOVERY)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        # Git commit hooks export paths for the outer worktree. Clear exactly
        # Git's repository-local environment before creating disposable fixtures.
        local_git_variables = subprocess.run(
            ["git", "rev-parse", "--local-env-vars"], check=True,
            capture_output=True, text=True, timeout=10,
        ).stdout.splitlines()
        environment = {key: value for key, value in os.environ.items()
                       if key not in local_git_variables}
        environment_patch = patch.dict(os.environ, environment, clear=True)
        environment_patch.start()
        self.addCleanup(environment_patch.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        source = json.loads((ROOT / "recovery/consumer.v1.json").read_text())
        self.config = source["preflight"]
        files = [
            "recovery/consumer.v1.json", "scripts/recovery.py", "scripts/rollback.py",
            "scripts/weekly_recovery.py",
            self.config["inventory_file"], self.config["playbook"],
            self.config["ansible_config"], *self.config["runbooks"],
        ]
        for name in files:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, path)
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("remote", "add", "origin",
                 "https://github.com/" + source["target"]["owning_repository"] + ".git")
        self.git("add", ".")
        self.git("commit", "-qm", "test: disposable consumer snapshot")
        self.declaration, _ = RECOVERY.manifest(self.root)

    def git(self, *args):
        result = subprocess.run(
            ["git", *args], cwd=self.root, capture_output=True, text=True, timeout=10,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        return result.stdout.strip()

    def test_manifest_pins_exact_clean_checkout_without_provider_dependency(self):
        self.assertEqual(self.git("rev-parse", "HEAD"), self.declaration["targets"][0]["revision"])
        self.assertEqual(["readiness", "verification"], self.declaration["targets"][0]["allowed_verification_levels"])
        self.assertNotIn("recovery_verification", (self.root / "scripts/recovery.py").read_text())
        command = self.declaration["targets"][0]["entrypoints"]["recovery"]
        self.assertEqual("scripts/rollback.py", command["entrypoint"])
        self.assertNotIn("--apply", command["args"])

    def test_dirty_checkout_cannot_export_trusted_revision(self):
        (self.root / "untracked").write_text("do-not-echo-secret")
        with self.assertRaises(RECOVERY.InvalidInput):
            RECOVERY.manifest(self.root)

    def test_wrong_repository_cannot_export_consumer_identity(self):
        self.git("remote", "set-url", "origin", "https://github.com/other/repository.git")
        with self.assertRaises(RECOVERY.InvalidInput):
            RECOVERY.manifest(self.root)

    def test_symlinks_and_missing_interfaces_fail_closed(self):
        runbook = self.root / self.config["runbooks"][0]
        runbook.unlink()
        with self.assertRaises(RECOVERY.InvalidInput):
            RECOVERY.preflight(self.root, self.declaration, self.config, run_syntax=False)
        runbook.symlink_to("/etc/passwd")
        with self.assertRaises(RECOVERY.InvalidInput):
            RECOVERY.preflight(self.root, self.declaration, self.config, run_syntax=False)

    def test_bootstrap_is_only_a_plan_and_never_connects_or_applies(self):
        with patch.object(RECOVERY.subprocess, "run", side_effect=AssertionError("execution")):
            plan = RECOVERY.bootstrap_plan(self.root, self.declaration, self.config)
        self.assertEqual("not_attempted", plan["execution_state"])
        self.assertEqual("isolated_recovery_test_required", plan["reason"])
        self.assertEqual(self.config["playbook"], plan["bootstrap"]["playbook"])

    def test_raw_output_and_inherited_credentials_are_discarded(self):
        completed = subprocess.CompletedProcess([], 0)
        with patch.dict(os.environ, {"SENSITIVE_TOKEN": "never-inherit"}):
            with patch.object(RECOVERY.subprocess, "run", return_value=completed) as run:
                result = RECOVERY.command_check(
                    self.root, self.config, "ansible-playbook", ["--syntax-check"], "syntax",
                )
        kwargs = run.call_args.kwargs
        self.assertNotIn("SENSITIVE_TOKEN", kwargs["env"])
        self.assertEqual(subprocess.DEVNULL, kwargs["stdout"])
        self.assertEqual(subprocess.DEVNULL, kwargs["stderr"])
        self.assertEqual(60, kwargs["timeout"])
        self.assertEqual("passed", result["state"])

    def test_tool_timeout_and_command_failure_remain_explicit(self):
        for error in (FileNotFoundError(), subprocess.TimeoutExpired("tool", 60)):
            with patch.object(RECOVERY.subprocess, "run", side_effect=error):
                result = RECOVERY.command_check(self.root, self.config, "tool", [], "syntax")
            self.assertEqual("unavailable", result["state"])
        with patch.object(RECOVERY.subprocess, "run", return_value=subprocess.CompletedProcess([], 1)):
            result = RECOVERY.command_check(self.root, self.config, "tool", [], "syntax")
        self.assertEqual("failed", result["state"])

    def test_preflight_only_parses_inventory_and_syntax_never_claims_recovery(self):
        def checked(root, config, tool, args, check_id):
            self.assertNotIn("--check", args)
            self.assertNotIn("--diff", args)
            self.assertTrue("--graph" in args or "--syntax-check" in args)
            return {"id": check_id, "state": "passed", "reason": "command_passed"}
        with patch.object(RECOVERY, "command_check", side_effect=checked):
            result = RECOVERY.preflight(self.root, self.declaration, self.config)
        self.assertEqual("unavailable", result["readiness_state"])
        self.assertEqual("external_prerequisites", result["checks"][-1]["id"])

    def test_cli_error_does_not_echo_input(self):
        (self.root / "untracked").write_text("do-not-echo-secret")
        result = subprocess.run(
            [str(self.root / "scripts/recovery.py"), "manifest"], cwd=self.root,
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(2, result.returncode)
        self.assertEqual("invalid_input", json.loads(result.stdout)["reason"])
        self.assertNotIn("do-not-echo", result.stdout + result.stderr)

    def test_local_only_scope_does_not_mask_syntax_failures(self):
        for state, expected in (("passed", "passed"), ("failed", "failed"),
                                ("unavailable", "unavailable")):
            with patch.object(RECOVERY, "command_check", return_value={
                "id": "syntax", "state": state, "reason": "command_result",
            }):
                result = RECOVERY.preflight(self.root, self.declaration, self.config,
                                            include_external=False)
            self.assertEqual(expected, result["readiness_state"])
            self.assertNotIn("external_prerequisites", [c["id"] for c in result["checks"]])
        args = next(check["command"]["args"] for check in self.declaration["targets"][0]["validation_commands"] if check["id"] == "consumer_preflight")
        self.assertEqual(["preflight", "--local-only"], args)


if __name__ == "__main__":
    unittest.main()
