"""Exercise Events image/readiness checks and environment-scoped secret identity."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).parents[1]


class EventsHealthTests(unittest.TestCase):
    def run_health(self, image: str, health: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'caddy.env').write_text('CADDY_HTTP_BIND=127.0.0.1:8080\n')
            (root / 'events.env').write_text('EVENTS_SERVICE_IMAGE_REF=expected-digest\n')
            (root / 'rag.env').write_text(
                'RAG_SERVICE_IMAGE_REF=expected-digest\n'
                'RAG_SERVICE_SOURCE_REVISION=source\nRAG_SERVICE_RELEASE_TAG=v1\n'
            )
            docker = root / 'docker'
            docker.write_text(
                '#!/usr/bin/env bash\n'
                'case "$1" in\n'
                'ps) echo container;;\n'
                'inspect) if [[ "$*" == *State.Health.Status* ]]; then echo healthy; '
                'elif [[ "$2" == --format ]]; then echo "$FAKE_IMAGE"; '
                'else echo \'{"Running": true, "Status": "healthy"}\'; fi;;\n'
                'exec) exit "$FAKE_HEALTH";;\n'
                'image) if [[ "$*" == *Config.Labels* ]]; then echo source; else echo "$FAKE_IMAGE"; fi;;\n'
                'esac\n'
            )
            docker.chmod(0o755)
            curl = root / 'curl'
            curl.write_text('#!/usr/bin/env bash\necho -n 200\n')
            curl.chmod(0o755)
            return subprocess.run(
                ['bash', str(ROOT / 'scripts/health-check-dev-remote.sh')],
                env={
                    **os.environ,
                    'PATH': str(root) + ':' + os.environ['PATH'],
                    'HEALTH_CHECK_CADDY_ENV_FILE': str(root / 'caddy.env'),
                    'HEALTH_CHECK_EVENTS_ENV_FILE': str(root / 'events.env'),
                    'HEALTH_CHECK_RAG_ENV_FILE': str(root / 'rag.env'),
                    'HEALTH_CHECK_AUTOMERGE_ENV_FILE': str(root / 'unselected-automerge.env'),
                    'HEALTH_CHECK_RETRY_INTERVAL': '0',
                    'FAKE_IMAGE': image,
                    'FAKE_HEALTH': health,
                },
                text=True, capture_output=True, timeout=5, check=False,
            )

    def test_both_services_require_the_expected_image_and_readiness(self):
        result = self.run_health('expected-digest', '0')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('OK Events Service wood-broker image and readiness', result.stdout)
        self.assertIn('OK Events Service wood-notify image and readiness', result.stdout)

    def test_image_drift_and_database_unreadiness_fail_health(self):
        for image, health in [('wrong-digest', '0'), ('expected-digest', '1')]:
            with self.subTest(image=image, health=health):
                result = self.run_health(image, health)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('OK Events Service', result.stdout)

    def test_host_automerge_selection_does_not_enter_events_fixture(self):
        with tempfile.TemporaryDirectory() as directory:
            host_env = Path(directory) / 'host-automerge.env'
            host_env.write_text('AUTOMERGE_REPAIR_IMAGE_REF=host-only-image\n')
            with patch.dict(os.environ, {'HEALTH_CHECK_AUTOMERGE_ENV_FILE': str(host_env)}):
                result = self.run_health('expected-digest', '0')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('OK Automerge Repair', result.stdout)


class ResolverEnvironmentTests(unittest.TestCase):
    def test_resolver_never_uses_dev_identity_for_production(self):
        spec = importlib.util.spec_from_file_location(
            'events_test_resolver', ROOT / 'scripts/resolve-infisical-env.py'
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for environment in ['dev', 'prod']:
            observed = []

            def protected(path):
                observed.append(path)
                raise RuntimeError('stop before reading credentials')

            args = SimpleNamespace(
                environment=environment, path='/events-service',
                require=['WES_DATABASE_URL'],
                output='/srv/infrastructure/secrets/runtime/events-service-broker.env',
            )
            # Patch umask as well: this diagnostic must not mutate process state.
            with patch.object(module.os, 'geteuid', return_value=0), \
                 patch.object(module.os, 'umask'), patch.object(module, 'protected', protected):
                with self.assertRaises(RuntimeError):
                    module.resolve(args)
            self.assertEqual(observed, [Path(
                '/srv/infrastructure/secrets/bootstrap/infisical-' + environment + '.json'
            )])


if __name__ == '__main__':
    unittest.main()
