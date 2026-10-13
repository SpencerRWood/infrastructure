#!/usr/bin/env python3
"""Check reviewed recovery consumer selections without changing their checkouts."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def verify(configuration, checkout_directory, prepare=False):
    config = json.loads(Path(configuration).read_text())
    manifest = json.loads(config['manifest_json'])
    targets = manifest['targets']
    ids = {target['id'] for target in targets}
    if len(ids) != len(targets) or ids != set(config['manifest_exports']) or ids != set(config['checkouts']):
        raise ValueError('consumer_mapping_invalid')
    root = Path(checkout_directory).resolve()
    results = []
    selections = []
    for target in targets:
        name = Path(config['checkouts'][target['id']]).name
        checkout = root / name
        if checkout.is_symlink() or not checkout.resolve().is_relative_to(root):
            raise ValueError('consumer_checkout_unsafe')
        export = config['manifest_exports'][target['id']]
        entrypoint = checkout / export['entrypoint']
        if entrypoint.is_symlink() or not entrypoint.resolve().is_relative_to(checkout):
            raise ValueError('consumer_export_unsafe')
        process = subprocess.run([str(entrypoint), *export['args']], cwd=checkout,
                                 capture_output=True, text=True, timeout=min(export['timeout_seconds'], 15),
                                 check=True)
        if len(process.stdout.encode()) > 65536:
            raise ValueError('consumer_export_limit')
        actual = json.loads(process.stdout)
        if (actual.get('schema_version') != '1' or len(actual.get('targets', [])) != 1
                or any(actual['targets'][0].get(key) != target.get(key)
                       for key in ('id', 'owning_repository'))):
            raise ValueError('consumer_identity_selection_mismatch')
        if not prepare and actual != {'schema_version': '1', 'targets': [target]}:
            raise ValueError('consumer_manifest_selection_mismatch')
        selections.extend(actual['targets'])
        results.append({'target_id': target['id'], 'revision': actual['targets'][0]['revision'], 'state': 'passed'})
    result = {'state': 'passed', 'consumers': results}
    if prepare:
        config['manifest_json'] = json.dumps({'schema_version': '1', 'targets': selections}, sort_keys=True, separators=(',', ':'))
        result['configuration'] = config
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--configuration', required=True)
    parser.add_argument('--checkout-directory', required=True)
    parser.add_argument('--prepare', action='store_true',
                        help='Export a reviewable selection from clean sources; never update runtime or clones')
    args = parser.parse_args()
    try:
        result = verify(args.configuration, args.checkout_directory, args.prepare)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({'state': 'failed', 'reason': 'reviewed_consumer_selection_unverified'}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    sys.exit(main())
