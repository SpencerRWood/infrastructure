"""Exercise the deployed health script with deterministic route responses."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "health-check-dev-remote.sh"
INFISICAL_ROUTE = "dev-infisical.woodhost.cloud/api/status"


class HealthCheckTests(unittest.TestCase):
    def run_health_check(self, responses: str) -> tuple[subprocess.CompletedProcess[str], int]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            bin_directory = root / "bin"
            bin_directory.mkdir()
            (root / "caddy.env").write_text("CADDY_HTTP_BIND=127.0.0.1:8080\n", encoding="utf-8")
            docker = bin_directory / "docker"
            docker.write_text(
                '#!/usr/bin/env bash\n'
                'if [[ "$1" == ps ]]; then echo container1; else echo \'{"Running": true, "Status": "healthy"}\'; fi\n',
                encoding="utf-8",
            )
            docker.chmod(0o755)
            curl = bin_directory / "curl"
            curl.write_text(
                f"#!{sys.executable}\n"
                "import os, pathlib, sys\n"
                "args = sys.argv[1:]\n"
                "host = next(arg.removeprefix('Host: ') for arg in args if arg.startswith('Host: '))\n"
                "if host != 'dev-infisical.woodhost.cloud':\n"
                "    print('200', end='')\n"
                "    sys.exit(0)\n"
                "count_file = pathlib.Path(os.environ['FAKE_CURL_COUNT'])\n"
                "count = int(count_file.read_text()) if count_file.exists() else 0\n"
                "count_file.write_text(str(count + 1))\n"
                "responses = os.environ['FAKE_CURL_RESPONSES'].split(',')\n"
                "response = responses[min(count, len(responses) - 1)]\n"
                "if response == 'exit7':\n"
                "    print('curl: (7) Connection refused', file=sys.stderr)\n"
                "    print('000', end='')\n"
                "    sys.exit(7)\n"
                "print(response, end='')\n",
                encoding="utf-8",
            )
            curl.chmod(0o755)
            count_file = root / "curl-count"
            environment = {
                **os.environ,
                "PATH": f"{bin_directory}:{os.environ['PATH']}",
                "HEALTH_CHECK_CADDY_ENV_FILE": str(root / "caddy.env"),
                "HEALTH_CHECK_ROUTE_ATTEMPTS": "3",
                "HEALTH_CHECK_RETRY_INTERVAL": "0",
                "FAKE_CURL_RESPONSES": responses,
                "FAKE_CURL_COUNT": str(count_file),
            }
            result = subprocess.run(
                ["bash", str(SCRIPT)],
                env=environment,
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            return result, int(count_file.read_text()) if count_file.exists() else 0

    def test_transient_502_then_success(self) -> None:
        for responses in ("502,502,200", "500,503,200"):
            with self.subTest(responses=responses):
                result, attempts = self.run_health_check(responses)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(attempts, 3)
                self.assertIn(f"OK infrastructure Caddy route {INFISICAL_ROUTE}", result.stdout)

    def test_persistent_502_fails_with_route_and_status(self) -> None:
        result, attempts = self.run_health_check("502")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(attempts, 3)
        self.assertIn(INFISICAL_ROUTE, result.stderr)
        self.assertIn("HTTP 502", result.stderr)

    def test_connection_refusal_fails_with_route_and_curl_error(self) -> None:
        result, attempts = self.run_health_check("exit7")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(attempts, 3)
        self.assertIn(INFISICAL_ROUTE, result.stderr)
        self.assertIn("curl exit 7", result.stderr)

    def test_bad_endpoint_does_not_hang(self) -> None:
        result, attempts = self.run_health_check("404")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(attempts, 3)
        self.assertIn("HTTP 404", result.stderr)


if __name__ == "__main__":
    unittest.main()
