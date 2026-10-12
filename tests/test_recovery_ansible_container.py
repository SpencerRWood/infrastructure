"""Opt-in local-image regression; no pulls, deployment or recovery execution.

Run with RECOVERY_TEST_IMAGE=<local image ID> and unittest discovery. The regular
suite checks the static security contract in test_recovery_runtime.py; this test
requires the separately built Linux candidate and a running Docker daemon.
"""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).parents[1]
IMAGE = os.environ.get('RECOVERY_TEST_IMAGE')

# Run inside the image, under the Compose UID and filesystem/security settings.
# Match the consumer's explicit child environment; do not inherit Ansible temp,
# credentials, callbacks or connection settings from the container environment.
PROBE = r'''
import errno
import json
import os
import stat
import subprocess

corrected = os.environ['TEST_CORRECTED'] == '1'
assert os.getuid() == os.getgid() == 10001
assert os.uname().sysname == 'Linux' and os.uname().machine == 'x86_64'
status = open('/proc/self/status').read()
assert 'CapEff:\t0000000000000000' in status
assert 'NoNewPrivs:\t1' in status
try:
    open('/home/app/read-only-root-probe', 'w').close()
except OSError as error:
    assert error.errno == errno.EROFS, error
else:
    raise AssertionError('root filesystem writable')
with open('/tmp/disposable-write-probe', 'w') as handle:
    handle.write('disposable')
if corrected:
    directory = '/home/app/.ansible'
    info = os.stat(directory)
    assert info.st_uid == info.st_gid == 10001
    assert stat.S_IMODE(info.st_mode) == 0o700
    filesystem = os.statvfs(directory)
    assert filesystem.f_blocks * filesystem.f_frsize <= 64 * 1024 * 1024
    mount = next(line.split() for line in open('/proc/mounts')
                 if line.split()[1] == directory)
    assert mount[2] == 'tmpfs'
    assert {'rw', 'nosuid', 'nodev'} <= set(mount[3].split(','))
    with open(directory + '/disposable-write-probe', 'w') as handle:
        handle.write('disposable')
env = {
    'PATH': os.environ['PATH'], 'LANG': 'C.UTF-8',
    'PYTHONDONTWRITEBYTECODE': '1',
    'ANSIBLE_CONFIG': '/inputs/ansible.cfg', 'ANSIBLE_NOCOLOR': '1',
}
commands = [
    ['ansible', '--version'],
    ['ansible-inventory', '--list', '-i', '/inputs/inventory.yml'],
    ['ansible-playbook', '--syntax-check', '-i', '/inputs/inventory.yml',
     '/inputs/playbook.yml'],
]
results = []
for command in commands:
    result = subprocess.run(command, env=env, capture_output=True, text=True,
                            timeout=45)
    if corrected:
        assert result.returncode == 0, (command, result.stderr)
        if command[0] == 'ansible-inventory':
            assert 'localhost' in json.loads(result.stdout)['_meta']['hostvars']
    else:
        assert result.returncode != 0, command
        assert '/home/app/.ansible' in result.stderr, result.stderr
        assert 'Read-only file system' in result.stderr, result.stderr
    results.append({'command': command, 'exit_code': result.returncode})
print(json.dumps({'corrected': corrected, 'uid': os.getuid(),
                  'sanitized_environment_keys': sorted(env),
                  'root_read_only': True, 'results': results}))
'''


