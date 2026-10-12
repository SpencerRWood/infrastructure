"""Real-backup restore classification, isolation and cleanup contracts."""
import json
import yaml
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import backup_restore


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'database.dump').write_bytes(b'PGDMP-fixture')
        (self.root / 'globals.sql').write_bytes(b'-- globals')
        self.manifest = {'artifacts': [
            {'source': 'application', 'artifact': 'database.dump', 'format': 'postgres-custom',
             'sha256': backup_restore.digest(self.root / 'database.dump'), 'completed_at': '2026-10-12T20:00:00+00:00',
             'recovery_prerequisites': {'roles_artifact': 'globals.sql', 'extensions': ['plpgsql'],
                'database_settings': {'locale_provider': 'c', 'lc_collate': 'C', 'lc_ctype': 'C'}}},
            {'source': 'postgres-globals', 'artifact': 'globals.sql',
             'sha256': backup_restore.digest(self.root / 'globals.sql')} ]}
        self.policy = self.root / 'policy.yml'
        from recovery_manifest import load_policy
        policy = load_policy(ROOT / 'recovery/backup-policy.yml')
        policy.update(pointer='/unreachable-production-path', restore_database='application',
                      representative_queries=['SELECT true;'])
        policy.pop('restore_file_source', None)
        self.policy.write_text(yaml.safe_dump(policy))

    def test_missing_backup_is_unavailable_without_launching_any_engine(self):
        with patch.object(backup_restore, 'run') as run:
            result = backup_restore.verify(self.policy)
        self.assertEqual(result['readiness_state'], 'unavailable')
        run.assert_not_called()
        self.assertEqual(result['checks'][0]['reason'], 'backup_artifact_missing')

    def test_corrupt_backup_is_failed_without_launching_any_engine(self):
        from recovery_manifest import InvalidBackup
        with patch.object(backup_restore, 'validate', side_effect=InvalidBackup('backup_checksum_mismatch')), \
                patch.object(backup_restore, 'run') as command:
            result = backup_restore.verify(self.policy)
        self.assertEqual(result['readiness_state'], 'failed')
        self.assertEqual(result['checks'][0]['reason'], 'backup_checksum_mismatch')
        command.assert_not_called()

    def test_denied_backup_is_unavailable_without_launching_any_engine(self):
        with patch.object(backup_restore, 'validate', side_effect=PermissionError('private-path')), \
                patch.object(backup_restore, 'run') as command:
            result = backup_restore.verify(self.policy)
        self.assertEqual(result['readiness_state'], 'unavailable')
        self.assertEqual(result['checks'][0]['reason'], 'backup_unreadable')
        self.assertNotIn('private-path', json.dumps(result))
        command.assert_not_called()

    def test_missing_schema_runtime_is_unavailable_without_restore(self):
        with patch.object(backup_restore, 'load_policy', side_effect=ImportError), \
                patch.object(backup_restore, 'run') as command:
            result = backup_restore.verify(self.policy)
        self.assertEqual(result['readiness_state'], 'unavailable')
        self.assertEqual(result['checks'][0]['reason'], 'backup_schema_runtime_unavailable')
        command.assert_not_called()

    def test_missing_tool_is_unavailable_and_binds_real_checksum(self):
        with patch.object(backup_restore, 'validate', return_value=(self.manifest, self.root, 'a' * 64)), \
                patch.object(backup_restore.os, 'geteuid', return_value=10001), \
                patch.object(backup_restore.shutil, 'which', return_value=None):
            result = backup_restore.verify(self.policy)
        self.assertEqual(result['readiness_state'], 'unavailable')
        self.assertEqual(result['checks'][0]['artifact_sha256'], result['provenance']['backups'][0]['artifact_sha256'])
        self.assertEqual(result['provenance']['backups'][0]['kind'], 'recovery_backup')

    def test_commands_use_private_socket_restore_owner_acl_and_cleanup(self):
        workspaces = []
        def command(argv, workspace, timeout=60):
            workspaces.append(workspace)
            if 'pg_available_extensions' in ' '.join(argv):
                return 'plpgsql'
            if argv == ['locale', '-a']:
                return 'C\nPOSIX'
            if argv[0] == 'psql':
                return 't'
            return ''
        with patch.object(backup_restore, 'validate', return_value=(self.manifest, self.root, 'a' * 64)), \
                patch.object(backup_restore.os, 'geteuid', return_value=10001), \
                patch.object(backup_restore.shutil, 'which', return_value='/fixture/tool'), \
                patch.object(backup_restore, 'run', side_effect=command) as calls:
            result = backup_restore.verify(self.policy)
        self.assertEqual(result['readiness_state'], 'passed')
        restore = next(call.args[0] for call in calls.call_args_list if call.args[0][0] == 'pg_restore')
        self.assertIn('--create', restore)
        self.assertNotIn('--no-owner', restore)
        self.assertNotIn('--no-acl', restore)
        self.assertTrue(restore[restore.index('-h') + 1].startswith('/tmp/rv-real-'))
        self.assertFalse(any('unreachable-production-path' in str(call.args) for call in calls.call_args_list))
        self.assertTrue(all(not workspace.exists() for workspace in workspaces))

    def test_source_locale_is_a_reported_prerequisite(self):
        self.manifest['artifacts'][0]['recovery_prerequisites']['database_settings']['lc_collate'] = 'en_US.utf8'
        def command(argv, workspace, timeout=60):
            return 'plpgsql' if argv[0] == 'psql' else 'C\nPOSIX'
        with patch.object(backup_restore, 'validate', return_value=(self.manifest, self.root, 'a' * 64)), \
                patch.object(backup_restore.os, 'geteuid', return_value=10001), \
                patch.object(backup_restore.shutil, 'which', return_value='/fixture/tool'), \
                patch.object(backup_restore, 'run', side_effect=command):
            result = backup_restore.verify(self.policy)
        self.assertEqual(result['readiness_state'], 'unavailable')
        self.assertEqual(result['checks'][0]['reason'], 'required_database_locale_unavailable')


if __name__ == '__main__':
    unittest.main()
