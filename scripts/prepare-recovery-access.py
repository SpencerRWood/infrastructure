#!/usr/bin/env python3
"""Produce exact non-secret Infisical grants for one administrator review."""
import argparse
import json
from pathlib import Path
import re

from recovery_manifest import read_yaml


def prepare(root, homelab):
    root, homelab = Path(root), Path(homelab)
    plan = json.loads((root / 'recovery/probe-access.v1.json').read_text())
    catalogs = {
        'Infrastructure Dev': json.loads((root / 'recovery/runtime-secrets.v1.json').read_text())['services'],
        'Homelab': read_yaml(homelab / 'ansible/inventory/group_vars/homelab.yml')['infisical_runtime_services'],
        'CI': {'ghcr': {'environment': 'ci', 'path': '/github', 'required_keys': ['WEBSITE_PORTFOLIO_GHCR_TOKEN']}},
    }
    grants = []
    for project, services in catalogs.items():
        for service in services.values():
            names = sorted(set(service['required_keys']))
            if (not names or any(not re.fullmatch(r'[A-Z][A-Z0-9_]*', name) for name in names)
                    or not re.fullmatch(r'/[a-z][a-z0-9/-]*', service['path'])):
                raise ValueError('metadata_scope_invalid')
            grants.append({'project_id': plan['project_mapping'][project], 'action': 'describeSecret',
                           'subject': 'secrets', 'conditions': {'environment': service['environment'],
                           'secretPath': service['path'], 'secretName': {'$in': names}}})
    return {'schema_version': '1', 'identity': plan['metadata_identity'], 'grants': grants,
            'values_access': False, 'applied': False,
            'denied_actions': ['read', 'readValue', 'create', 'edit', 'delete'],
            'runtime_storage': {'project': 'Infrastructure Dev', 'environment': 'dev',
                                'path': '/recovery-verification', 'names': plan['required_runtime_names']},
            'staging_storage': {'project': 'Infrastructure Dev', 'environment': 'dev',
                                'path': '/recovery-verification-staged-op500',
                                'promote_only_during_approved_deployment': True},
            'registry_reader': {'proposed_principal': 'wood-recovery-reader', 'principal_verified': False,
                                'token_type': 'personal-access-token-classic', 'scopes': ['read:packages'],
                                'packages': ['SpencerRWood/automerge-repair', 'SpencerRWood/events-service',
                                             'SpencerRWood/portfolio-website', 'SpencerRWood/rag-service',
                                             'SpencerRWood/recovery-verification'],
                                'package_permission': 'read', 'repository_access': False,
                                'rotation_days': 21, 'expiry_days': 30}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--homelab', required=True)
    args = parser.parse_args()
    try:
        result = prepare(Path(__file__).resolve().parents[1], args.homelab)
    except (OSError, ValueError, KeyError, TypeError):
        print(json.dumps({'state': 'failed', 'reason': 'metadata_access_plan_invalid'}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
