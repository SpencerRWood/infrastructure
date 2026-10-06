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
WEBSITE_ROUTE = "dev-website-portfolio.woodhost.cloud/health"


class HealthCheckTests(unittest.TestCase):
    def run_health_check(
        self,
        responses: str,
        target_host: str = "dev-infisical.woodhost.cloud",
        report_present: bool = True,
        report_healthy: bool = True,
        report_inspect_broken_pipe: bool = False,
        rag_present: bool = True,
        rag_healthy: bool = True,
        rag_image_matches: bool = True,
        rag_running_image_matches: bool = True,
        rag_api_ready: bool = True,
        automerge_selected: bool = False,
        automerge_present: bool = True,
        automerge_healthy: bool = True,
        automerge_image_matches: bool = True,
        automerge_grpc_ready: bool = True,
    ) -> tuple[subprocess.CompletedProcess[str], int]:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            bin_directory = root / "bin"
            bin_directory.mkdir()
            (root / "caddy.env").write_text("CADDY_HTTP_BIND=127.0.0.1:8080\n", encoding="utf-8")
            (root / "rag.env").write_text(
                "RAG_SERVICE_IMAGE_REF=syntax-only/rag:v1@sha256:fixture\n"
                "RAG_SERVICE_SOURCE_REVISION=source\nRAG_SERVICE_RELEASE_TAG=v1\n"
            )
            if automerge_selected:
                (root / "automerge.env").write_text("AUTOMERGE_REPAIR_IMAGE_REF=syntax-only/automerge:test\n")
            docker = bin_directory / "docker"
            docker.write_text(
                '#!/usr/bin/env bash\n'
                'if [[ "$1" == ps ]]; then\n'
                '  if [[ "$*" == *automerge-repair-code* ]]; then\n'
                '    [[ "$FAKE_AUTOMERGE_PRESENT" == true ]] && echo automerge1\n'
                '  elif [[ "$*" == *rag-service-code* ]]; then\n'
                '    [[ "$FAKE_RAG_PRESENT" == true ]] && echo rag1\n'
                '  elif [[ "$*" == *service=rag-service* ]]; then echo ragapi1\n'
                '  elif [[ "$*" == *openproject-reports-code* ]]; then\n'
                '    [[ "$FAKE_REPORT_PRESENT" == true ]] && echo report1\n'
                '  else echo container1; fi\n'
                '  exit 0\n'
                'elif [[ "$1" == exec && "$2" == automerge1 ]]; then\n'
                '  [[ "$FAKE_AUTOMERGE_GRPC_READY" == true ]]; exit $?\n'
                'elif [[ "$1" == exec && "$2" == ragapi1 ]]; then\n'
                '  [[ "$FAKE_RAG_API_READY" == true ]]; exit $?\n'
                'elif [[ "$*" == *rag* && "$*" == *Config.Image* ]]; then\n'
                '  if [[ "$FAKE_RAG_IMAGE_MATCHES" == true ]]; then echo syntax-only/rag:v1@sha256:fixture; else echo wrong; fi\n'
                'elif [[ "$*" == *rag* && "$*" == *.Image* ]]; then\n'
                '  if [[ "$FAKE_RAG_RUNNING_IMAGE_MATCHES" == true ]]; then echo image-id; else echo wrong; fi\n'
                'elif [[ "$1" == image && "$*" == *Config.Labels* ]]; then echo source\n'
                'elif [[ "$1" == image && "$*" == *.Id* ]]; then echo image-id\n'
                'elif [[ "$*" == *automerge1* && "$*" == *Config.Image* ]]; then\n'
                '  if [[ "$FAKE_AUTOMERGE_IMAGE_MATCHES" == true ]]; then echo syntax-only/automerge:test; else echo wrong; fi\n'
                'elif [[ "$*" == *automerge1* && "$*" == *State.Health.Status* ]]; then\n'
                '  if [[ "$FAKE_AUTOMERGE_HEALTHY" == true ]]; then echo healthy; else echo unhealthy; fi\n'
                'elif [[ "$*" == *report1* && "$*" == *State.Health.Status* ]]; then\n'
                '  if [[ "$FAKE_REPORT_HEALTHY" == true ]]; then echo healthy; else echo unhealthy; fi\n'
                'elif [[ "$*" == *rag1* && "$*" == *State.Health.Status* ]]; then\n'
                '  if [[ "$FAKE_RAG_HEALTHY" == true ]]; then echo healthy; else echo unhealthy; fi\n'
                'elif [[ "$2" == report1 && "$FAKE_REPORT_INSPECT_BROKEN_PIPE" == true ]]; then\n'
                '  echo \'{"Running": true, "Status": "healthy"}\'; exit 141\n'
                'elif [[ "$2" == rag1 && "$FAKE_RAG_HEALTHY" != true ]]; then\n'
                '  echo \'{"Running": true, "Status": "unhealthy"}\'\n'
                'elif [[ "$2" == report1 && "$FAKE_REPORT_HEALTHY" != true ]]; then\n'
                '  echo \'{"Running": true, "Status": "unhealthy"}\'\n'
                'else echo \'{"Running": true, "Status": "healthy"}\'; fi\n',
                encoding="utf-8",
            )
            docker.chmod(0o755)
            curl = bin_directory / "curl"
            curl.write_text(
                f"#!{sys.executable}\n"
                "import os, pathlib, sys\n"
                "args = sys.argv[1:]\n"
                "host = next(arg.removeprefix('Host: ') for arg in args if arg.startswith('Host: '))\n"
                "if host != os.environ['FAKE_CURL_TARGET_HOST']:\n"
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
                "HEALTH_CHECK_EVENTS_ENV_FILE": str(root / "events-compose.env"),
                "HEALTH_CHECK_ROUTE_ATTEMPTS": "3",
                "HEALTH_CHECK_KEYCLOAK_ROUTE_ATTEMPTS": "3",
                "HEALTH_CHECK_RETRY_INTERVAL": "0",
                "FAKE_CURL_RESPONSES": responses,
                "FAKE_CURL_TARGET_HOST": target_host,
                "FAKE_CURL_COUNT": str(count_file),
                "FAKE_REPORT_PRESENT": str(report_present).lower(),
                "FAKE_REPORT_HEALTHY": str(report_healthy).lower(),
                "FAKE_REPORT_INSPECT_BROKEN_PIPE": str(report_inspect_broken_pipe).lower(),
                "FAKE_RAG_PRESENT": str(rag_present).lower(),
                "FAKE_RAG_HEALTHY": str(rag_healthy).lower(),
                "HEALTH_CHECK_RAG_ENV_FILE": str(root / "rag.env"),
                "FAKE_RAG_IMAGE_MATCHES": str(rag_image_matches).lower(),
                "FAKE_RAG_RUNNING_IMAGE_MATCHES": str(rag_running_image_matches).lower(),
                "FAKE_RAG_API_READY": str(rag_api_ready).lower(),
                "HEALTH_CHECK_AUTOMERGE_ENV_FILE": str(root / "automerge.env"),
                "FAKE_AUTOMERGE_PRESENT": str(automerge_present).lower(),
                "FAKE_AUTOMERGE_HEALTHY": str(automerge_healthy).lower(),
                "FAKE_AUTOMERGE_IMAGE_MATCHES": str(automerge_image_matches).lower(),
                "FAKE_AUTOMERGE_GRPC_READY": str(automerge_grpc_ready).lower(),
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

    def test_selected_automerge_requires_exact_image_and_grpc_readiness(self) -> None:
        result, _ = self.run_health_check("200", automerge_selected=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK Automerge Repair image and gRPC readiness", result.stdout)
        for failure in (
            {"automerge_present": False},
            {"automerge_healthy": False},
            {"automerge_image_matches": False},
            {"automerge_grpc_ready": False},
        ):
            with self.subTest(failure=failure):
                result, _ = self.run_health_check("200", automerge_selected=True, **failure)
                self.assertNotEqual(result.returncode, 0)

    def test_rag_database_readiness_must_succeed_after_liveness(self) -> None:
        result, attempts = self.run_health_check("200,503,503,503", target_host="dev-rag-service.woodhost.cloud")
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(attempts, 4)
        self.assertIn("dev-rag-service.woodhost.cloud/knowledge-bases?limit=1", result.stderr)

    def test_rag_requires_exact_artifact_and_core_readiness(self) -> None:
        result, _ = self.run_health_check("200")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK RAG immutable image, revision, and core readiness", result.stdout)
        for failure in (
            {"rag_image_matches": False},
            {"rag_running_image_matches": False},
            {"rag_api_ready": False},
        ):
            with self.subTest(failure=failure):
                result, _ = self.run_health_check("200", **failure)
                self.assertNotEqual(result.returncode, 0)

    def test_rag_code_server_must_be_present_and_healthy(self) -> None:
        for present, healthy in ((False, True), (True, False)):
            with self.subTest(present=present, healthy=healthy):
                result, _ = self.run_health_check("200", rag_present=present, rag_healthy=healthy)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("RAG Service Dagster code server is not healthy", result.stderr)

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

    def test_website_route_failure_blocks_deployment_health(self) -> None:
        result, attempts = self.run_health_check(
            "502", target_host="dev-website-portfolio.woodhost.cloud"
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(attempts, 3)
        self.assertIn(WEBSITE_ROUTE, result.stderr)
        self.assertIn("HTTP 502", result.stderr)

    def test_missing_report_code_server_blocks_deployment_health(self) -> None:
        result, _ = self.run_health_check("200", report_present=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("OpenProject Reports Dagster code server is not healthy", result.stderr)

    def test_health_state_read_avoids_full_inspection_broken_pipe(self) -> None:
        result, _ = self.run_health_check("200", report_inspect_broken_pipe=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("OK OpenProject Reports Dagster code server", result.stdout)

    def test_unhealthy_report_code_server_blocks_deployment_health(self) -> None:
        result, _ = self.run_health_check("200", report_healthy=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("OpenProject Reports Dagster code server is not healthy", result.stderr)


if __name__ == "__main__":
    unittest.main()
