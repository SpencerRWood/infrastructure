"""Events health and rollback operations run against fake host commands only."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
IMAGE = 'ghcr.io/spencerrwood/events-service:v0.6.0@sha256:' + 'a' * 64


class EventsScopedOperationsTests(unittest.TestCase):
    def test_health_checks_both_exact_images_and_ready_endpoints(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = root / 'events.env'
            environment.write_text('EVENTS_SERVICE_PROJECT_NAME=events-test\n'
                                   f'EVENTS_SERVICE_IMAGE_REF={IMAGE}\n')
            docker = root / 'docker'
            docker.write_text('''#!/bin/sh
case "$*" in
  'ps '*) echo test-container ;;
  *'.Config.Image'*) printf '%s\n' "$OBSERVED_IMAGE" ;;
  *'.State.Health.Status'*) printf '%s\n' "$OBSERVED_HEALTH" ;;
  *) exit 1 ;;
esac
''')
            curl = root / 'curl'
            curl.write_text('#!/bin/sh\nexit "$HTTP_RESULT"\n')
            docker.chmod(0o755)
            curl.chmod(0o755)
            for image, health, http_result, expected in (
                    (IMAGE, 'healthy', '0', 0),
                    (IMAGE.replace('a' * 64, 'b' * 64), 'healthy', '0', 1),
                    (IMAGE, 'unhealthy', '0', 1),
                    (IMAGE, 'healthy', '22', 1)):
                with self.subTest(image=image, health=health, http=http_result):
                    result = subprocess.run(
                        ['bash', str(ROOT / 'scripts/health-check-events-service.sh')],
                        env={**os.environ, 'PATH': temporary + os.pathsep + os.environ['PATH'],
                             'HEALTH_CHECK_EVENTS_ENV_FILE': str(environment),
                             'OBSERVED_IMAGE': image, 'OBSERVED_HEALTH': health,
                             'HTTP_RESULT': http_result},
                        text=True, capture_output=True, timeout=5, check=False)
                    self.assertEqual(result.returncode == 0, expected == 0, result.stderr)

    def test_rollback_stops_before_apply_when_schema_is_unknown_or_evidence_blocks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            script = root / 'rollback-events-service.sh'
            script.write_text((ROOT / 'scripts/rollback-events-service.sh').read_text().replace(
                '/usr/bin/python3', sys.executable))
            for name, content in {
                'git': '#!/bin/sh\nprintf "events_service_image_ref: %s\\n" "$OLD_IMAGE"\n',
                'docker': '''#!/bin/sh
case "$1" in
  run) printf '%s\n' "$OLD_SCHEMA" ;;
  compose)
    case "$*" in
      *' stop '*) echo writers-stopped >&2; exit 0 ;;
      *' up '*) echo writers-resumed >&2; exit 0 ;;
      *) echo guarded-migration-attempt >&2; exit 73 ;;
    esac ;;
  *) exit 99 ;;
esac
''',
            }.items():
                command = root / name
                command.write_text(content)
                command.chmod(0o755)
            for schema, attempted in (('unreviewed-schema', False),
                                      ('0005_recovery_parts', True),
                                      ('0006_interactive_edits', True)):
                result = subprocess.run(
                    ['bash', str(script), 'v0.9.99'],
                    env={**os.environ, 'PATH': temporary + os.pathsep + os.environ['PATH'],
                         'OLD_IMAGE': IMAGE, 'OLD_SCHEMA': schema},
                    text=True, capture_output=True, timeout=5, check=False)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual('guarded-migration-attempt' in result.stderr, attempted)
                self.assertEqual('writers-stopped' in result.stderr, attempted)
                self.assertEqual('writers-resumed' in result.stderr, attempted)
                if attempted:
                    self.assertLess(result.stderr.index('writers-stopped'),
                                    result.stderr.index('guarded-migration-attempt'))


if __name__ == '__main__':
    unittest.main()
