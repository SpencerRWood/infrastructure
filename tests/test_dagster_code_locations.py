"""External Dagster declarations render the shared runtime contract."""

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ansible.errors import AnsibleFilterError
from jinja2 import Environment
import yaml


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "dagster_locations", ROOT / "ansible/filter_plugins/dagster_locations.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
validate = MODULE.valid_dagster_locations
IMAGE = "ghcr.io/example/data-cleanup:v1.0.0@sha256:" + "a" * 64


def render(locations, runtime_environments=None):
    runtime_environments = runtime_environments or {}
    validate(locations, runtime_environments)
    context = {
        "dagster_code_locations": locations,
        "dagster_runtime_environments": runtime_environments,
    }
    engine = Environment(autoescape=False)
    compose = yaml.safe_load(engine.from_string(
        (ROOT / "ansible/roles/dagster/templates/compose.infisical.yml.j2").read_text()
    ).render(**context))
    workspace = yaml.safe_load(engine.from_string(
        (ROOT / "ansible/roles/dagster/templates/workspace.yaml.j2").read_text()
    ).render(**context))
    health = [location["service_name"] for location in locations]
    return compose, workspace, health


class DagsterCodeLocationTests(unittest.TestCase):
    def setUp(self):
        self.minimal = {
            "name": "data_cleanup",
            "service_name": "data-cleanup-code",
            "image": IMAGE,
            "port": 4000,
        }

    def test_minimal_location_inherits_runtime_and_registration(self):
        compose, workspace, health = render([self.minimal])
        service = compose["services"]["data-cleanup-code"]
        self.assertEqual(service["image"], IMAGE)
        self.assertEqual(service["restart"], "unless-stopped")
        self.assertEqual(service["user"], "1000:1000")
        self.assertEqual(service["environment"], {"DAGSTER_GRPC_PORT": "4000"})
        self.assertEqual(service["env_file"], [
            "/srv/infrastructure/secrets/static/dagster.env",
            "/srv/infrastructure/secrets/runtime/dagster.env",
        ])
        self.assertEqual(service["volumes"], [
            "${DAGSTER_CONFIG_PATH:?required}:/opt/dagster/dagster_home:ro",
            "${DAGSTER_LOCAL_PATH:?required}:/opt/dagster/local",
        ])
        self.assertEqual(service["networks"], ["postgres"])
        self.assertEqual(service["expose"], ["4000"])
        self.assertEqual(service["healthcheck"], {
            "test": ["CMD", "dagster", "api", "grpc-health-check", "-p", "4000"],
            "interval": "10s", "timeout": "10s", "retries": 10, "start_period": "30s",
        })
        self.assertIn({"grpc_server": {
            "host": "data-cleanup-code", "port": 4000, "location_name": "data_cleanup"
        }}, workspace["load_from"])
        self.assertEqual(health, ["data-cleanup-code"])

    def test_outbound_network_is_opt_in(self):
        location = {**self.minimal, "capabilities": {"outbound_network": True}}
        compose, _, _ = render([location])
        self.assertEqual(compose["services"]["data-cleanup-code"]["networks"], ["postgres", "proxy"])

    def test_application_runtime_environment_is_optional(self):
        runtime = {"reports": {"output": "/srv/infrastructure/secrets/runtime/reports.env"}}
        location = {**self.minimal, "runtime_env": "reports"}
        compose, _, _ = render([location], runtime)
        self.assertEqual(compose["services"]["data-cleanup-code"]["env_file"][-1], runtime["reports"]["output"])
        self.assertNotIn("OPENPROJECT_API_TOKEN", str(compose))

    def test_duplicate_names_services_and_conflicting_ports_are_rejected(self):
        second = {**self.minimal, "name": "other", "service_name": "other-code", "port": 4001}
        for change in ({"name": "data_cleanup"}, {"service_name": "data-cleanup-code"},
                       {"service_name": "data-cleanup-code", "port": 4002}):
            with self.subTest(change=change), self.assertRaises(AnsibleFilterError):
                validate([self.minimal, {**second, **change}], {})
        # Separate containers may use the same internal gRPC port.
        validate([self.minimal, {**second, "port": 4000}], {})

    def test_unpinned_images_invalid_references_and_capabilities_are_rejected(self):
        for change in ({"image": "ghcr.io/example/data-cleanup:latest"},
                       {"runtime_env": "missing"}, {"capabilities": {"outbound_network": "yes"}},
                       {"port": 0}, {"service_name": "dagster-daemon"}):
            with self.subTest(change=change), self.assertRaises(AnsibleFilterError):
                validate([{**self.minimal, **change}], {})

    def test_openproject_reports_keeps_application_contract(self):
        manifest = yaml.safe_load((ROOT / "environments/dev.yml").read_text())
        locations = manifest["dagster_code_locations"]
        runtime = manifest["dagster_runtime_environments"]
        compose, workspace, health = render(locations, runtime)
        service = compose["services"]["openproject-reports-code"]
        self.assertEqual(service["user"], "1000:1000")
        self.assertEqual(service["networks"], ["postgres", "proxy"])
        self.assertEqual(service["env_file"][-1], runtime["openproject_reports"]["output"])
        self.assertEqual(locations[0]["image"],
                         "ghcr.io/spencerrwood/openproject-reports:v0.1.7@sha256:90d955f26549864699295c46c819c8ad13e80686c4ec648ca022fa5820099cf1")
        self.assertEqual(runtime["openproject_reports"]["required_keys"], [
            "OPENPROJECT_BASE_URL", "OPENPROJECT_API_TOKEN",
            "GOOGLE_DRIVE_CREDENTIALS_JSON", "GOOGLE_DRIVE_FOLDER_ID",
        ])
        self.assertEqual(
            manifest["infrastructure_infisical_runtime_services"]["dagster"]["required_keys"],
            ["DAGSTER_POSTGRES_PASSWORD"],
        )
        self.assertIn({"grpc_server": {
            "host": "openproject-reports-code", "port": 4000, "location_name": "openproject_reports"
        }}, workspace["load_from"])
        self.assertEqual(health, ["openproject-reports-code"])

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose is unavailable")
    def test_rendered_compose_passes_docker_config(self):
        manifest = yaml.safe_load((ROOT / "environments/dev.yml").read_text())
        cases = (
            ([self.minimal], {}),
            (manifest["dagster_code_locations"], manifest["dagster_runtime_environments"]),
        )
        for locations, runtime in cases:
            with self.subTest(location=locations[0]["name"]):
                compose, _, _ = render(locations, runtime)
                for service in compose["services"].values():
                    if "env_file" in service:
                        service["env_file"] = ["/dev/null"]
                with tempfile.TemporaryDirectory() as directory:
                    compose_file = Path(directory) / "compose.yml"
                    compose_file.write_text(yaml.safe_dump(compose), encoding="utf-8")
                    environment = {
                        **os.environ,
                        "DAGSTER_PROJECT_NAME": "infrastructure-dev-dagster",
                        "DAGSTER_IMAGE": "local/infrastructure-dagster:1.13.16",
                        "DAGSTER_VERSION": "1.13.16",
                        "DAGSTER_LIB_VERSION": "0.29.16",
                        "PYTHON_VERSION": "3.12-slim",
                        "DAGSTER_CONFIG_PATH": "/tmp/dagster-config",
                        "DAGSTER_LOCAL_PATH": "/tmp/dagster-local",
                        "DAGSTER_CODEX_HOME": "/tmp/dagster-home",
                        "DAGSTER_CODEX_STATE_PATH": "/tmp/dagster-codex-state",
                        "DAGSTER_POSTGRES_NETWORK": "infrastructure-dev-postgres",
                        "DAGSTER_PROXY_NETWORK": "infrastructure-dev-proxy",
                    }
                    result = subprocess.run(
                        ["docker", "compose", "-f", str(compose_file), "config", "--quiet"],
                        env=environment, capture_output=True, text=True, check=False,
                    )
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
