#!/usr/bin/env python3
"""Validate canonical YAML backup definitions without probing a live host."""
import json
from pathlib import Path
import sys

from recovery_manifest import InvalidBackup, load_policy, read_yaml

ROOT = Path(__file__).resolve().parents[1]


def verify(configuration_file):
    import jsonschema
    config = read_yaml(configuration_file)['backups_configuration']
    schema = json.loads((ROOT / 'recovery/backup-config.schema.json').read_text())
    try:
        jsonschema.Draft202012Validator(schema).validate(config)
    except jsonschema.ValidationError as error:
        raise InvalidBackup('backup_configuration_schema_invalid') from error
    policy = load_policy(ROOT / 'recovery/backup-policy.yml')
    ids = [item['id'] for kind in ('files', 'mongo', 'redis') for item in config.get(kind, [])]
    sources = ['postgres-globals', *config['postgres']['required_databases'], *ids]
    if len(sources) != len(set(sources)):
        raise InvalidBackup('backup_target_identity_collision')
    if set(sources) != set(policy['required_sources']):
        raise InvalidBackup('backup_coverage_policy_mismatch')
    if (config['consumer'] != policy['consumer'] or config['environment'] != policy['environment']
            or config['postgres']['container'] != policy['postgres_container']
            or config['destination']['root'] + '/current.json' != policy['pointer']
            or config['max_age_seconds'] != policy['max_age_seconds']):
        raise InvalidBackup('backup_configuration_policy_mismatch')
    if config['encryption_recipient'] != policy.get('encryption_recipient'):
        raise InvalidBackup('backup_encryption_policy_mismatch')
    if policy['restore_database'] not in config['postgres']['required_databases']:
        raise InvalidBackup('backup_restore_database_not_configured')
    if policy.get('restore_file_source') not in [item['id'] for item in config.get('files', [])]:
        raise InvalidBackup('backup_restore_file_not_configured')
    if config.get('off_source_copy_sources', []) != policy.get('off_source_copy_sources', []):
        raise InvalidBackup('backup_off_source_policy_mismatch')
    if config.get('off_source_copy_sources') and (
            config['off_source_destination']['root'] != policy['off_source_copy_root']):
        raise InvalidBackup('backup_off_source_destination_mismatch')
    return {'status': 'passed', 'consumer': config['consumer'], 'targets': sources,
            'retention_pruning_enabled': config['retention']['pruning_enabled'],
            'schedule': config['schedule']}


if __name__ == '__main__':
    try:
        result = verify(ROOT / sys.argv[1])
    except (InvalidBackup, OSError, ValueError, KeyError, TypeError, IndexError):
        print(json.dumps({'status': 'failed', 'reason': 'backup_configuration_invalid'}))
        raise SystemExit(1)
    print(json.dumps(result))
