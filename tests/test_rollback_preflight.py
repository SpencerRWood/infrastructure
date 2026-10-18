"""Isolated regression for the v0.32.1 automatic rollback custody failure."""

import copy
import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('preflight', ROOT / 'scripts/rollback-preflight.py')
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)


class RollbackCustodyTests(unittest.TestCase):
    def target(self, directory, independent=False, binding=True):
        root = Path(directory)
        sources = ['ansible/roles/backups/defaults/main.yml', 'environments/dev.yml',
                   'ansible/roles/recovery_verification/tasks/main.yml', 'recovery/ansible.cfg']
        for source in sources:
            path = root / source
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text((ROOT / source).read_text())
        environment = yaml.safe_load((ROOT / 'environments/dev.yml').read_text())
        environment = copy.deepcopy(environment)
        environment['backups_configuration']['independent_custody_verified'] = independent
        if not binding:
            # v0.32.1 contained the nested approval but omitted its role binding.
            environment.pop('backups_temporary_operator_custody_authorized')
        (root / 'environments/dev.yml').write_text(yaml.safe_dump(environment))
        for args in (['init', '-q'], ['add', '.'],
                     ['-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                      '-c', 'commit.gpgsign=false', 'commit', '-qm', 'fixture'],
                     ['tag', 'v0.1.0']):
            subprocess.run(['git', *args], cwd=root, check=True, capture_output=True)
        return root

    def test_missing_binding_blocks_even_with_nested_temporary_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.target(directory, binding=False)
            with self.assertRaises(subprocess.CalledProcessError):
                PREFLIGHT.check(root, 'v0.1.0')

    def test_existing_approved_binding_passes_without_changing_custody(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.target(directory)
            before = subprocess.check_output(['git', 'status', '--porcelain'], cwd=root)
            self.assertEqual(len(PREFLIGHT.check(root, 'v0.1.0')), 40)
            self.assertEqual(subprocess.check_output(['git', 'status', '--porcelain'], cwd=root), before)

    def test_independent_custody_passes_without_temporary_approval(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.target(directory, independent=True, binding=False)
            self.assertEqual(len(PREFLIGHT.check(root, 'v0.1.0')), 40)

    def test_missing_or_mutable_release_blocks(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.target(directory)
            for ref in ('', 'main', 'v9.9.9'):
                with self.subTest(ref=ref), self.assertRaises((ValueError, subprocess.CalledProcessError)):
                    PREFLIGHT.check(root, ref)
