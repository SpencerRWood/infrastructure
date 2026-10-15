"""Exercise the scoped deployment health gate without touching a host."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'ghcr.io/spencerrwood/wood-design-system:v0.1.0@sha256:' + 'a' * 64


class WDSHealthTests(unittest.TestCase):
    def probe(self, **overrides):
        with tempfile.TemporaryDirectory() as temporary:
            commands = {
                'sed': '''#!/bin/sh
case "$*" in
  *WDS_IMAGE_REF*) printf '%s\\n' "$EXPECTED_IMAGE" ;;
  *CADDY_HTTP_BIND*) echo 127.0.0.1:8080 ;;
  *) exit 1 ;;
esac
''',
                'docker': '''#!/bin/sh
case "$*" in
  'ps '*) echo test-container ;;
  *'.Config.Image'*) printf '%s\\n' "$OBSERVED_IMAGE" ;;
  *'.State.Health.Status'*) printf '%s\\n' "$OBSERVED_HEALTH" ;;
  *) exit 1 ;;
esac
''',
                'curl': '''#!/bin/sh
case "$*" in
  *'/components') printf '%s' "$ROUTE_STATUS" ;;
  *) printf 200 ;;
esac
''',
            }
            for name, contents in commands.items():
                path = Path(temporary) / name
                path.write_text(contents)
                path.chmod(0o755)
            environment = {
                **os.environ,
                'PATH': temporary + os.pathsep + os.environ['PATH'],
                'EXPECTED_IMAGE': IMAGE,
                'OBSERVED_IMAGE': IMAGE,
                'OBSERVED_HEALTH': 'healthy',
                'ROUTE_STATUS': '200',
                **overrides,
            }
            return subprocess.run(
                ['bash', str(ROOT / 'scripts/health-check-wood-design-system.sh')],
                env=environment, capture_output=True, text=True, timeout=5,
            )

    def test_healthy_exact_digest_and_all_routes_pass(self):
        self.assertEqual(self.probe().returncode, 0)

    def test_different_container_identity_is_rejected(self):
        self.assertNotEqual(self.probe(OBSERVED_IMAGE=IMAGE.replace('a' * 64, 'b' * 64)).returncode, 0)

    def test_unhealthy_container_is_rejected(self):
        self.assertNotEqual(self.probe(OBSERVED_HEALTH='unhealthy').returncode, 0)

    def test_failed_documentation_route_is_rejected(self):
        self.assertNotEqual(self.probe(ROUTE_STATUS='404').returncode, 0)
