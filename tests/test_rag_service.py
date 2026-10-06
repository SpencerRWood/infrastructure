"""Check the RAG deployment's credential and persistence boundaries."""

from pathlib import Path
import os
import subprocess
import unittest
from uuid import uuid4

import yaml
from dagster._core.instance.config import dagster_instance_config


ROOT = Path(__file__).parents[1]


class RagServiceTests(unittest.TestCase):
    @unittest.skipUnless(
        os.environ.get("RAG_TEST_POSTGRES_CONTAINER"),
        "Requires a disposable PostgreSQL/pgvector container",
    )
    def test_extension_provisioning_preserves_restricted_migration_identity(self):
        container = os.environ["RAG_TEST_POSTGRES_CONTAINER"]
        name = "rag_fixture_" + uuid4().hex
        tasks = yaml.safe_load((ROOT / "ansible/roles/rag_service/tasks/main.yml").read_text())
        provision = next(task for task in tasks if "rag_service_vector_extension" == task.get("register"))

        def sql(database, statement, user="postgres", check=True):
            return subprocess.run(
                ["docker", "exec", "-i", container, "psql", "-X", "-U", user,
                 "-d", database, "-At", "--set=ON_ERROR_STOP=1"],
                input=statement, text=True, capture_output=True, check=check,
            )

        sql("postgres", f"CREATE ROLE {name} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE;\nCREATE DATABASE {name} OWNER {name};")
        try:
            denied = sql(name, "CREATE EXTENSION vector WITH SCHEMA public;", name, check=False)
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("superuser", denied.stderr)
            first = sql(name, provision["ansible.builtin.command"]["stdin"])
            self.assertIn("CREATE EXTENSION", first.stdout)
            repeat = sql(name, provision["ansible.builtin.command"]["stdin"])
            self.assertNotIn("CREATE EXTENSION", repeat.stdout)
            result = sql(name, "CREATE TABLE vectors (embedding vector(2));\nINSERT INTO vectors VALUES ('[1,0]');\nSELECT 1 - (embedding <=> '[1,0]'::vector) FROM vectors;", name)
            self.assertEqual(result.stdout.splitlines()[-1], "1")
            privileges = sql("postgres", f"SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname='{name}';")
            self.assertEqual(privileges.stdout.strip(), "f|f|f")
        finally:
            sql("postgres", f"DROP DATABASE {name};\nDROP ROLE {name};")

    def test_shared_runtime_accepts_worker_monitoring_configuration(self):
        config, _ = dagster_instance_config(str(ROOT / "compose/dagster/config"))
        self.assertTrue(config["run_monitoring"]["enabled"])

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

    def test_embedding_is_independent_private_and_shared_by_both_rag_roles(self):
        compose = yaml.safe_load((ROOT / "compose/rag-service/compose.yml").read_text())
        embedding = compose["services"]["embedding-service"]
        self.assertEqual(embedding["image"], "${RAG_EMBEDDING_IMAGE_REF:?required}")
        self.assertNotIn("ports", embedding)
        self.assertNotIn("env_file", embedding)
        self.assertEqual(set(embedding["networks"]), {"embedding", "model-download"})
        self.assertTrue(compose["networks"]["embedding"]["internal"])
        self.assertIn(":/data/models", embedding["volumes"][0])
        for role in ("rag-service", "rag-service-code"):
            service = compose["services"][role]
            settings = service["environment"]
            self.assertEqual(settings["RAG_EMBEDDING_ENDPOINT"], "http://embedding-service:8080/v1")
            self.assertEqual(settings["RAG_EMBEDDING_MODEL"], "Qwen/Qwen3-Embedding-0.6B")
            self.assertEqual(settings["RAG_EMBEDDING_DIMENSIONS"], "1024")
            self.assertIn("embedding", service["networks"])
            self.assertEqual(service["depends_on"]["embedding-service"]["condition"], "service_healthy")


if __name__ == "__main__":
    unittest.main()
