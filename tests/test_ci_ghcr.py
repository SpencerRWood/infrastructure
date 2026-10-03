"""Registry resolution must support a folder with multiple CI credentials."""

from pathlib import Path
import runpy
import unittest


RESOLVER = runpy.run_path(str(Path(__file__).parents[1] / 'scripts/resolve-ci-ghcr.py'))
SELECT = RESOLVER['select_credential']
KEY = RESOLVER['KEY']


class CiGhcrTests(unittest.TestCase):
    def test_unrelated_credentials_do_not_block_registry_resolution(self):
        registry = {'secretKey': KEY, 'secretValue': 'registry-value'}
        promotion = {'secretKey': 'INFRASTRUCTURE_PR_TOKEN', 'secretValue': 'promotion-value'}
        for entries in ([registry], [promotion, registry], [registry, promotion]):
            with self.subTest(entries=len(entries)):
                self.assertEqual(SELECT({'secrets': entries}), 'registry-value')

    def test_missing_or_duplicate_registry_credential_is_rejected(self):
        registry = {'secretKey': KEY, 'secretValue': 'registry-value'}
        for entries in ([], [{'secretKey': 'OTHER', 'secretValue': 'other'}], [registry, registry]):
            with self.subTest(entries=len(entries)):
                with self.assertRaises(ValueError):
                    SELECT({'secrets': entries})

    def test_invalid_registry_value_is_rejected(self):
        for value in ('', None, 123, 'value\n', 'value\r'):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    SELECT({'secrets': [{'secretKey': KEY, 'secretValue': value}]})


if __name__ == '__main__':
    unittest.main()
