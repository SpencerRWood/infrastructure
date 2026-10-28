"""Ensure validation, publication and rollback require distinct authority."""

from pathlib import Path
import json
import tomllib
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1] / '.github/workflows'


class WorkflowGovernanceTests(unittest.TestCase):
    def test_github_flow_configuration_agrees_without_planning_release(self):
        root = ROOT.parents[1]
        project = tomllib.loads((root / 'pyproject.toml').read_text())
        self.assertEqual(project['tool']['wood']['branching'], {'strategy': 'trunk'})
        self.assertEqual(project['tool']['semantic_release']['branches'],
                         {'main': {'match': '^main$', 'prerelease': False}})
        capability = tomllib.loads((root / '.github/release.toml').read_text())
        self.assertEqual(capability['branching']['policy'], 'infrastructure')
        renovate = json.loads((root / 'renovate.json').read_text())
        self.assertEqual(renovate['baseBranchPatterns'], ['main'])
        routing = yaml.safe_load((ROOT / 'routing.yml').read_text())
        self.assertEqual(routing['on']['pull_request']['branches'], ['main'])

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
        self.assertEqual(triggers['push']['branches'], ['main'])
        self.assertEqual(triggers['pull_request']['branches'], ['main'])
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

    def test_validation_publishes_the_existing_promotion_status_for_trusted_sources(self):
        validate = yaml.safe_load((ROOT / 'validate.yml').read_text())
        job = validate['jobs']['validation']
        self.assertIn('/validate.yml@', job['uses'])
        self.assertEqual(job['with']['workflow_revision'], job['uses'].split('@')[1])
        self.assertEqual(job['with']['status_context'], 'infrastructure-validation')
        self.assertIn('head.repo.full_name == github.repository', job['with']['publish_commit_status'])
        self.assertIn("github.event_name == 'pull_request' &&", job['with']['publish_commit_status'])
        self.assertEqual(validate['permissions'], {'contents': 'read', 'statuses': 'write'})


if __name__ == '__main__':
    unittest.main()
