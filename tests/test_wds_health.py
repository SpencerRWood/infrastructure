"""Exercise the scoped deployment health gate without touching a host."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from jinja2 import Environment, StrictUndefined


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


class WDSInitialRollbackTests(unittest.TestCase):
    def wrapper(self, operation, *, running='', outside=False, installed_route=None):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / ('outside' if outside else 'runner/_work/infrastructure/infrastructure')
            (workspace / '.git').mkdir(parents=True)
            secret = root / 'runner-input'
            secret.write_text('')
            binary = root / 'bin'
            binary.mkdir()
            for name, content in {
                'env': '#!/bin/sh\nprintf "%s\\n" "$*"\n',
                'docker': '#!/bin/sh\nprintf "%s" "$WDS_RUNNING"\n',
            }.items():
                path = binary / name
                path.write_text(content)
                path.chmod(0o755)
            source = (ROOT / 'ansible/roles/github_runner/templates/deploy-wrapper.sh.j2').read_text()
            rendered = Environment(undefined=StrictUndefined).from_string(source).render(
                github_runner_root=str(root / 'runner'),
                github_runner_ansible_config_path='ansible/ansible.cfg',
                github_runner_secret_file=str(secret),
                github_runner_inventory_path='ansible/inventory/dev',
                github_runner_playbook_path='ansible/playbooks/dev.yml',
                github_runner_ansible_extra_args='',
                github_runner_health_command='false',
            )
            # The runner executes this suite on the real deployment host. Keep
            # rollback-baseline filesystem probes inside the disposable fixture,
            # just like Docker, so installed host routes cannot affect the test.
            for index, route in enumerate((
                    '/srv/infrastructure/compose/caddy/routes/wood-design-system.caddy',
                    '/srv/docker/proxy/config/sites/wood-design-system.caddy')):
                fixture = root / f'installed-route-{index}'
                rendered = rendered.replace(route, str(fixture))
                if installed_route == index:
                    fixture.write_text('fixture route remains installed\n')
            script = root / 'wrapper'
            script.write_text(rendered)
            return subprocess.run(['bash', str(script), str(workspace), operation],
                env={**os.environ, 'PATH':str(binary) + os.pathsep + os.environ['PATH'],
                     'WDS_RUNNING':running}, capture_output=True, text=True, timeout=5)

    def test_old_release_uses_only_installed_scoped_rollback(self):
        result = self.wrapper('apply-wood-design-system')
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(),
                         'WDS_ROLLBACK_APPROVED=true /usr/local/sbin/github-runner-infrastructure-wds-rollback')

    def test_old_release_health_rejects_a_remaining_wds_container(self):
        self.assertEqual(self.wrapper('health-wood-design-system').returncode, 0)
        self.assertNotEqual(self.wrapper('health-wood-design-system', running='stale-container').returncode, 0)

    def test_old_release_health_rejects_each_remaining_route_without_a_container(self):
        for route in (0, 1):
            with self.subTest(route=route):
                self.assertNotEqual(self.wrapper('health-wood-design-system', installed_route=route).returncode, 0)

    def test_workspace_boundary_is_preserved(self):
        result = self.wrapper('apply-wood-design-system', outside=True)
        self.assertEqual(result.returncode, 64)
        self.assertEqual(result.stdout, '')
