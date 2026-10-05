"""Credential parsing must fail closed and never include URI input in errors."""

import importlib.util
import unittest
from pathlib import Path
from urllib.parse import quote

PLUGIN = Path(__file__).parents[1] / "ansible/filter_plugins/postgres_application.py"
SPEC = importlib.util.spec_from_file_location("postgres_application", PLUGIN)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ApplicationCredentialTests(unittest.TestCase):
    def setUp(self):
        self.application = {
            "role": "events_service", "database": "events_service",
            "host": "192.168.1.21", "port": 25433,
            "url_scheme": "postgresql+psycopg",
        }
        self.password = "encoding-test-only:" + "@/'%+?#" * 4
        self.url = (
            "postgresql+psycopg://events_service:"
            + quote(self.password, safe="")
            + "@192.168.1.21:25433/events_service"
        )

    def test_uri_password_round_trip(self):
        self.assertEqual(
            MODULE.postgres_application_credential(self.url, self.application),
            {"password": self.password},
        )

    def test_reject_wrong_identity_endpoint_and_parameters_without_values(self):
        for value in (
            "", self.url.replace("192.168.1.21", "localhost"),
            self.url.replace("25433", "5432"),
            self.url.replace("events_service:", "postgres:"),
            self.url.replace("/events_service", "/postgres"),
            self.url + "?sslmode=disable",
            self.url.replace(quote(self.password, safe=""), "short"),
        ):
            with self.subTest(value_present=bool(value)):
                with self.assertRaises(MODULE.AnsibleFilterError) as error:
                    MODULE.postgres_application_credential(value, self.application)
                self.assertNotIn(self.password, str(error.exception))
                self.assertNotIn("postgresql+psycopg://", str(error.exception))

    def test_reject_sql_identifier_injection(self):
        application = {**self.application, "role": "events_service';--"}
        with self.assertRaises(MODULE.AnsibleFilterError):
            MODULE.postgres_application_credential(self.url, application)

    def test_native_postgresql_url_requires_explicit_selected_scheme(self):
        application = {
            **self.application, "role": "architecture_docs",
            "database": "architecture_docs", "url_scheme": "postgresql",
        }
        value = self.url.replace("postgresql+psycopg", "postgresql").replace(
            "events_service", "architecture_docs"
        )
        self.assertEqual(
            MODULE.postgres_application_credential(value, application),
            {"password": self.password},
        )
        for contract in (
            {**application, "url_scheme": "postgresql+psycopg"},
            {**application, "url_scheme": "unsupported"},
            {key: item for key, item in application.items() if key != "url_scheme"},
        ):
            with self.assertRaises(MODULE.AnsibleFilterError):
                MODULE.postgres_application_credential(value, contract)
