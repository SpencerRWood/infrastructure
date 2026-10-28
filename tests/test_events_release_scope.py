"""Automatic Events deployment never authorizes unrelated configuration or rollback."""

from copy import deepcopy
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('events_scope', ROOT / 'scripts/events_release_scope.py')
scope = importlib.util.module_from_spec(spec)
spec.loader.exec_module(scope)


class EventsReleaseScopeTests(unittest.TestCase):
    def setUp(self):
        self.before = {'events_service_image_ref':
                       'ghcr.io/spencerrwood/events-service:v0.6.0@sha256:' + 'a' * 64,
                       'services': {'events_service': True, 'postgres': True},
                       'another_image_ref': 'unchanged'}
        self.after = deepcopy(self.before)
        self.after['events_service_image_ref'] = (
            'ghcr.io/spencerrwood/events-service:v0.7.0@sha256:' + 'b' * 64)

    def test_only_forward_immutable_events_pin_can_authorize(self):
        self.assertTrue(scope.image_only(self.before, self.after))
        for change in (
                {'another_image_ref': 'changed'},
                {'services': {'events_service': False, 'postgres': True}},
                {'events_service_image_ref': self.before['events_service_image_ref']},
                {'events_service_image_ref': 'ghcr.io/spencerrwood/events-service:v0.7.0'},
                {'events_service_image_ref': self.after['events_service_image_ref'].replace('v0.7.0', 'v0.5.0')},
                {'events_service_image_ref': self.after['events_service_image_ref'].replace('events-service', 'another')},
                {'new_setting': True}):
            with self.subTest(change=change):
                self.assertFalse(scope.image_only(self.before, {**self.after, **change}))

    def test_release_checkout_and_unique_published_tag_are_required(self):
        sha = 'a' * 40
        with patch.object(scope, 'git', side_effect=[sha, 'environments/dev.yml',
                yaml.safe_dump(self.before), yaml.safe_dump(self.after), 'v0.9.99']):
            observed = scope.observe(ROOT, sha)
        self.assertTrue(observed['approved'])
        self.assertEqual(observed['release_tag'], 'v0.9.99')
        for tags in ('', 'v0.9.99\nv0.9.100'):
            with patch.object(scope, 'git', side_effect=[sha, 'environments/dev.yml',
                    yaml.safe_dump(self.before), yaml.safe_dump(self.after), tags]):
                with self.assertRaisesRegex(ValueError, 'unique_published'):
                    scope.observe(ROOT, sha)
        with patch.object(scope, 'git', return_value='b' * 40):
            with self.assertRaisesRegex(ValueError, 'checkout_mismatch'):
                scope.observe(ROOT, sha)

    def test_other_files_and_mixed_configuration_cannot_deploy(self):
        sha = 'a' * 40
        with patch.object(scope, 'git', side_effect=[sha, 'environments/dev.yml\nREADME.md']):
            self.assertFalse(scope.observe(ROOT, sha)['approved'])
        with patch.object(scope, 'git', side_effect=[sha, 'environments/dev.yml',
                yaml.safe_dump(self.before), yaml.safe_dump({**self.after, 'extra': True})]):
            self.assertFalse(scope.observe(ROOT, sha)['approved'])

    def test_workflow_gates_deployment_and_privilege_is_events_only(self):
        workflow = yaml.safe_load((ROOT / '.github/workflows/deploy-events.yml').read_text())
        trigger = workflow['on']['workflow_run']
        self.assertEqual(trigger['workflows'], ['Release'])
        self.assertEqual(trigger['branches'], ['main'])
        self.assertIn("conclusion == 'success'", workflow['jobs']['scope']['if'])
        deploy = workflow['jobs']['deploy-events']
        self.assertEqual(deploy['if'], "needs.scope.outputs.approved == 'true'")
        self.assertEqual(deploy['permissions']['actions'], 'write')
        dispatch = deploy['steps'][0]['run']
        self.assertIn('gh workflow run deploy.yml', dispatch)
        self.assertIn('--field deployment_approved=true', dispatch)
        self.assertIn('--field events_service_only=true', dispatch)
        manual = yaml.safe_load((ROOT / '.github/workflows/deploy.yml').read_text())
        self.assertFalse(manual['on']['workflow_dispatch']['inputs']['events_service_only']['default'])
        component = manual['jobs']['deploy-dev']['with']
        self.assertIn('apply-events-service', component['privileged_deploy_command'])
        self.assertIn('health-events-service', component['privileged_health_check_command'])
        self.assertIn('rollback-events-service', component['privileged_rollback_command'])
        self.assertIn('events-service-dev.json', component['deployment_state_file'])
        self.assertIn('WDS_ONLY', manual['jobs']['deployment-scope']['steps'][0]['run'])
        wrapper = (ROOT / 'ansible/roles/github_runner/templates/deploy-wrapper.sh.j2').read_text()
        for operation in ('apply-events-service', 'check-events-service'):
            body = wrapper.split(f'  {operation})', 1)[1].split(';;', 1)[0]
            self.assertIn('--tags events_service', body)


if __name__ == '__main__':
    unittest.main()