@unittest.skipUnless(IMAGE, 'set RECOVERY_TEST_IMAGE to the approved local Linux image ID')
class RecoveryAnsibleContainerTests(unittest.TestCase):
    def run_command(self, arguments, **kwargs):
        result = subprocess.run(arguments, capture_output=True, text=True,
                                timeout=180, **kwargs)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def test_rendered_compose_security_and_positive_negative_ansible(self):
        self.assertTrue(IMAGE.startswith('sha256:'), 'use an immutable local image ID')
        image = json.loads(self.run_command(['docker', 'image', 'inspect', IMAGE]))[0]
        self.assertEqual(image['Os'], 'linux')
        self.assertEqual(image['Architecture'], 'amd64')
        with tempfile.TemporaryDirectory(prefix='op500-ansible-') as temporary:
            fixtures = Path(temporary)
            (fixtures / 'inventory.yml').write_text(
                'all:\n  hosts:\n    localhost:\n      ansible_connection: local\n')
            (fixtures / 'playbook.yml').write_text(
                '- hosts: all\n  gather_facts: false\n  tasks:\n'
                '    - name: Disposable syntax check\n'
                '      ansible.builtin.debug:\n        msg: disposable\n')
            (fixtures / 'ansible.cfg').write_text((ROOT / 'recovery/ansible.cfg').read_text())
            # Native Linux bind mounts retain host ownership; these public,
            # disposable inputs must be readable by the container's UID 10001.
            fixtures.chmod(0o755)
            for fixture in fixtures.iterdir():
                fixture.chmod(0o644)
            environment = dict(os.environ)
            environment.update({
                'RECOVERY_PROJECT_NAME': 'op500-syntax-only',
                'RECOVERY_IMAGE_REF': IMAGE,
                'RECOVERY_RUNTIME_ENV_FILE': '/dev/null',
                'RECOVERY_CONFIG_PATH': '/tmp/disposable-config',
                'RECOVERY_CHECKOUTS_PATH': '/tmp/disposable-checkouts',
                'RECOVERY_STATE_PATH': '/tmp/disposable-state',
                'RECOVERY_STORAGE_PATH': '/tmp/disposable-storage',
                'RECOVERY_DAGSTER_CONFIG_PATH': '/tmp/disposable-dagster-config',
                'RECOVERY_DAGSTER_LOCAL_PATH': '/tmp/disposable-dagster-local',
                'RECOVERY_POSTGRES_NETWORK': 'syntax-postgres',
                'RECOVERY_PROXY_NETWORK': 'syntax-proxy',
            })
            rendered = json.loads(self.run_command([
                'docker', 'compose', '-f',
                str(ROOT / 'compose/recovery-verification/compose.yml'),
                'config', '--format', 'json'], env=environment))
            service = rendered['services']['recovery-verification-code']
            self.assertTrue(service['read_only'])
            self.assertEqual(service['user'], '10001:10001')
            self.assertEqual(service['cap_drop'], ['ALL'])
            self.assertEqual(service['security_opt'], ['no-new-privileges:true'])
            self.assertNotIn('ANSIBLE_LOCAL_TEMP', service['environment'])
            self.assertIn('/tmp', service['tmpfs'])
            self.assertEqual(len(service['tmpfs']), 2)
            for corrected in (False, True):
                with self.subTest(corrected=corrected):
                    arguments = [
                        'docker', 'run', '--rm', '--pull=never',
                        '--platform=linux/amd64', '--network=none', '--read-only',
                        '--user', service['user'],
                        '--mount', f'type=bind,source={fixtures},target=/inputs,readonly',
                        '--env', f'TEST_CORRECTED={int(corrected)}',
                        '--entrypoint', 'python',
                    ]
                    for capability in service['cap_drop']:
                        arguments.extend(['--cap-drop', capability])
                    for group in service['group_add']:
                        arguments.extend(['--group-add', str(group)])
                    for option in service['security_opt']:
                        arguments.extend(['--security-opt', option])
                    for mount in service['tmpfs']:
                        if corrected or not mount.startswith('/home/app/.ansible:'):
                            arguments.extend(['--tmpfs', mount])
                    arguments.extend([IMAGE, '-c', PROBE])
                    evidence = json.loads(self.run_command(arguments))
                    self.assertEqual(evidence['corrected'], corrected)
                    print(json.dumps(evidence, sort_keys=True))
