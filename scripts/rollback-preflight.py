#!/usr/bin/env python3
"""Check the selected immutable rollback release's custody gate before apply."""

import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

import yaml


def check(root, ref):
    if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', ref):
        raise ValueError('rollback_release_tag_required')

    def git(*args):
        return subprocess.check_output(['git', *args], cwd=root, text=True, timeout=30,
                                       stderr=subprocess.PIPE)

    revision = git('rev-parse', '--verify', f'refs/tags/{ref}^{{commit}}').strip()
    subprocess.run(['git', 'merge-base', '--is-ancestor', revision, 'HEAD'],
                   cwd=root, check=True, capture_output=True, timeout=30)
    tasks = yaml.safe_load(git('show', f'{revision}:ansible/roles/recovery_verification/tasks/main.yml'))
    # Evaluate the selected release's actual assertion, including its own role
    # defaults and environment bindings. Never inject a newer custody exception.
    assertions = tasks[0]['ansible.builtin.assert']['that']
    custody = [item for item in assertions if 'independent_custody_verified' in item]
    if len(custody) != 1:
        raise ValueError('rollback_custody_gate_unavailable')
    with tempfile.TemporaryDirectory(prefix='rollback-custody-') as temporary:
        directory = Path(temporary)
        sources = ['ansible/roles/backups/defaults/main.yml', 'environments/dev.yml']
        files = []
        for index, source in enumerate(sources):
            path = directory / f'vars-{index}.yml'
            path.write_text(git('show', f'{revision}:{source}'))
            files.append(str(path))
        playbook = directory / 'check.yml'
        playbook.write_text(yaml.safe_dump([{
            'hosts': 'localhost', 'gather_facts': False, 'vars_files': files,
            'tasks': [{'ansible.builtin.assert': {'that': custody}}],
        }]))
        subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local',
                        str(playbook), '--check'], check=True, capture_output=True,
                       timeout=30, env=os.environ | {
                           'ANSIBLE_CONFIG': str(Path(root) / 'recovery/ansible.cfg'),
                           'ANSIBLE_LOCAL_TEMP': str(directory / 'local'),
                           'ANSIBLE_REMOTE_TEMP': str(directory / 'remote'),
                       })
    return revision


def main():
    ref = os.environ.get('PREVIOUS_REF', '')
    try:
        revision = check(Path(__file__).resolve().parents[1], ref)
    except (ValueError, KeyError, TypeError, IndexError, OSError, yaml.YAMLError,
            subprocess.SubprocessError):
        print(json.dumps({'status': 'blocked', 'release': ref,
                          'reason': 'rollback_custody_preflight_failed'}))
        return 1
    print(json.dumps({'status': 'passed', 'release': ref, 'revision': revision,
                      'check': 'selected_release_backup_custody',
                      'live_rollback': False}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
