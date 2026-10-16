"""Canonical backup YAML, schema, coverage and mutation-safety contracts."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from recovery_manifest import InvalidBackup, read_yaml
SPEC = importlib.util.spec_from_file_location('configuration', ROOT / 'scripts/validate-backups.py')
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)
SOURCE = ROOT / 'environments/dev.yml'


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.config = read_yaml(SOURCE)['backups_configuration']

    def test_canonical_yaml_and_policy_enumerate_all_configured_targets(self):
        result = VALIDATOR.verify(SOURCE)
        self.assertEqual(result['status'], 'passed')
        self.assertFalse(result['retention_pruning_enabled'])
        self.assertIn(self.config['postgres']['required_databases'][0], result['targets'])

    def test_dev_redeploy_retains_approved_exception_without_claiming_independent_custody(self):
        defaults = read_yaml(ROOT / 'ansible/roles/backups/defaults/main.yml')
        self.assertFalse(defaults['backups_quiesce_authorized'])
        self.assertFalse(defaults['backups_temporary_operator_custody_authorized'])
        executable = shutil.which('ansible-playbook')
        self.assertIsNotNone(executable)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            playbook = root / 'verify.yml'
            playbook.write_text(yaml.safe_dump([{
                'hosts': 'localhost', 'gather_facts': False,
                'vars_files': [str(SOURCE)],
                'tasks': [{'ansible.builtin.assert': {'that': [
                    'backups_quiesce_authorized | bool',
                    'backups_temporary_operator_custody_authorized | bool',
                    'not backups_configuration.independent_custody_verified | bool',
                    'not backups_configuration.retention.pruning_enabled | bool',
                ]}}],
            }]))
            result = subprocess.run([
                executable, '-i', 'localhost,', '-c', 'local', str(playbook), '--check',
            ], capture_output=True, text=True, timeout=30, env=os.environ | {
                'ANSIBLE_CONFIG': str(ROOT / 'recovery/ansible.cfg'),
                'ANSIBLE_LOCAL_TEMP': str(root / 'local'),
                'ANSIBLE_REMOTE_TEMP': str(root / 'remote'),
            })
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_invalid_runtime_configuration_fails_before_backup_side_effects(self):
        for mutate in (
                lambda c: c['postgres'].update(password_source='legacy-fallback'),
                lambda c: c['retention'].update(pruning_enabled=True),
                lambda c: c.update(max_age_seconds='86400'),
                lambda c: c['files'][0].update(paths=['relative/source']),
                lambda c: c['files'][0].update(sqlite_engine='unsupported')):
            with self.subTest(mutate=mutate), tempfile.TemporaryDirectory() as temporary:
                config = copy.deepcopy(self.config)
                mutate(config)
                path = Path(temporary) / 'config.json'
                path.write_text(json.dumps(config))
                result = subprocess.run([
                    sys.executable, str(ROOT / 'scripts/recovery-backup.py'),
                    '--config', str(path), '--schema', str(ROOT / 'recovery/backup-config.schema.json'),
                    '--validate-config'], capture_output=True, text=True, timeout=10)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('backup_configuration_schema_invalid', result.stderr)

    def test_coverage_drift_and_duplicate_targets_fail(self):
        for duplicate in (False, True):
            config = copy.deepcopy(self.config)
            config['files'].append({'id': config['files'][0]['id'] if duplicate else 'new-state',
                                    'paths': ['/absolute/new-state']})
            with tempfile.TemporaryDirectory() as temporary:
                path = Path(temporary) / 'configuration.yml'
                path.write_text(yaml.safe_dump({'backups_configuration': config}))
                with self.assertRaises(InvalidBackup):
                    VALIDATOR.verify(path)

    def test_duplicate_yaml_keys_fail_instead_of_overriding_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'configuration.yml'
            path.write_text('consumer: homelab\nconsumer: infrastructure\n')
            with self.assertRaisesRegex(InvalidBackup, 'backup_yaml_duplicate_key'):
                read_yaml(path)


if __name__ == '__main__':
    unittest.main()
