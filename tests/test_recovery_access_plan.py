"""One exact authorization request never grants values or broad project access."""
import importlib.util
from pathlib import Path
import unittest
import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('access_plan', ROOT / 'scripts/prepare-recovery-access.py')
ACCESS = importlib.util.module_from_spec(spec); spec.loader.exec_module(ACCESS)


class AccessPlanTests(unittest.TestCase):
    def test_grants_are_metadata_only_at_exact_names_and_never_applied(self):
        from unittest.mock import patch
        import json
        plan = {'project_mapping': {'Infrastructure Dev': 'a', 'Homelab': 'b', 'CI': 'c'},
                'metadata_identity': {'name': 'recovery-verification-metadata'}, 'required_runtime_names': []}
        catalog = {'services': {'app': {'environment': 'dev', 'path': '/app', 'required_keys': ['KEY']}}}
        with patch.object(ACCESS.Path, 'read_text', side_effect=[json.dumps(plan), json.dumps(catalog)]), \
                patch.object(ACCESS, 'read_yaml', return_value={'infisical_runtime_services': {}}):
            result = ACCESS.prepare(ROOT, ROOT)
        self.assertFalse(result['applied'])
        self.assertFalse(result['values_access'])
        self.assertEqual({g['action'] for g in result['grants']}, {'describeSecret'})
        self.assertTrue(all(set(g['conditions']) == {'environment', 'secretPath', 'secretName'} for g in result['grants']))
        self.assertEqual(result['registry_reader']['scopes'], ['read:packages'])
        self.assertFalse(result['registry_reader']['repository_access'])


if __name__ == '__main__':
    unittest.main()
