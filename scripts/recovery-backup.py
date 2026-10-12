#!/usr/bin/env python3
"""Publish complete immutable recovery groups; never prune previous backups."""
import argparse
import datetime as dt
import fcntl
import fnmatch
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import uuid


class BackupFailure(Exception):
    """A sanitized operational failure."""


def command(argv, *, output=None, timeout=1800):
    result = subprocess.run(argv, stdout=output or subprocess.PIPE,
                            stderr=subprocess.DEVNULL, timeout=timeout, check=False)
    if result.returncode:
        raise BackupFailure('command_failed:' + Path(argv[0]).name)
    return result.stdout.decode().strip() if output is None else None


def timestamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def check_destination(config):
    destination = config['destination']
    mount = Path(destination['mount'])
    details = json.loads(command(['findmnt', '--json', '--mountpoint', str(mount),
                                 '--output', 'TARGET,SOURCE,FSTYPE']))['filesystems']
    if len(details) != 1 or any(details[0].get(key) != value for key, value in {
        'target': str(mount), 'source': destination['source'],
        'fstype': destination['fstype'],
    }.items()):
        raise BackupFailure('backup_destination_identity_mismatch')
    root = Path(destination['root'])
    if (not root.is_absolute() or '..' in root.parts or mount.is_symlink()
            or root == mount or not root.is_relative_to(mount)):
        raise BackupFailure('backup_destination_path_invalid')
    # Reject symlink redirection before creating anything on the destination.
    for parent in (root, *root.parents):
        if parent.is_symlink():
            raise BackupFailure('backup_destination_symlink')
        if parent == mount:
            break
    return root


def pg_command(container, password_source, program, *args):
    # Resolve the existing runtime contract inside the source container. No secret
    # values appear in the host argv, logs, configuration or manifest.
    if password_source == 'file':
        resolve = ': "${POSTGRES_PASSWORD_FILE:?}"; export PGPASSWORD="$(cat "$POSTGRES_PASSWORD_FILE")"; '
    elif password_source == 'environment':
        resolve = 'export PGPASSWORD="${POSTGRES_PASSWORD:?}"; '
    else:
        raise BackupFailure('postgres_credential_contract_invalid')
    script = resolve + 'exec "$@" -U "$POSTGRES_USER"'
    return ['docker', 'exec', container, 'sh', '-eu', '-c', script,
            'recovery-backup', program, *args]


def backup_postgres(config, stage, add):
    container = config['postgres']['container']
    password_source = config['postgres']['password_source']
    if command(['docker', 'inspect', '--format', '{{.State.Running}}', container]) != 'true':
        raise BackupFailure('active_postgres_unavailable')
    query = 'SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY datname;'
    databases = command(pg_command(container, password_source, 'psql', '-X', '-At', '-d', 'postgres', '-c', query)).splitlines()
    if not set(config['postgres']['required_databases']) <= set(databases):
        raise BackupFailure('required_database_missing')
    version = command(pg_command(container, password_source, 'psql', '-X', '-At', '-d', 'postgres',
                                 '-c', 'SHOW server_version;'))
    path = stage / 'postgres-globals.sql'
    started = timestamp()
    with path.open('wb') as stream:
        command(pg_command(container, password_source, 'pg_dumpall', '--globals-only', '--no-tablespaces'), output=stream)
    if not path.read_bytes().startswith(b'--'):
        raise BackupFailure('postgres_globals_invalid')
    add(path, 'postgres-globals', 'postgres-sql', {'postgres_version': version}, started)
    for index, database in enumerate(databases):
        path = stage / f'postgres-{index:03d}.dump'
        started = timestamp()
        with path.open('wb') as stream:
            command(pg_command(container, password_source, 'pg_dump', '--format=custom', '--dbname', database), output=stream)
        with path.open('rb') as stream:
            if stream.read(5) != b'PGDMP':
                raise BackupFailure('postgres_dump_invalid')
        # Validate the custom archive TOC with the same source engine binaries.
        with path.open('rb') as stream:
            result = subprocess.run(['docker', 'exec', '-i', container, 'pg_restore', '--list'],
                                    stdin=stream, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, timeout=120, check=False)
        if result.returncode:
            raise BackupFailure('postgres_archive_validation_failed')
        extensions = command(pg_command(container, password_source, 'psql', '-X', '-At', '-d', database, '-c',
                                        'SELECT extname FROM pg_extension ORDER BY extname;')).splitlines()
        settings = json.loads(command(pg_command(container, password_source, 'psql', '-X', '-At', '-d', database, '-c',
            "SELECT json_build_object('owner',pg_get_userbyid(datdba),'locale_provider',datlocprovider,"
            "'lc_collate',datcollate,'lc_ctype',datctype) FROM pg_database WHERE datname=current_database();")))
        add(path, database, 'postgres-custom', {'postgres_version': version, 'extensions': extensions,
                                               'database_settings': settings,
                                               'roles_artifact': 'postgres-globals.sql'}, started)
    return databases


