"""The canonical private identity never enters guest transport or evidence."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('transport', ROOT / 'scripts/stage-recovery-transport.py')
TRANSPORT = importlib.util.module_from_spec(spec); spec.loader.exec_module(TRANSPORT)


class TransportTests(unittest.TestCase):
    def test_unapproved_transport_cannot_read_identity_or_create_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            resource = 'temporary://recovery-' + 'a' * 32
            destination = root / resource.removeprefix('temporary://')
            with patch.object(TRANSPORT, 'TRANSPORT_ROOT', root), \
                    patch.object(TRANSPORT, 'load_policy', return_value={'pointer': '/fixture', 'encryption_recipient': 'age1' + 'b' * 58}), \
                    patch.object(TRANSPORT, 'validate', return_value=({}, root, 'c' * 64)), \
                    patch.object(TRANSPORT.STREAM, 'encrypt_stream') as encrypt:
                with self.assertRaisesRegex(ValueError, 'approved_transport_plan_required'):
                    TRANSPORT.stage(root, destination, 'age1' + 'a' * 58, resource,
                                    {'execution_authorized': False})
                self.assertFalse(destination.exists()); encrypt.assert_not_called()

    def test_staging_binds_plaintext_hashes_without_transferring_private_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            group = root / 'source'; group.mkdir()
            ciphertext = group / 'database.age'; ciphertext.write_bytes(b'fixture-ciphertext')
            identity = root / 'controller.agekey'; identity.write_text('fixture-only-private-identity'); identity.chmod(0o600)
            manifest = {'artifacts': [{'source': 'database', 'artifact': 'database.age', 'sha256': TRANSPORT.digest(ciphertext)}]}
            (group / 'manifest.json').write_text(json.dumps(manifest))
            group_hash = TRANSPORT.digest(group / 'manifest.json')
            recipient, resource = 'age1' + 'a' * 58, 'temporary://recovery-' + 'a' * 32
            destination = root / resource.removeprefix('temporary://')
            approved = {'execution_authorized': True, 'manifest_sha256': group_hash,
                        'guest_recipient': recipient, 'resource_reference': resource,
                        'source_revision': 'b' * 40, 'controller_identity_file': str(identity), 'image_exports': {}}
            def encrypted(command, output, received, *limits):
                self.assertEqual(received, recipient)
                self.assertEqual(command[:3], ['age', '--decrypt', '--identity'])
                output.write_bytes(b'guest-encrypted-fixture')
                return 'c' * 64
            with patch.object(TRANSPORT, 'TRANSPORT_ROOT', root), \
                    patch.object(TRANSPORT, 'load_policy', return_value={'pointer': '/fixture', 'encryption_recipient': 'age1' + 'b' * 58}), \
                    patch.object(TRANSPORT, 'validate', return_value=(manifest, group, group_hash)), \
                    patch.object(TRANSPORT.subprocess, 'check_output', side_effect=['b' * 40, '']), \
                    patch.object(TRANSPORT.STREAM, 'encrypt_stream', side_effect=encrypted):
                result = TRANSPORT.stage(root, destination, recipient, resource, approved)
            self.assertFalse(result['private_identity_transferred'])
            record = json.loads((destination / 'transport.json').read_text())
            self.assertEqual(record['artifacts']['database']['source_ciphertext_sha256'], TRANSPORT.digest(ciphertext))
            self.assertEqual(record['artifacts']['database']['plaintext_sha256'], 'c' * 64)
            self.assertNotIn('fixture-only-private-identity', (destination / 'transport.json').read_text())
            self.assertFalse((destination / identity.name).exists())
            self.assertEqual(identity.read_text(), 'fixture-only-private-identity')


if __name__ == '__main__':
    unittest.main()
