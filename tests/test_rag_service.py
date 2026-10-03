"""Check the RAG deployment's credential and persistence boundaries."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).parents[1]


class RagServiceTests(unittest.TestCase):
    def test_migration_and_platform_secrets_are_not_in_the_api(self):
        compose = yaml.safe_load((ROOT / "compose/rag-service/compose.yml").read_text())
        api = compose["services"]["rag-service"]
        code = compose["services"]["rag-service-code"]
        migration = compose["services"]["rag-service-migrate"]
        self.assertEqual(api["env_file"], ["${RAG_SERVICE_RUNTIME_ENV_FILE:?required}"])
        self.assertNotIn("${RAG_SERVICE_MIGRATION_ENV_FILE:?required}", code["env_file"])
        self.assertEqual(migration["env_file"], ["${RAG_SERVICE_MIGRATION_ENV_FILE:?required}"])
        self.assertEqual(migration["networks"], ["postgres"])
        self.assertNotIn("volumes", migration)
        self.assertEqual(api["image"], code["image"])
        self.assertEqual(api["image"], migration["image"])
        self.assertEqual(api["volumes"][0], code["volumes"][0])
        self.assertIn("/data/documents", api["volumes"][0])

    def test_dagster_location_has_no_tracking_credentials(self):
        source = (ROOT / "compose/rag-service/compose.yml").read_text()
        self.assertNotIn("secrets/runtime/dagster.env", source)
        self.assertNotIn("OPENPROJECT", source)
        self.assertNotIn("GOOGLE_DRIVE", source)


if __name__ == "__main__":
    unittest.main()