def backup_files(config, stage, add):
    for component in config.get('files', []):
        started = timestamp()
        paths = [Path(value) for value in component['paths']]
        if not paths or any(not path.exists() or path.is_symlink() for path in paths):
            raise BackupFailure('required_application_state_missing')
        path = stage / (component['id'] + '.tar.gz')
        def include(member):
            for pattern in component.get('exclude', []):
                if fnmatch.fnmatch(member.name, pattern) or fnmatch.fnmatch(member.name, pattern.rstrip('/') + '/*'):
                    return None
            return member
        with tarfile.open(path, 'w:gz') as archive:
            for index, source in enumerate(paths):
                archive.add(source, arcname=str(index), recursive=True, filter=include)
        sqlite_count = validate_file_archive(path, component)
        prerequisites = {'source_paths': [str(value) for value in paths],
                         'consistency': 'writers_quiesced',
                         'sqlite_databases_integrity_verified': sqlite_count,
                         'excluded_disposable_state': component.get('exclude', []),
                         'sqlite_engine': component.get('sqlite_engine', 'python-sqlite3')}
        if component.get('sensitive'):
            recipient = config.get('encryption_recipient')
            if not recipient:
                raise BackupFailure('secret_archive_encryption_recipient_required')
            encrypted = path.with_suffix(path.suffix + '.age')
            command(['age', '--recipient', recipient, '--output', str(encrypted), str(path)])
            path.unlink()  # Only this run's unpublished temporary plaintext.
            path = encrypted
            prerequisites['decryption_key'] = 'operator-managed age identity, stored independently'
        add(path, component['id'], 'tar-gzip-age' if component.get('sensitive') else 'tar-gzip', prerequisites, started)
    for component in config.get('mongo', []):
        started = timestamp()
        path = stage / (component['id'] + '.archive.gz')
        with path.open('wb') as stream:
            command(['docker', 'exec', component['container'], 'mongodump', '--archive', '--gzip'], output=stream)
        with gzip.open(path, 'rb') as stream:
            while stream.read(1024 * 1024):
                pass
        add(path, component['id'], 'mongo-archive-gzip',
            {'mongodb_version': command(['docker', 'exec', component['container'], 'mongodump', '--version']),
             'consistency': 'writers_quiesced'}, started)
    for component in config.get('redis', []):
        started = timestamp()
        path = stage / (component['id'] + '.rdb')
        with path.open('wb') as stream:
            command(['docker', 'exec', component['container'], 'redis-cli', '--rdb', '-'], output=stream)
        with path.open('rb') as stream:
            if stream.read(5) != b'REDIS':
                raise BackupFailure('redis_backup_format_invalid')
        # Validate with the source version. This uses only a new container /tmp
        # file, never the live Redis persistence directory or CONFIG/SAVE.
        script = 'file=$(mktemp); trap \'rm -f "$file"\' EXIT; cat > "$file"; redis-check-rdb "$file" >/dev/null'
        with path.open('rb') as stream:
            result = subprocess.run(['docker', 'exec', '-i', component['container'], 'sh', '-eu', '-c', script],
                                    stdin=stream, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                    timeout=120, check=False)
        if result.returncode:
            raise BackupFailure('redis_backup_validation_failed')
        add(path, component['id'], 'redis-rdb',
            {'redis_version': command(['docker', 'exec', component['container'], 'redis-server', '--version']),
             'consistency': 'redis_replication_snapshot_with_application_writers_quiesced'}, started)


