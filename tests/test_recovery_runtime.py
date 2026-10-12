"""Recovery code-location registration cannot enable runtime activation by itself."""

import json
from pathlib import Path
import unittest

from jinja2 import Environment
import yaml


ROOT = Path(__file__).parents[1]


class RecoveryRuntimeTests(unittest.TestCase):
    def test_runtime_selection_is_dev_only_with_immutable_image(self):
        production = yaml.safe_load((ROOT / 'environments/prod.yml').read_text())
        self.assertFalse(production['services']['recovery_verification'])
        self.assertNotIn('recovery_verification_image_ref', production)
        development = yaml.safe_load((ROOT / 'environments/dev.yml').read_text())
        self.assertTrue(development['services']['recovery_verification'])
        self.assertRegex(development['recovery_verification_image_ref'],
                         r'^ghcr\.io/spencerrwood/recovery-verification:v\d+\.\d+\.\d+@sha256:[0-9a-f]{64}$')
        config = json.loads((ROOT / 'environments/recovery-verification-dev.json').read_text())
        self.assertEqual(config['environment'], 'infrastructure-dev')
        self.assertFalse(config['isolated_test_mode'])
        self.assertFalse(config['notifications_enabled'])
        manifest = json.loads(config['manifest_json'])
        targets = {target['id'] for target in manifest['targets']}
        self.assertEqual(targets, set(config['checkouts']))
        self.assertEqual(targets, set(config['manifest_exports']))

    def test_workspace_respects_explicit_selection(self):
        source = (ROOT / 'ansible/roles/dagster/templates/workspace.yaml.j2').read_text()
        environment = Environment()
        environment.filters['bool'] = bool
        canonical = (ROOT / 'compose/dagster/config/workspace.yaml').read_text()
        for selected in (False, True):
            workspace = yaml.safe_load(environment.from_string(source).render(
                lookup=lambda *args: canonical, role_path='unused',
                services={'recovery_verification': selected},
            ))
            names = [entry['grpc_server']['location_name'] for entry in workspace['load_from']]
            self.assertEqual('recovery-verification' in names, selected)

    def test_runtime_is_isolated_with_durable_history(self):
        code = yaml.safe_load((ROOT / 'compose/recovery-verification/compose.yml').read_text())['services']['recovery-verification-code']
        self.assertEqual(code['user'], '10001:10001')
        self.assertTrue(code['read_only'])
        self.assertEqual(code['tmpfs'], [
            '/tmp',
            '/home/app/.ansible:rw,nosuid,nodev,size=64m,uid=10001,gid=10001,mode=0700',
        ])
        self.assertEqual(code['cap_drop'], ['ALL'])
        self.assertEqual(code['security_opt'], ['no-new-privileges:true'])
        self.assertNotIn('ANSIBLE_LOCAL_TEMP', code['environment'])
        self.assertNotIn('ports', code)
        self.assertNotIn('/var/run/docker.sock', str(code))
        self.assertIn('${RECOVERY_CHECKOUTS_PATH:?required}:/opt/recovery/checkouts:ro', code['volumes'])
        self.assertIn('${RECOVERY_STORAGE_PATH:?required}:/mnt/wood-server-nas:ro', code['volumes'])
        self.assertIn('${RECOVERY_STATE_PATH:?required}:/opt/recovery/state', code['volumes'])
        self.assertIn('recovery-verification-health', code['healthcheck']['test'][-1])

    def test_deployment_requires_published_digest_and_runtime_configuration(self):
        tasks = yaml.safe_load((ROOT / 'ansible/roles/recovery_verification/tasks/main.yml').read_text())
        contract = tasks[0]['ansible.builtin.assert']['that']
        self.assertIn("infrastructure_environment == 'dev'", contract)
        self.assertIn('sha256', str(contract))
        self.assertIn('recovery_verification_config_source', str(contract))
        resolver = next(t for t in tasks if t['name'].startswith('Resolve scoped'))
        self.assertTrue(resolver['no_log'])
        self.assertEqual(resolver['when'], 'not ansible_check_mode')
        start = next(t for t in tasks if t['name'].startswith('Start and health'))
        self.assertEqual(start['when'], 'not ansible_check_mode')
        self.assertIn('--wait', start['ansible.builtin.command']['argv'])

    def test_selected_runtime_registers_scoped_refresh_without_dropping_other_services(self):
        defaults = yaml.safe_load((ROOT / 'ansible/roles/recovery_verification/defaults/main.yml').read_text())
        contract = defaults['recovery_verification_secret_contract']
        self.assertEqual(contract['path'], '/recovery-verification')
        self.assertEqual(contract['required_keys'], ['DAGSTER_POSTGRES_PASSWORD'])
        self.assertEqual(contract['compose_services'], ['recovery-verification-code'])
        tasks = yaml.safe_load((ROOT / 'ansible/roles/recovery_verification/tasks/main.yml').read_text())
        registration = next(t for t in tasks if t['name'].startswith('Register selected'))
        content = registration['ansible.builtin.copy']['content']
        self.assertIn('infrastructure_infisical_runtime_services | combine(', content)
        deploy = yaml.safe_load((ROOT / 'ansible/playbooks/deploy.yml').read_text())[0]
        self.assertEqual(deploy['tasks'][-1]['ansible.builtin.include_role']['name'], 'recovery_verification')
        self.assertIn('services.recovery_verification', deploy['tasks'][-1]['when'])
