#!/usr/bin/env python3
"""Consumer-owned manifest export and non-destructive reconstruction preflight."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


class InvalidInput(ValueError):
    """An unsafe or incomplete consumer checkout."""


def checked_path(root, name):
    path = root / name
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise InvalidInput("invalid_repository_path")
    if not path.is_file():
        raise InvalidInput("missing_repository_file")
    return path


def clean_revision(root, owner):
    def git(*args):
        result = subprocess.run(
            ["git", *args], cwd=root, capture_output=True, text=True, timeout=10,
        )
        if result.returncode:
            raise InvalidInput("repository_unavailable")
        return result.stdout.strip()

    if git("rev-parse", "--show-toplevel") != str(root.resolve()):
        raise InvalidInput("invalid_repository_root")
    remote = git("remote", "get-url", "origin")
    if remote not in {f"https://github.com/{owner}.git",
                       f"https://github.com/{owner}", f"git@github.com:{owner}.git"}:
        raise InvalidInput("repository_mismatch")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise InvalidInput("dirty_checkout")
    revision = git("rev-parse", "HEAD")
    if len(revision) != 40 or any(c not in "0123456789abcdef" for c in revision):
        raise InvalidInput("unsupported_git_revision")
    return revision


def manifest(root):
    source = json.loads(checked_path(root, "recovery/consumer.v1.json").read_text())
    if set(source) != {"schema_version", "target", "preflight"}:
        raise InvalidInput("invalid_consumer_configuration")
    if source["schema_version"] != "1" or "revision" in source["target"]:
        raise InvalidInput("invalid_consumer_configuration")
    target = source["target"]
    target["revision"] = clean_revision(root, target["owning_repository"])
    return {"schema_version": "1", "targets": [target]}, source["preflight"]


def command_check(root, config, tool, args, check_id):
    # Do not inherit application credentials, callback plugins or Ansible overrides.
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "ANSIBLE_CONFIG": str(checked_path(root, config["ansible_config"])),
        "ANSIBLE_NOCOLOR": "1",
    }
    try:
        # Inventory parsing and syntax checking cannot connect to the managed host.
        # Discard raw output: inventory and Ansible errors may contain protected input.
        result = subprocess.run(
            [tool, *args], cwd=root, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60,
        )
    except FileNotFoundError:
        return {"id": check_id, "state": "unavailable", "reason": "tool_unavailable"}
    except subprocess.TimeoutExpired:
        return {"id": check_id, "state": "unavailable", "reason": "command_timeout"}
    return {
        "id": check_id, "state": "passed" if result.returncode == 0 else "failed",
        "reason": "command_passed" if result.returncode == 0 else "command_failed",
    }


def preflight(root, declaration, config, run_syntax=True, include_external=True):
    target = declaration["targets"][0]
    for command in (
        *target["entrypoints"].values(),
        *(check["command"] for check in target["validation_commands"]),
    ):
        entrypoint = checked_path(root, command["entrypoint"])
        if not os.access(entrypoint, os.X_OK):
            raise InvalidInput("entrypoint_not_executable")
    checked_path(root, config["playbook"])
    checked_path(root, config["inventory_file"])
    for runbook in config["runbooks"]:
        checked_path(root, runbook)
    checks = [
        {"id": "checkout", "state": "passed", "reason": "clean_revision"},
        {"id": "consumer_interfaces", "state": "passed", "reason": "files_present"},
    ]
    if run_syntax:
        checks.extend([
            command_check(root, config, "ansible-inventory",
                          ["-i", config["inventory"], "--graph"], "inventory"),
            command_check(root, config, "ansible-playbook",
                          ["-i", config["inventory"], config["playbook"],
                           "--syntax-check"], "syntax"),
        ])
    else:
        checks.append({"id": "syntax", "state": "skipped", "reason": "not_requested"})
    if include_external:
        checks.append({
            "id": "external_prerequisites", "state": "unavailable",
            "reason": "secrets_backups_storage_artifacts_not_probed",
        })
    states = {check["state"] for check in checks}
    state = next((item for item in ("failed", "unavailable", "skipped")
                  if item in states), "passed")
    return {
        "schema_version": "1", "mode": "preflight", "readiness_state": state,
        "checks": checks,
    }


def bootstrap_plan(root, declaration, config):
    # Plans refer to the same Ansible playbook as normal deployment. No alternate
    # recovery implementation, shell forwarding entrypoint, or host apply exists.
    preflight(root, declaration, config, run_syntax=False)
    return {
        "schema_version": "1", "mode": "plan", "execution_state": "not_attempted",
        "reason": "isolated_recovery_test_required",
        "revision": declaration["targets"][0]["revision"],
        "bootstrap": {
            "tool": "ansible-playbook",
            "playbook": config["playbook"],
            "inventory": config["inventory"],
        },
        "recovery": declaration["targets"][0]["entrypoints"]["recovery"],
        "supported_levels": ["readiness"],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["manifest", "preflight", "bootstrap"])
    parser.add_argument("--local-only", action="store_true",
                        help="Validate local configuration; caller owns external probes")
    args = parser.parse_args(argv)
    if args.local_only and args.operation != "preflight":
        parser.error("--local-only requires preflight")
    try:
        declaration, config = manifest(ROOT)
        if args.operation == "manifest":
            result = declaration
            status = 0
        elif args.operation == "bootstrap":
            result = bootstrap_plan(ROOT, declaration, config)
            status = 3
        else:
            result = preflight(ROOT, declaration, config,
                               include_external=not args.local_only)
            status = {"passed": 0, "failed": 1, "unavailable": 4,
                      "skipped": 3}[result["readiness_state"]]
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        result = {"schema_version": "1", "state": "failed", "reason": "invalid_input"}
        status = 2
    sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    return status


if __name__ == "__main__":
    raise SystemExit(main())