def validate_file_archive(path, component):
    """Validate archive bytes and SQLite copies, never connect to source files."""
    databases = []
    database_members = set()
    members = 0
    with tempfile.TemporaryDirectory(prefix='backup-sqlite-', dir='/tmp') as temporary:
        workspace = Path(temporary)
        with tarfile.open(path, 'r|gz') as archive:
            for member in archive:
                members += 1
                if not member.isfile():
                    continue
                with archive.extractfile(member) as stream:
                    header = stream.read(16)
                    database = header == b'SQLite format 3\x00'
                    suffix = next((value for value in ('-wal', '-shm') if member.name.endswith(value)), '')
                    name = member.name[:-len(suffix)] if suffix else member.name
                    target = workspace / (hashlib.sha256(name.encode()).hexdigest() + '.db' + suffix)
                    if database or suffix:
                        with target.open('wb') as copy:
                            copy.write(header)
                            shutil.copyfileobj(stream, copy, 1024 * 1024)
                        if database:
                            databases.append(target)
                            database_members.add(member.name)
                    else:
                        while stream.read(1024 * 1024):
                            pass
        if not members:
            raise BackupFailure('application_archive_empty')
        if not set(component.get('required_sqlite_members', [])) <= database_members:
            raise BackupFailure('required_sqlite_database_missing_or_invalid')
        for database in databases:
            engine = component.get('sqlite_engine', 'python-sqlite3')
            if engine == 'python-sqlite3':
                connection = None
                try:
                    connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
                    result = connection.execute('PRAGMA integrity_check').fetchall()
                    if result != [('ok',)]:
                        raise BackupFailure('sqlite_backup_integrity_failed')
                except sqlite3.Error as error:
                    raise BackupFailure('sqlite_backup_invalid_or_engine_incompatible') from error
                finally:
                    if connection is not None:
                        connection.close()
            else:
                validate_native_sqlite(workspace, database, component, engine)
    return len(databases)


def validate_native_sqlite(workspace, database, component, engine):
    image = command(['docker', 'inspect', '--format', '{{.Image}}', component['sqlite_container']])
    if engine == 'plex':
        program = '/usr/lib/plexmediaserver/Plex SQLite'
        arguments = ['-readonly', '/snapshot/' + database.name, 'PRAGMA integrity_check;']
    elif engine == 'calibre':
        program = '/usr/bin/calibre-debug'
        code = ('from calibre.db.backend import Connection; '
                f'connection=Connection("/snapshot/{database.name}"); '
                'result=list(connection.execute("PRAGMA integrity_check")); '
                'connection.close(); print("ok" if result==[("ok",)] else "failed")')
        arguments = ['-c', code]
    else:
        raise BackupFailure('sqlite_validation_engine_unsupported')
    container = command(['docker', 'create', '--network', 'none', '--read-only', '--user', '0:0', '--cap-drop', 'ALL',
                         '--security-opt', 'no-new-privileges', '--tmpfs', '/tmp:rw,nosuid,nodev',
                         '--env', 'CALIBRE_CONFIG_DIRECTORY=/tmp/calibre-config',
                         '--mount', f'type=bind,src={workspace},dst=/snapshot',
                         '--entrypoint', program, image, *arguments])
    try:
        if command(['docker', 'start', '--attach', container], timeout=300) != 'ok':
            raise BackupFailure('native_sqlite_backup_integrity_failed')
    finally:
        try:
            command(['docker', 'rm', '--force', '--volumes', container], timeout=30)
        except (BackupFailure, subprocess.TimeoutExpired) as error:
            raise BackupFailure('sqlite_validator_cleanup_failed') from error


