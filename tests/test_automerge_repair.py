"""Check environment opt-in, code-location wiring, and credential isolation."""

from pathlib import Path
import tomllib
import unittest

from jinja2 import Environment
import yaml

ROOT = Path(__file__).parents[1]


class AutomergeRepairTests(unittest.TestCase):
    def test_incident_policy_matches_platform_automerge_and_deployment_targets(self):
        policy = tomllib.loads((ROOT / "compose/automerge-repair/policy.toml").read_text())
        expected = {"infrastructure": "infrastructure-dev", "homelab": "homelab"}
        for name, target in expected.items():
            repository = policy["repositories"][name]
            self.assertEqual(repository["full_name"], f"SpencerRWood/{name}")
            self.assertEqual(repository["renovate_login"], "renovate[bot]")
            self.assertEqual(repository["automerge_mode"], "platform-squash")
            self.assertEqual(repository["deployment_environments"], {"dev": target})
            self.assertFalse(repository["repair_enabled"])
            self.assertEqual(repository["rollback"], "notification-only")

    def test_only_dev_selects_a_digest_qualified_release(self):
        dev = yaml.safe_load((ROOT / "environments/dev.yml").read_text())
        prod = yaml.safe_load((ROOT / "environments/prod.yml").read_text())
        self.assertTrue(dev["services"]["automerge_repair"])
        self.assertRegex(
            dev["automerge_repair_image_ref"],
            r"^ghcr\.io/spencerrwood/automerge-repair:v\d+\.\d+\.\d+@sha256:[0-9a-f]{64}$",
        )
        self.assertFalse(prod["services"].get("automerge_repair", False))

    def test_code_location_is_private_and_uses_scoped_credentials(self):
        compose = yaml.safe_load((ROOT / "compose/automerge-repair/compose.yml").read_text())
        code = compose["services"]["automerge-repair-code"]
        self.assertNotIn("ports", code)
        self.assertEqual(code["env_file"], ["${AUTOMERGE_REPAIR_RUNTIME_ENV_FILE:?required}"])
        self.assertEqual(code["user"], "1000:1000")
        self.assertIn("policy.toml:ro", code["volumes"][0])
        self.assertNotIn("OPENPROJECT", str(code))
        self.assertNotIn("GOOGLE_DRIVE", str(code))

    def test_refresh_targets_only_the_code_location_and_scoped_secret(self):
        manifest = yaml.safe_load((ROOT / "environments/dev.yml").read_text())
        runtime = manifest["infrastructure_infisical_runtime_services"]["automerge-repair"]
        self.assertEqual(runtime["environment"], "dev")
        self.assertEqual(runtime["path"], "/automerge-repair")
        self.assertEqual(runtime["required_keys"], ["DAGSTER_POSTGRES_PASSWORD"])
        self.assertEqual(runtime["compose_services"], ["automerge-repair-code"])
        self.assertEqual(runtime["source"], "compose/automerge-repair/compose.yml")

    def test_workspace_registers_only_selected_code_location(self):
        source = (ROOT / "ansible/roles/dagster/templates/workspace.yaml.j2").read_text()
        environment = Environment()
        environment.filters["bool"] = bool
        template = environment.from_string(source)
        canonical = (ROOT / "compose/dagster/config/workspace.yaml").read_text()
        for selected in (False, True):
            rendered = template.render(
                lookup=lambda *args: canonical,
                role_path="unused",
                services={"automerge_repair": selected},
            )
            workspace = yaml.safe_load(rendered)
            names = [entry["grpc_server"]["location_name"] for entry in workspace["load_from"]]
            self.assertEqual("automerge-repair" in names, selected)
            self.assertEqual(len(names), len(set(names)))
