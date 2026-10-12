"""Read-only validation for recovery-backup v1 completed groups."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import re


class InvalidBackup(ValueError):
    """Stable sanitized reasons suitable for recovery evidence."""
    state = 'failed'


class UnavailableBackup(InvalidBackup):
    """Required backup evidence could not be read."""
    state = 'unavailable'


def read_yaml(path):
    import yaml
    class UniqueLoader(yaml.SafeLoader):
        pass
    def mapping(loader, node, deep=False):
        result = {}
        for key, value in node.value:
            name = loader.construct_object(key, deep=deep)
            if name in result:
                raise InvalidBackup('backup_yaml_duplicate_key')
            result[name] = loader.construct_object(value, deep=deep)
        return result
    UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    try:
        return yaml.load(Path(path).read_text(), Loader=UniqueLoader)
    except yaml.YAMLError as error:
        raise InvalidBackup('backup_yaml_invalid') from error


def load_policy(path):
    import jsonschema
    path = Path(path)
    if path.suffix not in {'.yml', '.yaml'}:
        raise InvalidBackup('backup_policy_yaml_required')
    policy = read_yaml(path)
    schema = json.loads((Path(__file__).resolve().parents[1] / 'recovery/backup-policy.schema.json').read_text())
    try:
        jsonschema.Draft202012Validator(schema).validate(policy)
    except jsonschema.ValidationError as error:
        raise InvalidBackup('backup_policy_schema_invalid') from error
    return policy


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def instant(value):
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise InvalidBackup('backup_timestamp_timezone_missing')
    return parsed


def regular(path):
    if path.is_symlink():
        raise InvalidBackup('backup_artifact_missing')
    if not path.is_file():
        raise UnavailableBackup('backup_artifact_missing')
    if path.stat().st_size <= 0:
        raise InvalidBackup('backup_artifact_empty')


def validate(pointer, policy, now=None):
    """Trust the repository policy, never a producer's self-declared coverage."""
    now = now or dt.datetime.now(dt.timezone.utc)
    pointer = Path(pointer)
    regular(pointer)
    reference = json.loads(pointer.read_text())
    if reference.get('schema_version') != 1:
        raise InvalidBackup('backup_pointer_version_unsupported')
    relative = Path(reference['manifest'])
    if (relative.is_absolute() or '..' in relative.parts or len(relative.parts) != 2
            or relative.name != 'manifest.json' or relative.parts[0].startswith('.')):
        raise InvalidBackup('backup_manifest_reference_invalid')
    group = pointer.parent / relative.parts[0]
    if group.is_symlink():
        raise InvalidBackup('backup_group_symlink')
    path = group / relative.name
    regular(path)
    manifest = json.loads(path.read_text())
    if manifest.get('schema_version') != 1:
        raise InvalidBackup('backup_manifest_version_unsupported')
    if (manifest['consumer'] != policy['consumer'] or manifest['environment'] != policy['environment']
            or manifest['postgres_container'] != policy['postgres_container']
            or manifest['recovery_group'] != relative.parts[0]):
        raise InvalidBackup('backup_origin_mismatch')
    completed = instant(manifest['completed_at'])
    if not 0 <= (now - completed).total_seconds() <= min(policy['max_age_seconds'], manifest['max_age_seconds']):
        raise InvalidBackup('backup_stale')
    created = instant(manifest['created_at'])
    if created > completed:
        raise InvalidBackup('backup_completion_invalid')
    maximum_age = min(policy['max_age_seconds'], manifest['max_age_seconds'])
    if not 0 <= (now - created).total_seconds() <= maximum_age:
        raise InvalidBackup('backup_source_stale')
    entries = manifest['artifacts']
    sources = [entry['source'] for entry in entries]
    names = [entry['artifact'] for entry in entries]
    if (not entries or len(sources) != len(set(sources)) or len(names) != len(set(names))
            or len(manifest['required_sources']) != len(set(manifest['required_sources']))
            or set(sources) != set(manifest['required_sources'])
            or not set(policy['required_sources']) <= set(sources)):
        raise InvalidBackup('backup_group_incomplete')
    if not set(manifest['databases']) <= set(sources):
        raise InvalidBackup('backup_database_artifact_missing')
    for entry in entries:
        name = entry['artifact']
        if Path(name).name != name or name in {'.', '..'}:
            raise InvalidBackup('backup_artifact_reference_invalid')
        artifact = group / name
        regular(artifact)
        if entry['size_bytes'] != artifact.stat().st_size:
            raise InvalidBackup('backup_size_mismatch')
        checksum = entry['sha256']
        if not re.fullmatch('[0-9a-f]{64}', checksum) or digest(artifact) != checksum:
            raise InvalidBackup('backup_checksum_mismatch')
        if entry['source'] in policy.get('off_source_copy_sources', []):
            copy = entry.get('off_source_copy')
            if not copy:
                raise InvalidBackup('required_off_source_copy_missing')
            copy_path = Path(copy['artifact'])
            if not copy_path.is_relative_to(Path(policy['off_source_copy_root'])) or '..' in copy_path.parts:
                raise InvalidBackup('off_source_copy_reference_invalid')
            regular(copy_path)
            metadata_path = Path(copy['metadata'])
            if metadata_path != copy_path.with_name(copy_path.name + '.json'):
                raise InvalidBackup('off_source_metadata_reference_invalid')
            regular(metadata_path)
            metadata = json.loads(metadata_path.read_text())
            if any(metadata.get(key) != value for key, value in {
                'artifact': str(copy_path), 'consumer': policy['consumer'],
                'environment': policy['environment'], 'source': entry['source'],
                'recovery_group': manifest['recovery_group'], 'sha256': checksum,
                'size_bytes': entry['size_bytes'],
            }.items()):
                raise InvalidBackup('off_source_copy_metadata_mismatch')
            if (copy['sha256'] != checksum or copy_path.stat().st_size != entry['size_bytes']
                    or digest(copy_path) != checksum):
                raise InvalidBackup('off_source_copy_integrity_failed')
        if entry['format'] not in {'postgres-custom', 'postgres-sql', 'tar-gzip', 'tar-gzip-age', 'mongo-archive-gzip', 'redis-rdb'}:
            raise InvalidBackup('backup_format_unsupported')
        if not created <= instant(entry['created_at']) <= instant(entry['completed_at']) <= completed:
            raise InvalidBackup('backup_artifact_timestamp_invalid')
        if not 0 <= (now - instant(entry['created_at'])).total_seconds() <= maximum_age:
            raise InvalidBackup('backup_source_stale')
        if entry['format'] == 'postgres-custom':
            with artifact.open('rb') as stream:
                if stream.read(5) != b'PGDMP':
                    raise InvalidBackup('backup_format_mismatch')
            if entry['recovery_prerequisites']['roles_artifact'] not in names:
                raise InvalidBackup('backup_roles_artifact_missing')
        if entry['format'] == 'redis-rdb':
            with artifact.open('rb') as stream:
                if stream.read(5) != b'REDIS':
                    raise InvalidBackup('backup_format_mismatch')
    # Producer integrity claims are not restore evidence. Restoration status is
    # recorded separately by the isolated consumer verification mechanism.
    return manifest, group, digest(path)
