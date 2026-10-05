"""Provisioning resolves one canonical value in memory without creating a cache."""

import argparse
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[1] / "scripts/resolve-infisical-env.py"
SPEC = importlib.util.spec_from_file_location("infisical_value", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class InfisicalValueTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.identity = self.root / "infisical-dev.json"
        self.identity.write_text(json.dumps({
            "api_url": "https://infisical.example.test", "project_id": "project",
            "client_id": "fixture-client", "client_secret": "fixture-secret",
        }))
        self.args = argparse.Namespace(
            environment="dev", path="/architecture-docs", output=None,
            stdout_key="ARCHITECTURE_DOCS_DATABASE_URL",
            require=["ARCHITECTURE_DOCS_DATABASE_URL"],
        )

    def run_resolver(self, value, returncode=0):
        opener = mock.Mock()
        opener.open.return_value = io.BytesIO(b'{"accessToken":"fixture-token"}')
        result = mock.Mock(returncode=returncode, stdout=value)
        output = io.StringIO()
        with (
            mock.patch.object(MODULE, "IDENTITY", self.identity),
            mock.patch.object(MODULE, "RUNTIME_ROOT", self.root / "never-created"),
            mock.patch.object(MODULE, "protected") as protected,
            mock.patch.object(MODULE.os, "geteuid", return_value=0),
            mock.patch.object(MODULE.urllib.request, "build_opener", return_value=opener),
            mock.patch.object(MODULE.subprocess, "run", return_value=result) as run,
            redirect_stdout(output),
        ):
            MODULE.resolve(self.args)
        return output.getvalue(), run, protected

    def test_selected_value_is_returned_without_files_or_fallback(self):
        value = "postgresql://architecture_docs:fixture@192.168.1.21:25433/architecture_docs"
        output, run, protected = self.run_resolver(value + "\n")
        self.assertEqual(output, value + "\n")
        self.assertFalse((self.root / "never-created").exists())
        self.assertEqual(list(self.root.iterdir()), [self.identity])
        protected.assert_called_once_with(self.identity)
        command = run.call_args.args[0]
        self.assertEqual(command[:4], [
            "infisical", "secrets", "get", "ARCHITECTURE_DOCS_DATABASE_URL",
        ])
        self.assertIn("--include-imports=false", command)
        self.assertIn("--secret-overriding=false", command)
        self.assertNotIn("--output-file", " ".join(command))
        self.assertEqual(run.call_args.kwargs["env"]["INFISICAL_TOKEN"], "fixture-token")

    def test_missing_secret_or_invalid_value_never_uses_existing_environment(self):
        with mock.patch.dict(MODULE.os.environ, {
            "ARCHITECTURE_DOCS_DATABASE_URL": "fixture-stale-value",
        }):
            for value, code in (("", 1), ("", 0), ("value\nextra", 0)):
                with self.subTest(code=code, multiline="\n" in value):
                    with self.assertRaises(ValueError):
                        self.run_resolver(value, code)
        self.assertFalse((self.root / "never-created").exists())

    def test_stdout_requires_only_the_selected_key(self):
        self.args.require.append("OTHER_SECRET")
        with self.assertRaisesRegex(ValueError, "exactly the selected key"):
            self.run_resolver("fixture")
