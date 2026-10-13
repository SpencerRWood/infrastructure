"""Immutable encrypted image export/retrieval is separate from Docker cache."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


EXPORT = load('image_export', 'export-recovery-images.py')
VERIFY = load('image_retrieval', 'verify-recovery-image.py')


class ImageExportTests(unittest.TestCase):
    def archive(self, layer=b'fixture-layer', expected_layer=None):
        expected_layer = expected_layer if expected_layer is not None else layer
        config = json.dumps({'rootfs': {'diff_ids': ['sha256:' + hashlib.sha256(expected_layer).hexdigest()]}}).encode()
        config_hash = hashlib.sha256(config).hexdigest()
        manifest = json.dumps([{'Config': config_hash + '.json', 'Layers': ['layer.tar'], 'RepoTags': []}]).encode()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w') as stream:
            for name, content in [(config_hash + '.json', config), ('layer.tar', layer), ('manifest.json', manifest)]:
                member = tarfile.TarInfo(name); member.size = len(content)
                stream.addfile(member, io.BytesIO(content))
        data = buffer.getvalue()
        return data, {'image_id': 'sha256:' + config_hash, 'archive_sha256': hashlib.sha256(data).hexdigest(),
                      'ciphertext_sha256': 'a' * 64}

    def test_streamed_retrieval_proves_configuration_layers_and_no_plaintext_file(self):
        data, metadata = self.archive()
        result = VERIFY.inspect_archive(io.BytesIO(data), metadata)
        self.assertEqual(result['image_id'], metadata['image_id'])
        self.assertEqual(result['layer_count'], 1)
        self.assertFalse(result['plaintext_persisted'])

    def test_changed_layer_fails_even_when_outer_archive_hash_is_recomputed(self):
        data, metadata = self.archive(layer=b'changed-layer', expected_layer=b'original-layer')
        with self.assertRaisesRegex(ValueError, 'image_layer_integrity_failed'):
            VERIFY.inspect_archive(io.BytesIO(data), metadata)

    def test_wrong_configuration_and_archive_hash_fail(self):
        data, metadata = self.archive()
        for key, value, reason in [('image_id', 'sha256:' + 'b' * 64, 'image_configuration_identity_mismatch'),
                                   ('archive_sha256', 'b' * 64, 'image_archive_plaintext_checksum_mismatch')]:
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, reason):
                VERIFY.inspect_archive(io.BytesIO(data), metadata | {key: value})

    def test_unapproved_or_stale_plan_cannot_export_or_touch_storage(self):
        plan = {'images': []}
        with patch.object(EXPORT, 'prepare', return_value={'images': ['changed']}), \
                patch.object(EXPORT, 'encrypt_stream') as encrypt:
            with self.assertRaisesRegex(ValueError, 'approved_export_plan_stale'):
                EXPORT.apply(plan, EXPORT.fingerprint(plan))
            encrypt.assert_not_called()


if __name__ == '__main__':
    unittest.main()
