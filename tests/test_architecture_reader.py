"""Exercise the actual Ansible SQL against a disposable local PostgreSQL."""

import importlib.util
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location(
    "architecture_reader", ROOT / "ansible/filter_plugins/architecture_reader.py"
)
PLUGIN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PLUGIN)


class ReaderContractTests(unittest.TestCase):
    def test_reject_missing_ambiguous_or_injected_scope(self):
        valid = {"databases": [{"name": "application", "schemas": ["public"]}],
                 "infisical_path": "/documentation-automation"}
        self.assertEqual(PLUGIN.architecture_reader_contract(valid), valid)
        bad_databases = [[], valid["databases"] * 2, [{"name": "app';DROP ROLE postgres;--", "schemas": ["public"]}]]
        bad_databases += [[{"name": "application", "schemas": schemas}]
                          for schemas in ([], ["public", "public"], ["pg_catalog"], ["information_schema"], [None])]
        for patch in ([{"databases": databases} for databases in bad_databases] +
                      [{"infisical_path": "/wrong//path"}, {"extra": "unsupported"},
                       {"database": "obsolete_single_database"}]):
            with self.subTest(fields=list(patch)):
                with self.assertRaises(PLUGIN.AnsibleFilterError):
                    PLUGIN.architecture_reader_contract({**valid, **patch})
        with self.assertRaises(PLUGIN.AnsibleFilterError):
            PLUGIN.architecture_reader_contract({})

    def test_password_errors_do_not_include_inputs(self):
        for value in (None, "short", "CANARY-'" * 10, "CANARY\n" * 10):
            with self.assertRaises(PLUGIN.AnsibleFilterError) as error:
                PLUGIN.architecture_reader_password(value)
            self.assertNotIn("CANARY", str(error.exception))
        self.assertEqual(PLUGIN.architecture_reader_password("fixture_password_" * 4), "fixture_password_" * 4)


class ReaderPostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name in ("initdb", "pg_ctl", "psql"):
            if not shutil.which(name):
                raise unittest.SkipTest("Local PostgreSQL binaries unavailable")
        cls.temp = tempfile.TemporaryDirectory(prefix="architecture-reader-")
        cls.folder = Path(cls.temp.name)
        cls.data = cls.folder / "data"
        subprocess.run(["initdb", "-D", str(cls.data), "-U", "reader_test", "--auth=trust", "--no-locale"],
                       capture_output=True, check=True)
        hba = cls.data / "pg_hba.conf"
        hba.write_text("local all architecture_reader scram-sha-256\n" + hba.read_text())
        subprocess.run(["pg_ctl", "-D", str(cls.data), "-l", str(cls.folder / "postgres.log"),
                        "-o", f"-c listen_addresses='' -k {cls.folder}", "-w", "start"],
                       capture_output=True, check=True)
        cls.templates = Environment(
            loader=FileSystemLoader(ROOT / "ansible/roles/architecture_reader/templates"),
            undefined=StrictUndefined,
        )
        cls.templates.filters["architecture_reader_password"] = PLUGIN.architecture_reader_password
        cls.password = "synthetic_offline_reader_password_" * 2
        cls.database = {"name": "postgres", "schemas": ["fixture"]}

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["pg_ctl", "-D", str(cls.data), "-m", "fast", "-w", "stop"],
                       capture_output=True, check=True)
        cls.temp.cleanup()

    def sql(self, body, *, role="reader_test", password="", require_auth=False, database="postgres"):
        connection = "dbname=" + database + (" require_auth=scram-sha-256" if require_auth else "")
        return subprocess.run(
            ["psql", "-X", "-h", str(self.folder), "-U", role, "-d", connection, "-At", "--set=ON_ERROR_STOP=1"],
            input=body, text=True, capture_output=True,
            env={**os.environ, "PGPASSWORD": password},
        )

    def checked(self, body):
        result = self.sql(body)
        self.assertEqual(result.returncode, 0, "Disposable PostgreSQL setup/query failed")
        return result.stdout.strip()

    def setUp(self):
        self.checked("DROP DATABASE IF EXISTS service_two WITH (FORCE);")
        # Fresh application objects, with no data grants to PUBLIC.
        self.checked("DROP SCHEMA IF EXISTS fixture CASCADE; CREATE SCHEMA fixture; REVOKE ALL ON SCHEMA fixture FROM PUBLIC;")
        if self.checked("SELECT count(*) FROM pg_roles WHERE rolname='architecture_reader';") == "1":
            self.checked("DROP OWNED BY architecture_reader;")
        self.checked("DROP ROLE IF EXISTS architecture_reader; REVOKE ALL ON DATABASE postgres FROM PUBLIC; REVOKE ALL ON SCHEMA public FROM PUBLIC;")
        self.checked("CREATE TABLE fixture.parent (id integer PRIMARY KEY); CREATE TABLE fixture.child (id integer PRIMARY KEY, parent_id integer REFERENCES fixture.parent(id)); INSERT INTO fixture.parent VALUES (1);")

    def rendered(self, *, password=None, authenticated=False, name="reader.sql.j2", database=None, index=0):
        return self.templates.get_template(name).render(
            architecture_reader_database=database or self.database,
            architecture_reader_database_index=index,
            architecture_reader_authentication={"rc": 0 if authenticated else 2},
            architecture_reader_resolved={"stdout": password or self.password},
        )

    def provision(self, **kwargs):
        result = self.sql(self.rendered(**kwargs))
        self.assertEqual(result.returncode, 0, "Reader provisioning failed in disposable PostgreSQL")
        self.assertNotIn(self.password, result.stdout + result.stderr)
        return result

    def test_idempotency_metadata_denial_and_rotation(self):
        self.provision()
        first = self.checked("SELECT rolpassword FROM pg_authid WHERE rolname='architecture_reader';")
        verify = self.sql(self.rendered(name="verify.sql.j2"), role="architecture_reader",
                          password=self.password, require_auth=True)
        self.assertEqual(verify.returncode, 0, "Metadata reader verification failed")
        self.assertIn("parent_id", verify.stdout)
        self.assertIn("|f", verify.stdout)
        denied = self.sql("SELECT * FROM fixture.parent;", role="architecture_reader",
                          password=self.password, require_auth=True)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn("permission denied", denied.stderr)
        repeated = self.provision(authenticated=True)
        self.assertNotIn("ALTER ROLE", repeated.stdout)
        self.assertNotIn("GRANT", repeated.stdout)
        self.assertEqual(self.checked("SELECT rolpassword FROM pg_authid WHERE rolname='architecture_reader';"), first)
        rotated = "rotated_synthetic_reader_password_" * 2
        self.provision(password=rotated)
        self.assertNotEqual(self.sql("SELECT 1;", role="architecture_reader", password=self.password, require_auth=True).returncode, 0)
        self.assertEqual(self.sql("SELECT 1;", role="architecture_reader", password=rotated, require_auth=True).returncode, 0)

    def test_authentication_preflight_allows_reconciliation_but_rejects_unsafe_transport(self):
        tasks = yaml.safe_load((ROOT / "ansible/roles/architecture_reader/tasks/main.yml").read_text())
        task = next(item for item in tasks if item["name"] ==
                    "Check whether the current Infisical password already authenticates")
        fails = self.templates.compile_expression(task["failed_when"])

        def rejected(result):
            return fails(architecture_reader_authentication={
                "rc": result.returncode, "stderr": result.stderr,
            })

        missing = self.sql("SELECT 1;", role="architecture_reader", password=self.password)
        self.assertNotEqual(missing.returncode, 0)
        self.assertFalse(rejected(missing))
        self.provision()
        wrong = self.sql("SELECT 1;", role="architecture_reader", password="wrong_fixture_password")
        self.assertNotEqual(wrong.returncode, 0)
        self.assertFalse(rejected(wrong))
        valid = self.sql("SELECT 1;", role="architecture_reader", password=self.password)
        self.assertEqual(valid.returncode, 0)
        self.assertFalse(rejected(valid))
        # A trust-authenticated success must pass the second, mandatory SCRAM
        # probe before provisioning; require_auth masks both wrong-password
        # and trust errors behind the same generic libpq diagnostic.
        trust = self.sql("SELECT 1;")
        self.assertEqual(trust.returncode, 0)
        scram_task = next(item for item in tasks if item["name"] ==
                         "Require SCRAM before trusting a successful credential probe")
        enabled = self.templates.compile_expression(scram_task["when"][1])
        self.assertTrue(enabled(architecture_reader_authentication={"rc": trust.returncode}))
        self.assertIn("require_auth=scram-sha-256", " ".join(scram_task["ansible.builtin.command"]["argv"]))
        self.assertNotEqual(self.sql("SELECT 1;", require_auth=True).returncode, 0)
        self.assertTrue(fails(architecture_reader_authentication={
            "rc": 2, "stderr": "connection timed out",
        }))

    def test_public_table_and_column_access_fail_and_rollback(self):
        for grant, revoke in [("GRANT SELECT ON fixture.parent TO PUBLIC;", "REVOKE SELECT ON fixture.parent FROM PUBLIC;"),
                              ("GRANT SELECT(id) ON fixture.parent TO PUBLIC;", "REVOKE SELECT(id) ON fixture.parent FROM PUBLIC;")]:
            self.checked(grant)
            result = self.sql(self.rendered())
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(self.password, result.stderr + result.stdout)
            self.assertEqual(self.checked("SELECT count(*) FROM pg_roles WHERE rolname='architecture_reader';"), "0")
            self.checked(revoke)

    def test_privileged_existing_role_is_not_repurposed(self):
        self.checked("CREATE ROLE architecture_reader SUPERUSER;")
        result = self.sql(self.rendered())
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.checked("SELECT rolsuper FROM pg_roles WHERE rolname='architecture_reader';"), "t")

    def test_membership_and_callable_definer_fail_closed(self):
        self.checked("CREATE ROLE architecture_reader LOGIN; GRANT reader_test TO architecture_reader;")
        self.assertNotEqual(self.sql(self.rendered()).returncode, 0)
        self.checked("REVOKE reader_test FROM architecture_reader; DROP ROLE architecture_reader;")
        self.checked("CREATE FUNCTION fixture.unsafe() RETURNS integer LANGUAGE sql SECURITY DEFINER AS 'SELECT 1';")
        self.assertNotEqual(self.sql(self.rendered()).returncode, 0)

    def test_database_public_temp_access_fails_without_changing_public(self):
        self.checked("GRANT TEMPORARY ON DATABASE postgres TO PUBLIC;")
        self.assertNotEqual(self.sql(self.rendered()).returncode, 0)
        self.assertEqual(self.checked("SELECT has_database_privilege('public', 'postgres', 'TEMPORARY');"), "t")

    def test_multiple_databases_share_one_password_and_excluded_database_is_rejected(self):
        self.provision()
        verifier = self.checked("SELECT rolpassword FROM pg_authid WHERE rolname='architecture_reader';")
        self.checked("CREATE DATABASE service_two;")
        setup = self.sql("REVOKE ALL ON DATABASE service_two FROM PUBLIC; REVOKE ALL ON SCHEMA public FROM PUBLIC; "
                         "CREATE SCHEMA fixture; CREATE TABLE fixture.private_data (id integer PRIMARY KEY);",
                         database="service_two")
        self.assertEqual(setup.returncode, 0)
        second = {"name": "service_two", "schemas": ["fixture"]}
        result = self.sql(self.rendered(database=second, index=1), database="service_two")
        self.assertEqual(result.returncode, 0, "Second database provisioning failed")
        self.assertNotIn("ALTER ROLE", result.stdout)
        self.assertEqual(self.checked("SELECT rolpassword FROM pg_authid WHERE rolname='architecture_reader';"), verifier)
        hba = self.data / "pg_hba.conf"
        original = hba.read_text()
        rules = self.templates.get_template("reader-hba.j2").render(
            architecture_reader_allowed_databases="postgres,service_two"
        )
        hba.write_text(rules + "\n" + original)
        self.checked("SELECT pg_reload_conf();")
        try:
            for database in ("postgres", "service_two"):
                verification = self.sql(self.rendered(name="verify.sql.j2", database={"name": database, "schemas": ["fixture"]}),
                                        database=database, role="architecture_reader", password=self.password, require_auth=True)
                self.assertEqual(verification.returncode, 0, "Shared credential metadata verification failed")
                denied = self.sql("SELECT * FROM fixture." + ("parent" if database == "postgres" else "private_data"),
                                  database=database, role="architecture_reader", password=self.password, require_auth=True)
                self.assertNotEqual(denied.returncode, 0)
                self.assertIn("permission denied", denied.stderr)
            excluded = self.sql("SELECT 1", database="template1", role="architecture_reader", password=self.password, require_auth=True)
            self.assertNotEqual(excluded.returncode, 0)
            self.assertIn("pg_hba.conf rejects", excluded.stderr)
        finally:
            hba.write_text(original)
            self.checked("SELECT pg_reload_conf();")
