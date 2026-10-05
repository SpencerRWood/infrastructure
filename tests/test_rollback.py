"""Exercise the contract using real release history and fake target operations."""

import fcntl
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from jsonschema import Draft202012Validator, FormatChecker
import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("rollback", ROOT / "scripts/rollback.py")
rollback = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rollback)
SCHEMA = json.loads((ROOT / "docs/rollback-result.schema.json").read_text())
Draft202012Validator.check_schema(SCHEMA)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


class RollbackTests(unittest.TestCase):
    def setUp(self):
        # Commit hooks export Git paths for the outer worktree. Do not let
        # those paths redirect fixture commands into the real repository.
        local_git_variables = subprocess.run(
            ["git", "rev-parse", "--local-env-vars"], check=True,
            capture_output=True, text=True,
        ).stdout.splitlines()
        environment = {key: value for key, value in os.environ.items()
                       if key not in local_git_variables}
        environment_patch = patch.dict(os.environ, environment, clear=True)
        environment_patch.start()
        self.addCleanup(environment_patch.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "checkout"
        self.root.mkdir()
        self.config = tomllib.loads((ROOT / "rollback.toml").read_text())
        self.config["state_file"] = str(Path(self.temporary.name) / "state.json")
        self.state_path = Path(self.config["state_file"])
        self.git("init", "-b", "main")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Rollback test")
        self.git("remote", "add", "origin", f'https://github.com/{self.config["repository"]}.git')
        (self.root / "configuration").write_text("good\n")
        self.git("add", ".")
        self.git("commit", "-m", "good release")
        self.git("tag", "v1.0.0")
        self.good = self.git("rev-parse", "HEAD")
        (self.root / "configuration").write_text("bad\n")
        self.git("commit", "-am", "failed release")
        self.git("tag", "v1.0.1")
        self.failed = self.git("rev-parse", "HEAD")
        self.state = {
            "deployment_target": self.config["environment"],
            "current_release": "v1.0.0",
            "last_attempt_release": "v1.0.1",
            "last_attempt_state": "failure",
            "rollback_state": "failure",
            "unrelated_metadata": "preserved",
        }
        self.calls = []

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.root, check=True,
                              capture_output=True, text=True).stdout.strip()

    def invoke(self, apply=True, failing=None, **changes):
        self.state.update(changes)
        self.state_path.write_text(json.dumps(self.state))
        client = rollback.Rollback(self.root, self.config, self.config["environment"],
                                   "v1.0.1", apply)

        def operation(name):
            self.calls.append(name)
            self.assertEqual(self.failed if name == "health" else self.good,
                             self.git("rev-parse", "HEAD"))
            # The durable attempt marker exists before mutation/verification.
            self.assertEqual("failed", json.loads(self.state_path.read_text())[
                "rollback_contract"]["status"])
            if name == failing:
                raise subprocess.CalledProcessError(1, name)

        with patch.object(client, "operation", side_effect=operation):
            result = client.run()
        self.assertEqual(self.failed, self.git("rev-parse", "HEAD"))
        self.assertEqual("main", self.git("branch", "--show-current"))
        self.assertEqual(1, result["contract_version"])
        VALIDATOR.validate(result)
        return result

    def assertBlocked(self, result, reason):
        self.assertEqual("blocked", result["status"])
        self.assertEqual(reason, result["reason"])
        self.assertEqual("not_attempted", result["execution_outcome"])
        self.assertEqual("not_run", result["verification_result"])
        self.assertEqual([], self.calls)

    def test_success_restores_configuration_and_preserves_failure_evidence(self):
        result = self.invoke()
        self.assertEqual("succeeded", result["status"])
        self.assertEqual("succeeded", result["execution_outcome"])
        self.assertEqual("passed", result["verification_result"])
        self.assertEqual(self.good, result["previous_known_good_target"]["revision"])
        saved = json.loads(self.state_path.read_text())
        self.assertEqual("preserved", saved["unrelated_metadata"])
        self.assertEqual("failure", saved["last_attempt_state"])
        self.assertEqual("v1.0.1", saved["last_attempt_release"])
        self.assertEqual(result, saved["rollback_contract"])
        self.assertEqual(["check", "apply", "health"], self.calls)

    def test_preview_selects_without_applying_or_recording(self):
        result = self.invoke(apply=False)
        self.assertEqual("ready", result["status"])
        self.assertEqual([], self.calls)
        self.assertNotIn("rollback_contract", json.loads(self.state_path.read_text()))

    def test_notification_only_never_applies(self):
        self.config["mode"] = "notification_only"
        result = self.invoke()
        self.assertEqual("notification_only", result["status"])
        self.assertEqual([], self.calls)

    def test_required_uses_identical_semantics(self):
        self.config["mode"] = "required"
        self.assertEqual("succeeded", self.invoke()["status"])

    def test_no_known_good_target(self):
        self.assertBlocked(self.invoke(current_release=None), "no_known_good_target")

    def test_redeploy_of_current_release_uses_previous_success(self):
        self.assertEqual("succeeded", self.invoke(
            current_release="v1.0.1", previous_successful_release="v1.0.0")["status"])

    def test_identical_commit_alias_is_not_safe(self):
        self.git("tag", "v1.0.2", self.failed)
        self.assertBlocked(self.invoke(current_release="v1.0.2"), "no_distinct_known_good_target")

    def test_missing_and_malformed_release_tags(self):
        for value, reason in (("v9.0.0", "release_tag_unavailable"),
                              ("main", "invalid_release_tag"), ("--help", "invalid_release_tag")):
            with self.subTest(value=value):
                self.assertBlocked(self.invoke(current_release=value), reason)

    def test_non_ancestor_target_is_not_previous(self):
        self.git("checkout", "--orphan", "unrelated")
        self.git("commit", "-m", "unrelated release")
        self.git("tag", "v9.0.0")
        self.git("checkout", "main")
        self.assertBlocked(self.invoke(current_release="v9.0.0"), "known_good_target_not_previous")

    def test_stale_and_successful_deployment_evidence_blocks(self):
        self.assertBlocked(self.invoke(last_attempt_release="v0.0.0"), "stale_or_unconfirmed_failure")
        self.assertBlocked(self.invoke(last_attempt_release="v1.0.1", last_attempt_state="success"),
                           "stale_or_unconfirmed_failure")

    def test_wrong_environment_and_repository(self):
        self.assertBlocked(self.invoke(deployment_target="other"), "environment_evidence_mismatch")
        self.git("remote", "set-url", "origin", "https://github.com/untrusted/repo.git")
        self.assertBlocked(self.invoke(), "repository_mismatch")

    def test_dirty_checkout_blocks(self):
        (self.root / "untracked").write_text("work")
        self.assertBlocked(self.invoke(), "dirty_checkout")

    def test_operation_failures_are_distinct_and_fail_closed(self):
        for operation, execution, verification in (
            ("check", "not_attempted", "not_run"),
            ("apply", "failed", "not_run"),
            ("health", "succeeded", "failed"),
        ):
            with self.subTest(operation=operation):
                self.calls.clear()
                result = self.invoke(failing=operation)
                self.assertEqual("failed", result["status"])
                self.assertEqual(execution, result["execution_outcome"])
                self.assertEqual(verification, result["verification_result"])

    def test_repeated_success_and_existing_automatic_recovery_only_verify(self):
        result = self.invoke()
        self.state = json.loads(self.state_path.read_text())
        self.calls.clear()
        repeated = self.invoke()
        self.assertEqual("already_restored", repeated["execution_outcome"])
        self.assertEqual("passed", repeated["verification_result"])
        self.assertEqual(["health"], self.calls)
        self.assertEqual(result["previous_known_good_target"], repeated["previous_known_good_target"])
        self.state.pop("rollback_contract")
        self.calls.clear()
        self.assertEqual("already_restored", self.invoke()["execution_outcome"])
        self.assertEqual(["health"], self.calls)

    def test_failed_or_interrupted_attempt_cannot_reapply(self):
        self.invoke(failing="health")
        self.state = json.loads(self.state_path.read_text())
        self.calls.clear()
        self.assertBlocked(self.invoke(), "previous_rollback_attempt_failed")

    def test_lock_prevents_concurrent_clients(self):
        with self.state_path.with_suffix(".rollback.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.assertBlocked(self.invoke(), "rollback_in_progress")

    def test_invalid_or_absent_contract_fails_closed(self):
        self.config["unexpected"] = True
        self.assertBlocked(self.invoke(), "invalid_contract")
        self.config.pop("unexpected")
        self.config["mode"] = "unknown"
        self.assertBlocked(self.invoke(), "invalid_policy")

    def test_contract_record_from_older_incident_does_not_block_new_failure(self):
        self.state["rollback_contract"] = {
            "failed_target": {"ref": "v0.1.0", "revision": self.good},
            "status": "succeeded",
        }
        self.assertEqual("succeeded", self.invoke()["status"])

    def test_same_tag_with_conflicting_revision_blocks(self):
        self.state["rollback_contract"] = {
            "failed_target": {"ref": "v1.0.1", "revision": self.good},
            "status": "succeeded",
        }
        self.assertBlocked(self.invoke(), "conflicting_rollback_evidence")

    def test_workflow_matches_normal_deployment_serialization_and_identity(self):
        endpoint = yaml.safe_load((ROOT / ".github/workflows/rollback.yml").read_text())
        deploy = yaml.safe_load((ROOT / ".github/workflows/deploy.yml").read_text())
        job = next(job for job in deploy["jobs"].values()
                   if "deploy-ansible.yml" in job.get("uses", ""))
        self.assertEqual(job["with"]["concurrency_group"], endpoint["concurrency"]["group"])
        self.assertFalse(endpoint["concurrency"]["cancel-in-progress"])
        self.assertEqual(self.config["environment"], job["with"]["environment_name"])
        source_config = tomllib.loads((ROOT / "rollback.toml").read_text())
        self.assertEqual(source_config["state_file"], job["with"]["deployment_state_file"])
        self.assertIn(source_config["wrapper"], job["with"]["privileged_deploy_command"])
        for trigger in ("workflow_call", "workflow_dispatch"):
            inputs = endpoint["on"][trigger]["inputs"]
            self.assertEqual({"environment", "failed_target", "apply"}, set(inputs))
            self.assertFalse(inputs["apply"]["default"])
        self.assertEqual("main", endpoint["jobs"]["rollback"]["steps"][0]["with"]["ref"])

    def test_cli_missing_runner_evidence_is_structured_and_nonzero(self):
        result = subprocess.run([
            sys.executable, str(ROOT / "scripts/rollback.py"),
            "--environment", "unsupported", "--failed-target", "v1.0.1", "--json", "--apply",
        ], capture_output=True, text=True, timeout=10)
        self.assertEqual(3, result.returncode)
        parsed = json.loads(result.stdout)
        VALIDATOR.validate(parsed)
        self.assertEqual("blocked", parsed["status"])

    def test_missing_and_corrupt_state_fail_closed(self):
        for contents in (None, "not json", "[]"):
            with self.subTest(contents=contents):
                if contents is None:
                    self.state_path.unlink(missing_ok=True)
                else:
                    self.state_path.write_text(contents)
                client = rollback.Rollback(self.root, self.config, self.config["environment"],
                                           "v1.0.1", True)
                with patch.object(client, "operation") as operation:
                    self.assertEqual("blocked", client.run()["status"])
                    operation.assert_not_called()

    def test_evidence_write_failure_prevents_target_operations(self):
        self.state_path.write_text(json.dumps(self.state))
        client = rollback.Rollback(self.root, self.config, self.config["environment"], "v1.0.1", True)
        with patch.object(client, "save", side_effect=OSError), patch.object(client, "operation") as operation:
            result = client.run()
            operation.assert_not_called()
        self.assertEqual("failed", result["status"])
        self.assertEqual("evidence_write_failed", result["reason"])


if __name__ == "__main__":
    unittest.main()
