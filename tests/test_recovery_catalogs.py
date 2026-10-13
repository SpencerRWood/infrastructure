"""Recovery inventories include every selected dependency with explicit evidence."""
import json
from pathlib import Path
import re
import unittest
import yaml

ROOT = Path(__file__).parents[1]


class RecoveryCatalogTests(unittest.TestCase):
    def test_all_declared_release_images_remain_digest_pinned_in_catalog(self):
        config = yaml.safe_load((ROOT / 'environments/dev.yml').read_text())
        catalog = json.loads((ROOT / 'recovery/artifacts.v1.json').read_text())['references']
        for key, image in config.items():
            if key.endswith('_image_ref'):
                self.assertIn('oci://' + image, catalog)
        for reference in catalog:
            if reference.startswith('oci://'):
                self.assertRegex(reference, r'@sha256:[0-9a-f]{64}$')
            else:
                self.assertTrue((ROOT / reference.removeprefix('build://')).is_file())
        self.assertEqual(len(catalog), len(set(catalog)))

    def test_runtime_catalog_covers_base_and_current_component_contracts(self):
        catalog = json.loads((ROOT / 'recovery/runtime-secrets.v1.json').read_text())['services']
        base = yaml.safe_load((ROOT / 'environments/dev.yml').read_text())['infrastructure_infisical_runtime_services']
        for name, source in base.items():
            self.assertEqual(catalog[name]['environment'], source['environment'])
            self.assertEqual(catalog[name]['path'], source['path'])
            self.assertTrue(set(source['required_keys']) <= set(catalog[name]['required_keys']))
        defaults = yaml.safe_load((ROOT / 'ansible/roles/events_service/defaults/main.yml').read_text())
        required = set(defaults['events_service_broker_keys'] + defaults['events_service_notify_keys'])
        self.assertEqual(set(catalog['events-service']['required_keys']), required)
        self.assertIn('RAG_DATABASE_URL', catalog['rag-service']['required_keys'])
        self.assertIn('RAG_DATABASE_URL', catalog['rag-service-migrations']['required_keys'])
        self.assertIn('OVERLEAF_INVITE_TOKEN_SECRET', catalog['overleaf']['required_keys'])
        self.assertIn('CLSI_PASSWORD', catalog['clsi']['required_keys'])

    def test_probe_access_plan_never_attests_credentials_or_custody(self):
        plan = json.loads((ROOT / 'recovery/probe-access.v1.json').read_text())
        self.assertFalse(plan['privileged_configuration_approved'])
        self.assertFalse(plan['issued_credentials_verified'])
        self.assertFalse(plan['metadata_identity']['values_access'])
        self.assertFalse(plan['registry_identity']['write_access'])
        for project_id in plan['project_mapping'].values():
            self.assertRegex(project_id, r'^[0-9a-f-]{36}$')
        self.assertFalse(re.search(r'"(token|client_secret|password)"\s*:', json.dumps(plan)))


if __name__ == '__main__':
    unittest.main()
