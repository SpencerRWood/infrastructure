"""Restore a policy-selected real database into private disposable PostgreSQL."""
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import tarfile
import uuid
import stat

from recovery_manifest import InvalidBackup, digest, load_policy, validate


class RestoreFailure(Exception):
    def __init__(self, reason, state='failed'):
        self.reason, self.state = reason, state


def run(argv, workspace, timeout=60):
    environment = {'PATH': os.environ.get('PATH', os.defpath), 'LANG': 'C.UTF-8',
                   'HOME': str(workspace), 'TMPDIR': str(workspace)}
    try:
        result = subprocess.run(argv, env=environment, cwd=workspace, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    except FileNotFoundError as error:
        raise RestoreFailure('restore_tool_unavailable', 'unavailable') from error
    except subprocess.TimeoutExpired as error:
        raise RestoreFailure('restore_command_timeout') from error
    if result.returncode:
        raise RestoreFailure('isolated_' + Path(argv[0]).name + '_failed')
    if len(result.stdout) > 65536:
        raise RestoreFailure('restore_output_limit_exceeded')
    return result.stdout.decode().strip()


def copy_artifact(entry, group, target, policy, workspace):
    copied = target.with_name(target.name + '.encrypted') if entry['format'].endswith('-age') else target
    shutil.copyfile(group / entry['artifact'], copied)
    copied.chmod(0o600)
    if digest(copied) != entry['sha256']:
        raise RestoreFailure('copied_backup_checksum_mismatch')
    if copied != target:
        identity = Path(policy['decryption_identity_file'])
        if identity.is_symlink() or not identity.is_file():
            raise RestoreFailure('decryption_credential_unavailable', 'unavailable')
        metadata = identity.stat()
        if stat.S_IMODE(metadata.st_mode) != 0o600 or metadata.st_uid != os.geteuid():
            raise RestoreFailure('decryption_credential_permissions_invalid', 'unavailable')
        run(['age', '--decrypt', '--identity', str(identity), '--output', str(target), str(copied)], workspace, 120)
        target.chmod(0o600)
        copied.unlink()


def verify(policy_file, deadline_seconds=240):
    checks, backups = [], []
    checksum = None
    workspace = None
    previous = {}
    def observation(phase, state, reason, checksum=None):
        entry = {'id': phase, 'phase': phase, 'state': state, 'reason': reason}
        if checksum:
            entry['artifact_sha256'] = checksum
        checks.append(entry)
    def interrupted(signum, frame):
        raise RestoreFailure('restore_execution_interrupted')
    try:
        policy = load_policy(policy_file)
        manifest, group, _ = validate(policy['pointer'], policy)
        selected = next((item for item in manifest['artifacts']
                         if item['source'] == policy['restore_database'] and item['format'] in {'postgres-custom', 'postgres-custom-age'}), None)
        if not selected:
            raise RestoreFailure('representative_database_backup_missing')
        database = policy['restore_database']
        if not re.fullmatch('[a-z][a-z0-9_]{0,62}', database) or database == 'postgres':
            raise RestoreFailure('isolated_database_name_invalid')
        checksum = selected['sha256']
        backups.append({'source_id': 'current_recovery_group', 'kind': 'recovery_backup',
                        'artifact_sha256': checksum, 'timestamp': selected['completed_at']})
        if os.geteuid() == 0:
            raise RestoreFailure('restore_requires_unprivileged_user', 'unavailable')
        for tool in ('postgres', 'initdb', 'pg_ctl', 'psql', 'pg_restore', 'createdb', 'pg_amcheck'):
            if not shutil.which(tool):
                raise RestoreFailure('restore_tool_unavailable', 'unavailable')
        workspace = Path(tempfile.mkdtemp(prefix='rv-real-', dir='/tmp'))
        workspace.chmod(0o700)
        for signum in (signal.SIGTERM, signal.SIGALRM):
            previous[signum] = signal.signal(signum, interrupted)
        signal.alarm(deadline_seconds)
        data, socket = workspace / 'pgdata', workspace / 'socket'
        socket.mkdir(mode=0o700)
        globals_file = workspace / 'globals.sql'
        dump = workspace / 'database.dump'
        globals_entry = next(item for item in manifest['artifacts'] if item['source'] == 'postgres-globals')
        copy_artifact(globals_entry, group, globals_file, policy, workspace)
        copy_artifact(selected, group, dump, policy, workspace)
        with dump.open('rb') as stream:
            if stream.read(5) != b'PGDMP':
                raise RestoreFailure('decrypted_backup_format_invalid')
        bootstrap = 'rv_' + uuid.uuid4().hex
        run(['initdb', '-D', str(data), '-U', bootstrap, '--auth=trust', '--no-locale', '--encoding=UTF8'], workspace)
        # No TCP listener, live URI, production password or application process.
        run(['pg_ctl', '-D', str(data), '-l', str(workspace / 'postgres.log'), '-o',
             f"-k {socket} -p 55479 -c listen_addresses='' -c unix_socket_permissions=0700",
             '-w', '-t', '10', 'start'], workspace)
        connection = ['-h', str(socket), '-p', '55479', '-U', bootstrap]
        available = run(['psql', '-X', *connection, '-d', 'postgres', '-At', '-c',
                         'SELECT name FROM pg_available_extensions;'], workspace).splitlines()
        if not set(selected['recovery_prerequisites'].get('extensions', [])) <= set(available):
            raise RestoreFailure('required_postgres_extension_unavailable', 'unavailable')
        settings = selected['recovery_prerequisites'].get('database_settings')
        if settings and settings['locale_provider'] == 'c':
            def normalized(value):
                return value.lower().replace('-', '').replace('_', '')
            locales = {normalized(value) for value in run(['locale', '-a'], workspace).splitlines()}
            if any(normalized(settings[key]) not in locales for key in ('lc_collate', 'lc_ctype')):
                raise RestoreFailure('required_database_locale_unavailable', 'unavailable')
        run(['psql', '-X', *connection, '-d', 'postgres', '-v', 'ON_ERROR_STOP=1', '-f', str(globals_file)], workspace)
        # Ownership and ACLs are restored, unlike a no-owner/no-acl fixture test.
        run(['pg_restore', *connection, '--create', '--exit-on-error', '--no-tablespaces', '--dbname=postgres', str(dump)], workspace, 120)
        observation('restore', 'passed', 'representative_real_database_restored', checksum)
        def query(sql):
            return run(['psql', '-X', *connection, '-d', database, '-At', '-v', 'ON_ERROR_STOP=1', '-c', sql], workspace)
        if query("SELECT count(*)>0 FROM pg_class WHERE relkind='r' AND relnamespace IN (SELECT oid FROM pg_namespace WHERE nspname NOT IN ('pg_catalog','information_schema'));") != 't':
            raise RestoreFailure('representative_schema_missing')
        observation('schema', 'passed', 'application_relations_present')
        run(['pg_amcheck', *connection, '--database', database, '--install-missing'], workspace, 60)
        if query("SELECT count(*)=0 FROM pg_class c LEFT JOIN pg_roles r ON r.oid=c.relowner WHERE r.oid IS NULL;") != 't':
            raise RestoreFailure('restored_ownership_missing')
        observation('integrity', 'passed', 'database_integrity_and_ownership_verified')
        if policy.get('restore_file_source'):
            file_entry = next((item for item in manifest['artifacts']
                               if item['source'] == policy['restore_file_source'] and item['format'] in {'tar-gzip', 'tar-gzip-age'}), None)
            if not file_entry:
                raise RestoreFailure('representative_file_backup_missing')
            copied = workspace / 'application.tar.gz'
            copy_artifact(file_entry, group, copied, policy, workspace)
            restored_files = workspace / 'application-files'
            restored_files.mkdir(mode=0o700)
            with tarfile.open(copied, 'r:gz') as archive:
                members = archive.getmembers()
                if not members or any(not (member.isdir() or member.isfile()) for member in members):
                    raise RestoreFailure('application_archive_members_unsupported')
                archive.extractall(restored_files, filter='data')
                for member in members:
                    if member.isfile():
                        with archive.extractfile(member) as expected, (restored_files / member.name).open('rb') as actual:
                            while block := expected.read(1024 * 1024):
                                if actual.read(len(block)) != block:
                                    raise RestoreFailure('application_file_restore_integrity_failed')
            checks.append({'id': 'application_file_restore', 'phase': 'integrity', 'state': 'passed',
                           'reason': 'representative_application_archive_restored'})
        for sql in policy['representative_queries']:
            if query(sql) != 't':
                raise RestoreFailure('representative_query_failed')
        observation('synthetic', 'passed', 'representative_database_queries_passed')
    except ImportError:
        observation('restore', 'unavailable', 'backup_schema_runtime_unavailable', checksum)
    except InvalidBackup as error:
        observation('restore', error.state, str(error), checksum)
    except (FileNotFoundError, PermissionError):
        observation('restore', 'unavailable', 'backup_unreadable', checksum)
    except RestoreFailure as error:
        phase = next((item for item in ('restore', 'schema', 'integrity', 'synthetic')
                      if not any(check['phase'] == item for check in checks)), 'restore')
        observation(phase, error.state, error.reason, checksum if phase == 'restore' else None)
    except (OSError, KeyError, ValueError, TypeError, tarfile.TarError):
        phase = next((item for item in ('restore', 'schema', 'integrity', 'synthetic')
                      if not any(check['phase'] == item for check in checks)), 'classification')
        observation(phase, 'failed', 'invalid_restore_input', checksum if phase == 'restore' else None)
    finally:
        signal.alarm(0)
        cleanup_failed = False
        if workspace:
            signal.signal(signal.SIGTERM, signal.SIG_IGN)
            try:
                if (workspace / 'pgdata/postmaster.pid').exists():
                    run(['pg_ctl', '-D', str(workspace / 'pgdata'), '-m', 'immediate', '-w', '-t', '10', 'stop'], workspace, 12)
                shutil.rmtree(workspace)
            except (OSError, RestoreFailure):
                cleanup_failed = True
        for signum, handler in previous.items():
            signal.signal(signum, handler)
        observation('cleanup', 'failed' if cleanup_failed else 'passed',
                    'cleanup_failed' if cleanup_failed else 'temporary_resources_removed')
        if cleanup_failed:
            checks[-1]['resource_reference'] = 'temporary://' + workspace.name
    for phase in ('restore', 'schema', 'integrity', 'synthetic'):
        if not any(check['phase'] == phase for check in checks):
            observation(phase, 'skipped', 'restore_not_completed')
    states = {item['state'] for item in checks}
    state = next((value for value in ('failed', 'unavailable', 'skipped') if value in states), 'passed')
    return {'schema_version': '1', 'mode': 'verification', 'readiness_state': state,
            'checks': checks, 'provenance': {'playbooks': None, 'inventories': None,
                                            'inline_inventory': None, 'backups': backups}}