def produce(config):
    os.umask(0o077)
    root = check_destination(config)
    if config.get('off_source_copy_sources'):
        primary = config['destination']['source'].split(':', 1)[0]
        secondary = config['off_source_destination']['source'].split(':', 1)[0]
        if primary == secondary:
            raise BackupFailure('off_source_copy_shares_primary_storage_host')
        check_destination({'destination': config['off_source_destination']})
    for kind in ('files', 'mongo', 'redis'):
        for component in config.get(kind, []):
            if not re.fullmatch('[a-z][a-z0-9_-]{0,63}', component['id']):
                raise BackupFailure('backup_component_identifier_invalid')
    if any(component.get('sensitive') for component in config.get('files', [])) and not config.get('encryption_recipient'):
        raise BackupFailure('secret_archive_encryption_recipient_required')
    writers = config.get('quiesce_containers', [])
    if (config.get('files') or config.get('mongo') or config.get('redis')) and not writers:
        raise BackupFailure('application_consistency_contract_missing')
    if writers and not config.get('quiesce_authorized', False):
        raise BackupFailure('service_quiescence_approval_required')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    reader_gid = config.get('reader_gid')
    if reader_gid is not None:
        os.chown(root, -1, reader_gid)
        root.chmod(0o750)
    with (root / '.backup.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BackupFailure('backup_already_running') from error
        created = timestamp()
        group = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + uuid.uuid4().hex
        stage = Path(tempfile.mkdtemp(prefix='.in-progress-', dir=root))
        stopped = []
        artifacts = []
        pointer = None
        def add(path, source, format_name, prerequisites, artifact_created_at):
            if path.stat().st_size == 0:
                raise BackupFailure('backup_artifact_empty')
            path.chmod(0o600)
            if reader_gid is not None:
                os.chown(path, -1, reader_gid)
                path.chmod(0o640)
            with path.open('rb') as stream:
                os.fsync(stream.fileno())
            entry = {'source': source, 'artifact': path.name, 'format': format_name,
                              'sha256': sha256(path), 'size_bytes': path.stat().st_size,
                              'created_at': artifact_created_at, 'completed_at': timestamp(),
                              'recovery_prerequisites': prerequisites}
            if source in config.get('off_source_copy_sources', []):
                copy_root = check_destination({'destination': config['off_source_destination']})
                copy_root.mkdir(parents=True, exist_ok=True, mode=0o700)
                if reader_gid is not None:
                    os.chown(copy_root, -1, reader_gid)
                    copy_root.chmod(0o750)
                destination = copy_root / (group + '-' + path.name)
                temporary = copy_root / ('.copy-' + uuid.uuid4().hex)
                metadata_temporary = copy_root / ('.copy-meta-' + uuid.uuid4().hex)
                try:
                    shutil.copyfile(path, temporary)
                    if sha256(temporary) != entry['sha256']:
                        raise BackupFailure('off_source_copy_integrity_failed')
                    if reader_gid is not None:
                        os.chown(temporary, -1, reader_gid)
                        temporary.chmod(0o640)
                    with temporary.open('rb') as stream:
                        os.fsync(stream.fileno())
                    check_destination({'destination': config['off_source_destination']})
                    os.rename(temporary, destination)
                    metadata = destination.with_name(destination.name + '.json')
                    with metadata_temporary.open('x') as stream:
                        json.dump(entry | {'artifact': str(destination), 'consumer': config['consumer'],
                                          'environment': config['environment'], 'recovery_group': group,
                                          'scope': 'additional_copy_of_nas_origin_state'}, stream)
                        stream.write('\n')
                        stream.flush()
                        os.fsync(stream.fileno())
                    if reader_gid is not None:
                        os.chown(metadata_temporary, -1, reader_gid)
                        metadata_temporary.chmod(0o640)
                    os.rename(metadata_temporary, metadata)
                    copy_directory = os.open(copy_root, os.O_RDONLY)
                    try:
                        os.fsync(copy_directory)
                    finally:
                        os.close(copy_directory)
                    entry['off_source_copy'] = {'artifact': str(destination),
                                               'metadata': str(metadata), 'sha256': entry['sha256'],
                                               'size_bytes': entry['size_bytes']}
                finally:
                    if temporary.exists():
                        temporary.unlink()
                    if metadata_temporary.exists():
                        metadata_temporary.unlink()
            artifacts.append(entry)
        try:
            for container in writers:
                running = command(['docker', 'inspect', '--format', '{{.State.Running}}', container])
                if running == 'true':
                    stopped.append(container)
                    command(['docker', 'stop', '--time', '60', container], timeout=90)
            recovery_point = timestamp()
            databases = backup_postgres(config, stage, add)
            backup_files(config, stage, add)
            # Restart writers before marking production complete. A restart failure
            # leaves the last published manifest untouched and is a backup failure.
            for container in reversed(stopped.copy()):
                command(['docker', 'start', container], timeout=90)
                stopped.remove(container)
            document = {'schema_version': 1, 'consumer': config['consumer'],
                        'environment': config['environment'], 'recovery_group': group,
                        'postgres_container': config['postgres']['container'],
                        'created_at': created, 'completed_at': timestamp(),
                        'recovery_point_at': recovery_point,
                        'max_age_seconds': config['max_age_seconds'], 'databases': databases,
                        'required_sources': [item['source'] for item in artifacts],
                        'artifacts': artifacts, 'backup_available': True,
                        'integrity_verified': True,
                        'restore_verification': {'result': 'not_run', 'completed_at': None},
                        'application_recovery_verified': False}
            manifest = stage / 'manifest.json'
            with manifest.open('w') as stream:
                json.dump(document, stream, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            if reader_gid is not None:
                os.chown(manifest, -1, reader_gid)
                manifest.chmod(0o640)
                os.chown(stage, -1, reader_gid)
                stage.chmod(0o750)
            staged_directory = os.open(stage, os.O_RDONLY)
            try:
                os.fsync(staged_directory)
            finally:
                os.close(staged_directory)
            check_destination(config)
            final = root / group
            os.rename(stage, final)
            pointer = root / ('.current-' + uuid.uuid4().hex + '.json')
            with pointer.open('w') as stream:
                json.dump({'schema_version': 1, 'manifest': group + '/manifest.json'}, stream)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            if reader_gid is not None:
                os.chown(pointer, -1, reader_gid)
                pointer.chmod(0o640)
            os.replace(pointer, root / 'current.json')
            directory = os.open(root, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            return {'status': 'completed', 'consumer': config['consumer'], 'group': group}
        finally:
            restart_failed = False
            for container in reversed(stopped):
                try:
                    command(['docker', 'start', container], timeout=90)
                except (BackupFailure, subprocess.TimeoutExpired):
                    restart_failed = True
            if stage.exists():
                shutil.rmtree(stage)
            if pointer is not None and pointer.exists():
                pointer.unlink()
            if restart_failed:
                raise BackupFailure('backup_failed_and_writer_restart_failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--schema')
    parser.add_argument('--validate-config', action='store_true')
    args = parser.parse_args()
    os.umask(0o077)
    config = None
    started = timestamp()
    def record(result):
        if config is not None and config.get('status_file'):
            status = Path(config['status_file'])
            status.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            temporary = status.with_name('.attempt-' + uuid.uuid4().hex)
            with temporary.open('w') as stream:
                json.dump(result | {'started_at': started, 'observed_at': timestamp()}, stream)
                stream.write('\n')
            os.replace(temporary, status)
    def deadline(signum, frame):
        raise BackupFailure('backup_deadline_or_termination')
    try:
        config = json.loads(Path(args.config).read_text())
        import jsonschema
        schema_path = Path(args.schema) if args.schema else Path(args.config).with_suffix('.schema.json')
        schema = json.loads(schema_path.read_text())
        try:
            jsonschema.Draft202012Validator(schema).validate(config)
        except jsonschema.ValidationError as error:
            raise BackupFailure('backup_configuration_schema_invalid') from error
        identities = ['postgres-globals', *config['postgres']['required_databases'],
                      *[item['id'] for kind in ('files', 'mongo', 'redis') for item in config.get(kind, [])]]
        if len(identities) != len(set(identities)):
            raise BackupFailure('backup_target_identity_collision')
        if args.validate_config:
            print(json.dumps({'status': 'passed', 'consumer': config['consumer']}))
            return 0
        signal.signal(signal.SIGTERM, deadline)
        signal.signal(signal.SIGALRM, deadline)
        signal.alarm(config.get('deadline_seconds', 3600))
        record({'status': 'running', 'consumer': config['consumer']})
        result = produce(config)
    except (BackupFailure, ImportError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        reason = str(error) if isinstance(error, BackupFailure) else type(error).__name__
        result = {'status': 'failed', 'reason': reason}
        try:
            record(result)
        except OSError:
            result['status_record'] = 'unavailable'
        print(json.dumps(result), file=sys.stderr)
        return 1
    finally:
        signal.alarm(0)
    try:
        record(result)
    except OSError:
        print(json.dumps({'status': 'failed', 'reason': 'completed_group_status_record_failed'}), file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
