#!/usr/bin/env python3
"""Version 1 consumer-owned previous-known-good configuration rollback."""

import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib


class Blocked(Exception):
    """A prerequisite is absent; no deployment is permitted."""


class Rollback:
    def __init__(self, root, config, environment, failed, apply=False):
        self.root = Path(root)
        self.config = config
        self.apply = apply
        self.state = None
        self.result = {
            "contract_version": 1,
            "repository": config.get("repository"),
            "environment": environment,
            "failed_target": {"ref": failed, "revision": None},
            "previous_known_good_target": None,
            "policy": config.get("mode"),
            "status": "blocked",
            "execution_outcome": "not_attempted",
            "verification_result": "not_run",
            "reason": "missing_contract",
            "observed_at": datetime.now(timezone.utc).isoformat(),
        }

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True,
            text=True, timeout=30,
        ).stdout.strip()

    def target(self, ref):
        if not isinstance(ref, str) or not re.fullmatch(r"v\d+\.\d+\.\d+", ref):
            raise Blocked("invalid_release_tag")
        try:
            revision = self.git("rev-parse", "--verify", f"refs/tags/{ref}^{{commit}}")
        except subprocess.CalledProcessError:
            raise Blocked("release_tag_unavailable") from None
        return {"ref": ref, "revision": revision}

    def prepare(self):
        expected = {"contract_version", "repository", "environment", "mode",
                    "state_file", "wrapper", "operation_timeout_seconds"}
        if set(self.config) != expected or self.config["contract_version"] != 1:
            raise Blocked("invalid_contract")
        if self.config["mode"] not in ("enabled", "required", "notification_only"):
            raise Blocked("invalid_policy")
        if (not isinstance(self.config["operation_timeout_seconds"], int)
                or isinstance(self.config["operation_timeout_seconds"], bool)
                or not 1 <= self.config["operation_timeout_seconds"] <= 1800
                or not Path(self.config["wrapper"]).is_absolute()
                or not Path(self.config["state_file"]).is_absolute()):
            raise Blocked("invalid_contract")
        if self.result["environment"] != self.config["environment"]:
            raise Blocked("unsupported_environment")
        origin = self.git("remote", "get-url", "origin")
        repository = self.config["repository"]
        if origin not in (f"https://github.com/{repository}.git",
                          f"https://github.com/{repository}",
                          f"git@github.com:{repository}.git"):
            raise Blocked("repository_mismatch")
        if self.git("status", "--porcelain", "--untracked-files=all"):
            raise Blocked("dirty_checkout")
        self.result["failed_target"] = self.target(self.result["failed_target"]["ref"])
        path = Path(self.config["state_file"])
        try:
            self.state = json.loads(path.read_text())
        except (OSError, ValueError):
            raise Blocked("deployment_evidence_unavailable") from None
        if not isinstance(self.state, dict):
            raise Blocked("invalid_deployment_evidence")
        if self.state.get("deployment_target") != self.result["environment"]:
            raise Blocked("environment_evidence_mismatch")
        if (self.state.get("last_attempt_release") != self.result["failed_target"]["ref"]
                or self.state.get("last_attempt_state") != "failure"):
            raise Blocked("stale_or_unconfirmed_failure")
        previous = self.state.get("current_release")
        if previous == self.result["failed_target"]["ref"]:
            previous = self.state.get("previous_successful_release")
        if not previous:
            raise Blocked("no_known_good_target")
        candidate = self.target(previous)
        if candidate["revision"] == self.result["failed_target"]["revision"]:
            raise Blocked("no_distinct_known_good_target")
        try:
            self.git("merge-base", "--is-ancestor", candidate["revision"],
                     self.result["failed_target"]["revision"])
        except subprocess.CalledProcessError:
            raise Blocked("known_good_target_not_previous") from None
        self.result["previous_known_good_target"] = candidate
        prior = self.state.get("rollback_contract")
        if (isinstance(prior, dict) and isinstance(prior.get("failed_target"), dict)
                and prior["failed_target"].get("ref") != self.result["failed_target"]["ref"]):
            # Normal deployment metadata retains unknown keys across releases.
            # A completed older incident must not block a new confirmed failure.
            prior = None
        if prior and (not isinstance(prior, dict)
                      or prior.get("failed_target") != self.result["failed_target"]
                      or prior.get("previous_known_good_target") != candidate):
            raise Blocked("conflicting_rollback_evidence")
        if prior and prior.get("status") != "succeeded":
            raise Blocked("previous_rollback_attempt_failed")
        if self.config["mode"] == "notification_only":
            self.result.update(status="notification_only", reason="policy_notification_only")
            return False
        self.result.update(status="ready", reason="known_good_target_selected")
        return True

    def operation(self, name):
        # All commands are fixed by the consumer; no caller-supplied shell code.
        subprocess.run(
            ["sudo", "-n", self.config["wrapper"], str(self.root), name],
            cwd=self.root, check=True, stdout=sys.stderr, stderr=sys.stderr,
            timeout=self.config["operation_timeout_seconds"],
        )

    def save(self):
        self.state["rollback_contract"] = self.result.copy()
        self.state["rollback_release"] = self.result["previous_known_good_target"]["ref"]
        self.state["rollback_state"] = (
            "success" if self.result["status"] == "succeeded" else "failure")
        if self.result["status"] == "succeeded":
            self.state["current_release"] = self.state["rollback_release"]
        path = Path(self.config["state_file"])
        fd, temporary = tempfile.mkstemp(prefix=".rollback-", dir=path.parent)
        try:
            with os.fdopen(fd, "w") as stream:
                json.dump(self.state, stream, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def execute(self):
        original = self.git("rev-parse", "HEAD")
        branch = self.git("symbolic-ref", "--quiet", "--short", "HEAD") if (
            self.git("rev-parse", "--abbrev-ref", "HEAD") != "HEAD") else original
        try:
            recovered = (self.state.get("rollback_state") == "success"
                         and self.state.get("rollback_release") ==
                         self.result["previous_known_good_target"]["ref"])
            # Persist the attempt before any target operation. A killed process
            # cannot cause an unattended second apply on the next invocation.
            self.result.update(status="failed", reason="rollback_attempt_incomplete")
            self.save()
            self.result["reason"] = "checkout_failed"
            self.git("checkout", "--detach", self.result["previous_known_good_target"]["revision"])
            if recovered:
                self.result["execution_outcome"] = "already_restored"
            else:
                self.result["reason"] = "preflight_failed"
                self.operation("check")
                self.result.update(execution_outcome="failed", reason="apply_failed")
                self.operation("apply")
                self.result["execution_outcome"] = "succeeded"
            # Verify using the authoritative contract checkout's health gates,
            # rather than silently accepting an older tag's weaker checker.
            self.result["reason"] = "checkout_restore_failed"
            self.git("checkout", branch)
            self.result.update(verification_result="failed", reason="verification_failed")
            self.operation("health")
            self.result.update(status="succeeded", verification_result="passed",
                               reason="known_good_target_verified")
        except (subprocess.SubprocessError, OSError):
            self.result["status"] = "failed"
        finally:
            try:
                self.git("checkout", branch)
            except (subprocess.SubprocessError, OSError):
                self.result.update(status="failed", reason="checkout_restore_failed")
            try:
                self.save()
            except (OSError, ValueError):
                self.result.update(status="failed", reason="evidence_write_failed")

    def run(self):
        try:
            # Workflow concurrency serializes this with normal deployments. The
            # additional lock prevents two local contract clients from racing.
            path = Path(self.config["state_file"])
            with path.with_suffix(".rollback.lock").open("a") as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    raise Blocked("rollback_in_progress") from None
                if self.prepare() and self.apply:
                    self.execute()
        except Blocked as error:
            self.result.update(status="blocked", reason=str(error))
        except (KeyError, TypeError, ValueError, OSError, subprocess.SubprocessError):
            self.result.update(status="blocked", reason="rollback_prerequisite_unavailable")
        return self.result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--failed-target", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true", required=True)
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        config = tomllib.loads((root / "rollback.toml").read_text())
    except (OSError, ValueError):
        config = {}
    result = Rollback(root, config, args.environment, args.failed_target, args.apply).run()
    print(json.dumps(result, sort_keys=True))
    return {"succeeded": 0, "ready": 0, "notification_only": 3,
            "blocked": 3, "failed": 1}[result["status"]]


if __name__ == "__main__":
    sys.exit(main())
