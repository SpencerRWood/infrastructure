"""A healthy verifier must not silently evaluate a stale consumer selection."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location('selection', ROOT / 'scripts/verify-recovery-consumers.py')
SELECTION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SELECTION)


class ConsumerSelectionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.checkout = self.root / 'homelab'
        (self.checkout / 'scripts').mkdir(parents=True)
        self.target = {'id': 'homelab', 'revision': 'a' * 40,
                       'backup_sources': [{'id': 'current_recovery_group', 'reference': 'path:///backups/current.json'}]}
        self.config = {'manifest_json': json.dumps({'schema_version': '1', 'targets': [self.target]}),
                       'checkouts': {'homelab': '/opt/recovery/checkouts/homelab'},
                       'manifest_exports': {'homelab': {'entrypoint': 'scripts/recovery.py', 'args': ['manifest'], 'timeout_seconds': 10}}}
        self.path = self.root / 'config.json'
        self.path.write_text(json.dumps(self.config))

    def process(self, target):
        return subprocess.CompletedProcess([], 0, stdout=json.dumps({'schema_version': '1', 'targets': [target]}))

    def test_exact_reviewed_export_passes(self):
        with patch.object(SELECTION.subprocess, 'run', return_value=self.process(self.target)):
            result = SELECTION.verify(self.path, self.root)
        self.assertEqual(result['state'], 'passed')
        self.assertEqual(result['consumers'][0]['revision'], 'a' * 40)

    def test_preparation_preserves_controls_and_updates_only_reviewed_identity(self):
        self.config['cadence'] = {'daily': '0 6 * * *'}
        self.config['notifications_enabled'] = True
        self.path.write_text(json.dumps(self.config))
        updated = self.target | {'revision': 'b' * 40}
        with patch.object(SELECTION.subprocess, 'run', return_value=self.process(updated)):
            result = SELECTION.verify(self.path, self.root, prepare=True)
        self.assertEqual(result['configuration']['cadence'], self.config['cadence'])
        self.assertTrue(result['configuration']['notifications_enabled'])
        self.assertEqual(json.loads(result['configuration']['manifest_json'])['targets'], [updated])
        self.assertEqual(json.loads(self.path.read_text()), self.config)

    def test_preparation_rejects_different_consumer(self):
        with patch.object(SELECTION.subprocess, 'run', return_value=self.process(self.target | {'id': 'other'})):
            with self.assertRaisesRegex(ValueError, 'identity_selection_mismatch'):
                SELECTION.verify(self.path, self.root, prepare=True)

    def test_old_revision_and_old_backup_pointer_are_rejected(self):
        for changed in ({'revision': 'b' * 40}, {'backup_sources': [{'id': 'migration_snapshot', 'reference': 'path:///old'}]}):
            with self.subTest(changed=changed), patch.object(SELECTION.subprocess, 'run', return_value=self.process(self.target | changed)):
                with self.assertRaisesRegex(ValueError, 'selection_mismatch'):
                    SELECTION.verify(self.path, self.root)

    def test_symlink_checkout_is_rejected_before_invocation(self):
        alias = self.root / 'alias'
        alias.symlink_to(self.checkout, target_is_directory=True)
        self.config['checkouts']['homelab'] = '/opt/recovery/checkouts/alias'
        self.path.write_text(json.dumps(self.config))
        with patch.object(SELECTION.subprocess, 'run') as command:
            with self.assertRaisesRegex(ValueError, 'unsafe'):
                SELECTION.verify(self.path, self.root)
        command.assert_not_called()

    def test_missing_or_oversized_export_never_passes(self):
        for process in (subprocess.CalledProcessError(2, 'export'), self.process(self.target)):
            with self.subTest(process=type(process).__name__):
                if isinstance(process, subprocess.CalledProcessError):
                    mock = patch.object(SELECTION.subprocess, 'run', side_effect=process)
                    error = subprocess.CalledProcessError
                else:
                    process.stdout = 'x' * 65537
                    mock = patch.object(SELECTION.subprocess, 'run', return_value=process)
                    error = ValueError
                with mock, self.assertRaises(error):
                    SELECTION.verify(self.path, self.root)

    def test_selection_gate_precedes_runtime_and_secret_mutations(self):
        import yaml
        tasks = yaml.safe_load((ROOT / 'ansible/roles/recovery_verification/tasks/main.yml').read_text())
        names = [task['name'] for task in tasks]
        guard = names.index('Verify reviewed consumer manifests before changing the runtime')
        self.assertLess(guard, names.index('Register selected Recovery Verification with the existing secret refresh service'))
        self.assertLess(guard, names.index('Install reviewed non-secret recovery orchestration configuration'))
        self.assertEqual(tasks[guard]['become_user'], 'root')
        self.assertIn('--reuid=10001', tasks[guard]['ansible.builtin.command']['argv'])
        self.assertIn('--clear-groups', tasks[guard]['ansible.builtin.command']['argv'])
        self.assertFalse(tasks[guard]['changed_when'])


if __name__ == '__main__':
    unittest.main()
