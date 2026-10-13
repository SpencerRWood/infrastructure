"""Backup publication, preservation and recovery manifest failure contracts."""
import datetime as dt
import fcntl
import importlib.util
import json
import os
import sqlite3
import tarfile
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BACKUP = load('producer', 'recovery-backup.py')
MANIFEST = load('manifest', 'recovery_manifest.py')


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.mount = Path(self.temp.name)
        self.root = self.mount / 'backups'
        self.config = {'consumer': 'infrastructure', 'environment': 'dev', 'max_age_seconds': 86400,
                       'encryption_recipient': 'age1544rwqert2c0u5wks57lcgfw6saymcfmc7slhdr58js69w3m7d4st3la33',
                       'independent_custody_verified': True,
                       'destination': {'mount': str(self.mount), 'root': str(self.root),
                                       'source': 'nas:/backups', 'fstype': 'nfs'},
                       'postgres': {'container': 'active-postgres', 'password_source': 'file', 'required_databases': ['application']}}
        self.policy = {'consumer': 'infrastructure', 'environment': 'dev', 'max_age_seconds': 86400,
                       'postgres_container': 'active-postgres',
                       'required_sources': ['postgres-globals', 'application']}

    def fake_command(self, argv, *, output=None, timeout=1800):
        if argv[0] == 'findmnt':
            destination = self.config['destination']
            secondary = self.config.get('off_source_destination')
            if secondary and argv[3] == secondary['mount']:
                destination = secondary
            return json.dumps({'filesystems': [{'target': destination['mount'], 'source': destination['source'],
                                                'fstype': destination['fstype']}]})
        if 'inspect' in argv:
            if '{{json .State}}' in argv:
                return json.dumps({'Running': True, 'Health': {'Status': 'healthy'}})
            return 'true'
        if argv[0] == 'age':
            target = Path(argv[argv.index('--output') + 1])
            target.write_bytes(b'age-encryption.org/v1\n' + Path(argv[-1]).read_bytes())
            return ''
        if 'psql' in argv:
            if any('json_build_object' in value for value in argv):
                return json.dumps({'owner': 'application', 'locale_provider': 'c', 'lc_collate': 'C', 'lc_ctype': 'C'})
            if 'SELECT extname FROM pg_extension ORDER BY extname;' in argv:
                return 'plpgsql'
            return '16.9' if 'SHOW server_version;' in argv else 'application\npostgres'
        if output:
            output.write(b'-- globals\n' if 'pg_dumpall' in argv else b'PGDMP-disposable-test-archive')
            return None
        return ''

    def produce(self):
        with patch.object(BACKUP, 'command', side_effect=self.fake_command), \
                patch.object(BACKUP.subprocess, 'run') as run:
            run.return_value.returncode = 0
            return BACKUP.produce(self.config)

    def document(self):
        pointer = json.loads((self.root / 'current.json').read_text())
        path = self.root / pointer['manifest']
        return path, json.loads(path.read_text())

    def test_complete_publication_validates_without_claiming_restore(self):
        self.produce()
        manifest, group, checksum = MANIFEST.validate(self.root / 'current.json', self.policy)
        self.assertEqual(manifest['restore_verification']['result'], 'not_run')
        self.assertFalse(manifest['application_recovery_verified'])
        self.assertEqual(len(checksum), 64)
        self.assertEqual((group / 'manifest.json').stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.root.glob('.in-progress-*')))
        self.assertTrue(all((group / row['artifact']).stat().st_mode & 0o777 == 0o600
                            for row in manifest['artifacts']))

    def test_new_completion_cannot_make_old_source_fresh(self):
        self.produce()
        path, document = self.document()
        old = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()
        document['created_at'] = old
        for artifact in document['artifacts']:
            artifact['created_at'] = old
        path.write_text(json.dumps(document))
        with self.assertRaisesRegex(MANIFEST.InvalidBackup, 'backup_source_stale'):
            MANIFEST.validate(self.root / 'current.json', self.policy)

    def test_missing_or_wrong_mount_writes_nothing(self):
        with patch.object(BACKUP, 'command', return_value=json.dumps({'filesystems': []})):
            with self.assertRaises(BACKUP.BackupFailure):
                BACKUP.produce(self.config)
        self.assertFalse(self.root.exists())
        with patch.object(BACKUP, 'command', return_value=json.dumps({'filesystems': [
                {'target': str(self.mount), 'source': '/dev/localdisk', 'fstype': 'ext4'}]})):
            with self.assertRaises(BACKUP.BackupFailure):
                BACKUP.produce(self.config)
        self.assertFalse(self.root.exists())

    def test_failed_backup_keeps_last_valid_group(self):
        self.produce()
        previous = (self.root / 'current.json').read_bytes()
        with patch.object(BACKUP, 'command', side_effect=self.fake_command), \
                patch.object(BACKUP, 'backup_postgres', side_effect=BACKUP.BackupFailure('dump_failed')):
            with self.assertRaises(BACKUP.BackupFailure):
                BACKUP.produce(self.config)
        self.assertEqual((self.root / 'current.json').read_bytes(), previous)
        MANIFEST.validate(self.root / 'current.json', self.policy)
        self.assertFalse(list(self.root.glob('.in-progress-*')))

    def test_group_rejection_cases(self):
        self.produce()
        path, original = self.document()
        cases = [('backup_stale', {'completed_at': (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=2)).isoformat()}),
                 ('backup_origin_mismatch', {'consumer': 'other'}),
                 ('backup_origin_mismatch', {'environment': 'prod'}),
                 ('backup_origin_mismatch', {'postgres_container': 'retired-postgres'}),
                 ('backup_group_incomplete', {'artifacts': original['artifacts'][1:]}),
                 ('backup_group_incomplete', {'required_sources': []})]
        for reason, changes in cases:
            with self.subTest(reason=reason):
                path.write_text(json.dumps(original | changes))
                with self.assertRaisesRegex(MANIFEST.InvalidBackup, reason):
                    MANIFEST.validate(self.root / 'current.json', self.policy)
        path.write_text(json.dumps(original))
        artifact = path.parent / original['artifacts'][0]['artifact']
        artifact.write_bytes(b'x' * artifact.stat().st_size)
        with self.assertRaisesRegex(MANIFEST.InvalidBackup, 'backup_checksum_mismatch'):
            MANIFEST.validate(self.root / 'current.json', self.policy)
        artifact.unlink()
        with self.assertRaisesRegex(MANIFEST.InvalidBackup, 'backup_artifact_missing'):
            MANIFEST.validate(self.root / 'current.json', self.policy)

    def test_consumer_policy_rejects_self_consistent_incomplete_group(self):
        self.produce()
        path, original = self.document()
        original['artifacts'] = original['artifacts'][1:]
        original['required_sources'] = [item['source'] for item in original['artifacts']]
        path.write_text(json.dumps(original))
        with self.assertRaisesRegex(MANIFEST.InvalidBackup, 'backup_group_incomplete'):
            MANIFEST.validate(self.root / 'current.json', self.policy)

    def test_quiescence_requires_explicit_approval_before_any_stop(self):
        self.config['quiesce_containers'] = ['application']
        with patch.object(BACKUP, 'command', side_effect=self.fake_command) as calls:
            with self.assertRaisesRegex(BACKUP.BackupFailure, 'service_quiescence_approval_required'):
                BACKUP.produce(self.config)
        self.assertFalse(any('stop' in call.args[0] for call in calls.call_args_list))

    def test_writer_restart_after_dump_failure(self):
        self.config.update(quiesce_containers=['application'], quiesce_authorized=True)
        with patch.object(BACKUP, 'command', side_effect=self.fake_command) as calls, \
                patch.object(BACKUP, 'backup_postgres', side_effect=BACKUP.BackupFailure('dump_failed')):
            with self.assertRaises(BACKUP.BackupFailure):
                BACKUP.produce(self.config)
        self.assertTrue(any(call.args[0] == ['docker', 'start', 'application'] for call in calls.call_args_list))

    def test_runtime_credentials_remain_inside_container(self):
        argv = BACKUP.pg_command('active', 'file', 'pg_dump', '--dbname', 'application')
        self.assertIn('POSTGRES_PASSWORD_FILE', argv[6])
        self.assertNotIn('legacy', ' '.join(argv))
        self.assertNotIn('else', argv[6])
        with self.assertRaises(BACKUP.BackupFailure):
            BACKUP.pg_command('active', 'unsupported', 'pg_dump')

    def test_concurrent_run_cannot_publish(self):
        self.root.mkdir()
        with (self.root / '.backup.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with patch.object(BACKUP, 'command', side_effect=self.fake_command):
                with self.assertRaisesRegex(BACKUP.BackupFailure, 'backup_already_running'):
                    BACKUP.produce(self.config)
        self.assertFalse((self.root / 'current.json').exists())

    def test_destination_cannot_escape_mount_through_parent_traversal(self):
        self.config['destination']['root'] = str(self.mount / '..' / 'outside-backups')
        with patch.object(BACKUP, 'command', side_effect=self.fake_command):
            with self.assertRaisesRegex(BACKUP.BackupFailure, 'backup_destination_path_invalid'):
                BACKUP.produce(self.config)

    def test_completed_reader_access_is_read_only(self):
        self.config['reader_gid'] = os.getgid()
        self.produce()
        path, manifest = self.document()
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        self.assertEqual(path.parent.stat().st_mode & 0o777, 0o750)
        self.assertEqual(path.stat().st_gid, os.getgid())
        self.assertTrue(all((path.parent / row['artifact']).stat().st_mode & 0o777 == 0o640
                            for row in manifest['artifacts']))

    def test_missing_key_recipient_never_pauses_writers(self):
        self.config.pop('encryption_recipient')
        self.config.update(files=[{'id': 'keys', 'sensitive': True, 'paths': ['/protected/keys']}],
                           quiesce_containers=['application'], quiesce_authorized=True)
        with patch.object(BACKUP, 'command', side_effect=self.fake_command) as calls:
            with self.assertRaisesRegex(BACKUP.BackupFailure, 'backup_encryption_recipient_required'):
                BACKUP.produce(self.config)
        self.assertFalse(any('stop' in call.args[0] for call in calls.call_args_list))

    def test_unverified_custody_prevents_writer_pause_and_publication(self):
        self.config['independent_custody_verified'] = False
        with patch.object(BACKUP, 'command', side_effect=self.fake_command) as calls:
            with self.assertRaisesRegex(BACKUP.BackupFailure, 'independent_key_custody_required'):
                BACKUP.produce(self.config)
        self.assertFalse(self.root.exists())
        self.assertFalse(any('stop' in call.args[0] for call in calls.call_args_list))

    def test_every_artifact_encrypted_and_wrong_recipient_rejected(self):
        self.produce()
        path, manifest = self.document()
        self.assertTrue(all(row['artifact'].endswith('.age') for row in manifest['artifacts']))
        self.assertFalse(list(path.parent.glob('*.dump')))
        self.policy['encryption_recipient'] = self.config['encryption_recipient']
        MANIFEST.validate(self.root / 'current.json', self.policy)
        manifest['artifacts'][0]['encryption']['recipient'] = 'age1' + 'q' * 58
        path.write_text(json.dumps(manifest))
        with self.assertRaisesRegex(MANIFEST.InvalidBackup, 'backup_encryption_policy_mismatch'):
            MANIFEST.validate(self.root / 'current.json', self.policy)

    def test_failed_stop_still_resumes_writer(self):
        self.config.update(quiesce_containers=['application'], quiesce_authorized=True)
        def command(argv, **kwargs):
            if 'stop' in argv:
                raise BACKUP.BackupFailure('stop_failed')
            return self.fake_command(argv, **kwargs)
        with patch.object(BACKUP, 'command', side_effect=command) as calls:
            with self.assertRaisesRegex(BACKUP.BackupFailure, 'stop_failed'):
                BACKUP.produce(self.config)
        self.assertTrue(any(call.args[0] == ['docker', 'start', 'application'] for call in calls.call_args_list))

    def test_failed_resume_is_critical_and_never_publishes(self):
        self.config.update(quiesce_containers=['application'], quiesce_authorized=True)
        def command(argv, **kwargs):
            if 'start' in argv:
                raise BACKUP.BackupFailure('start_failed')
            return self.fake_command(argv, **kwargs)
        with patch.object(BACKUP, 'command', side_effect=command), \
                patch.object(BACKUP, 'backup_postgres', side_effect=BACKUP.BackupFailure('dump_failed')):
            with self.assertRaisesRegex(BACKUP.BackupFailure, 'backup_failed_and_writer_restart_failed'):
                BACKUP.produce(self.config)
        self.assertFalse((self.root / 'current.json').exists())

    def test_sqlite_backup_copy_integrity_and_missing_database(self):
        database = self.mount / 'application.db'
        with sqlite3.connect(database) as connection:
            connection.execute('CREATE TABLE recovered (id integer primary key)')
            connection.execute('INSERT INTO recovered VALUES (1)')
        archive = self.mount / 'state.tar.gz'
        with tarfile.open(archive, 'w:gz') as stream:
            stream.add(database, arcname='application.db')
        self.assertEqual(BACKUP.validate_file_archive(archive, {'required_sqlite_members': ['application.db']}), 1)
        with self.assertRaisesRegex(BACKUP.BackupFailure, 'required_sqlite_database_missing_or_invalid'):
            BACKUP.validate_file_archive(archive, {'required_sqlite_members': ['missing.db']})
        data = bytearray(database.read_bytes())
        data[100:150] = b'x' * 50
        database.write_bytes(data)
        with tarfile.open(archive, 'w:gz') as stream:
            stream.add(database, arcname='application.db')
        with self.assertRaises(BACKUP.BackupFailure):
            BACKUP.validate_file_archive(archive, {})

    def test_native_sqlite_uses_only_disposable_copy_and_removes_resources(self):
        component = {'sqlite_container': 'active-plex'}
        copy = self.mount / 'copied.db'
        def command(argv, **kwargs):
            if argv[1] == 'inspect':
                return 'sha256:existing-image'
            if argv[1] == 'create':
                return 'owned-disposable-container'
            if argv[1] == 'start':
                return 'ok'
            return ''
        with patch.object(BACKUP, 'command', side_effect=command) as calls:
            BACKUP.validate_native_sqlite(self.mount, copy, component, 'plex')
        create = next(call.args[0] for call in calls.call_args_list if call.args[0][1] == 'create')
        self.assertEqual(create[create.index('--network') + 1], 'none')
        self.assertIn('--read-only', create)
        self.assertIn('ALL', create)
        self.assertIn(f'type=bind,src={self.mount},dst=/snapshot', create)
        self.assertEqual(calls.call_args_list[-1].args[0],
                         ['docker', 'rm', '--force', '--volumes', 'owned-disposable-container'])

    def test_off_source_copy_is_required_and_checksum_verified(self):
        copy_mount = self.mount / 'host-mount'
        copy_mount.mkdir()
        copy_root = copy_mount / 'host-copy'
        self.config['off_source_copy_sources'] = ['application']
        self.config['off_source_destination'] = {'mount': str(copy_mount), 'source': '/dev/local-copy',
                                                'fstype': 'ext4', 'root': str(copy_root)}
        self.policy.update(off_source_copy_sources=['application'], off_source_copy_root=str(copy_root))
        self.produce()
        path, record = self.document()
        entry = next(item for item in record['artifacts'] if item['source'] == 'application')
        copy = Path(entry['off_source_copy']['artifact'])
        self.assertTrue(copy.is_file())
        MANIFEST.validate(self.root / 'current.json', self.policy)
        copy.write_bytes(b'x' * copy.stat().st_size)
        with self.assertRaisesRegex(MANIFEST.InvalidBackup, 'off_source_copy_integrity_failed'):
            MANIFEST.validate(self.root / 'current.json', self.policy)
        copy.unlink()
        with self.assertRaises(MANIFEST.InvalidBackup):
            MANIFEST.validate(self.root / 'current.json', self.policy)


if __name__ == '__main__':
    unittest.main()
