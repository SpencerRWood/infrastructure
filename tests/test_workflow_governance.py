"""Ensure validation, publication and rollback require distinct authority."""

from pathlib import Path
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1] / '.github/workflows'


class WorkflowGovernanceTests(unittest.TestCase):
    def test_only_main_integration_or_approved_dispatch_can_publish(self):
        release = yaml.safe_load((ROOT / 'release.yml').read_text())
        triggers = release.get('on', release.get(True))
        self.assertEqual(set(triggers), {'workflow_dispatch', 'push'})
        self.assertEqual(triggers['push']['branches'], ['main'])
        self.assertFalse(triggers['workflow_dispatch']['inputs']['release_approved']['default'])
        self.assertEqual(set(release['jobs']), {'release'})
        job = release['jobs']['release']
        self.assertIn("github.ref == 'refs/heads/main'", job['if'])
        self.assertIn("github.event_name == 'workflow_dispatch'", job['if'])
        self.assertIn('inputs.release_approved == true', job['if'])
        self.assertIn("github.event_name == 'push'", job['if'])
        self.assertEqual(job['with']['require_approval'], "${{ github.event_name == 'workflow_dispatch' }}")
        self.assertEqual(job['with']['approved'], '${{ inputs.release_approved == true }}')

    def test_deployment_and_rollback_remain_separately_manual(self):
        deploy = yaml.safe_load((ROOT / 'deploy.yml').read_text())
        triggers = deploy.get('on', deploy.get(True))
        self.assertEqual(set(triggers), {'workflow_dispatch', 'workflow_call'})
        for trigger in triggers.values():
            self.assertFalse(trigger['inputs']['deployment_approved']['default'])
        self.assertIn('release', triggers['workflow_dispatch']['inputs'])
        for job in deploy['jobs'].values():
            self.assertIn("github.ref == 'refs/heads/main'", job['if'])
            self.assertIn("github.event_name == 'workflow_dispatch'", job['if'])
            self.assertIn('inputs.deployment_approved == true', job['if'])
        job = next(job for job in deploy['jobs'].values() if 'deploy-ansible' in job['uses'])
        self.assertTrue(job['with']['require_approval'])
        self.assertEqual(job['with']['approved'], '${{ inputs.deployment_approved }}')

    def test_pushes_and_prs_validate_without_publishing_authority(self):
        validate = yaml.safe_load((ROOT / 'validate.yml').read_text())
        triggers = validate.get('on', validate.get(True))
        self.assertEqual(set(triggers), {'push', 'pull_request'})
        self.assertEqual(triggers['push']['branches'], ['development'])
        self.assertEqual(triggers['pull_request']['branches'], ['development', 'main'])
        self.assertEqual(validate['permissions']['contents'], 'read')
        for job in validate['jobs'].values():
            self.assertIn('/validate.yml@', job['uses'])

    def test_recovery_rollback_cannot_apply_from_automatic_events(self):
        rollback = yaml.safe_load((ROOT / 'rollback.yml').read_text())
        triggers = rollback.get('on', rollback.get(True))
        self.assertEqual(set(triggers), {'workflow_call', 'workflow_dispatch'})
        for trigger in triggers.values():
            self.assertFalse(trigger['inputs']['apply']['default'])
        job = rollback['jobs']['rollback']
        self.assertIn('inputs.apply != true', job['if'])
        self.assertIn("github.event_name == 'workflow_dispatch'", job['if'])
        self.assertIn("github.ref == 'refs/heads/main'", job['if'])
        self.assertIn('self-hosted', job['runs-on'])
        self.assertTrue(any('scripts/rollback.py' in step.get('run', '') for step in job['steps']))

    def test_validation_uses_standard_actions_check_without_status_write(self):
        validate = yaml.safe_load((ROOT / 'validate.yml').read_text())
        job = validate['jobs']['validation']
        self.assertIn('/validate.yml@', job['uses'])
        self.assertEqual(job['with'], {'workflow_revision': job['uses'].split('@')[1]})
        self.assertEqual(validate['permissions'], {'contents': 'read'})


if __name__ == '__main__':
    unittest.main()
