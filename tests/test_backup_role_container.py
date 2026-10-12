"""Opt-in backup-role convergence in a disposable, network-free Linux container."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
IMAGE = os.environ.get('BACKUPS_ROLE_TEST_IMAGE')
PROBE = r"""
import json,os,re,subprocess
from pathlib import Path
base=Path('/tmp/backup-role-test'); base.mkdir(mode=0o700)
binary=base/'bin'; binary.mkdir()
cron=binary/'crontab'
cron.write_text('''#!/bin/sh
record=/tmp/backup-role-test/root.crontab
case "$*" in
*" -l"|"-l") test -f "$record" || exit 1; cat "$record";;
*) for argument in "$@"; do file="$argument"; done; cp "$file" "$record";;
esac
''')
cron.chmod(0o755)
playbook=base/'playbook.yml'
playbook.write_text('''---
- name: Exercise only the backup installation role
  hosts: localhost
  connection: local
  gather_facts: false
  vars_files: [/inputs/environments/dev.yml]
  vars:
    infrastructure_environment: dev
  tasks:
    - name: Apply the repository backup role in disposable storage
      ansible.builtin.include_role:
        name: /inputs/ansible/roles/backups
      vars:
        playbook_dir: /inputs/ansible/playbooks
''')
environment={**os.environ,'PATH':str(binary)+':'+os.environ['PATH'],
             'HOME':str(base),'ANSIBLE_LOCAL_TEMP':str(base/'ansible'),
             'ANSIBLE_CONFIG':'/inputs/ansible/ansible.cfg','ANSIBLE_NOCOLOR':'1'}
records=[]
for attempt in (1,2):
    result=subprocess.run(['ansible-playbook','-i','localhost,',str(playbook)],env=environment,
                          capture_output=True,text=True,timeout=90)
    (base/f'ansible-{attempt}.log').write_text(result.stdout+result.stderr)
    if result.returncode:
        import sys
        print(result.stdout+result.stderr,file=sys.stderr)
        raise RuntimeError('backup_role_application_failed')
    recaps=re.findall(r'localhost\s*:\s*ok=(\d+)\s+changed=(\d+)\s+unreachable=(\d+)\s+failed=(\d+)',result.stdout)
    assert len(recaps)==1 and recaps[0][2:]==('0','0')
    records.append(int(recaps[0][1]))
assert records[0]>0 and records[1]==0,records
helper=Path('/usr/local/sbin/infrastructure-recovery-backup').stat()
configuration=Path('/etc/infrastructure/recovery-backup.json')
assert helper.st_uid==0 and helper.st_mode&0o777==0o700
assert configuration.stat().st_uid==0 and configuration.stat().st_mode&0o777==0o600
config=json.loads(configuration.read_text())
assert config['postgres']['container']=='infrastructure-dev-postgres-postgres-1'
assert config['reader_gid']==10001 and config['quiesce_authorized'] is False
assert not any('PASSWORD' in name for name in config)
assert '45 2 * * *' in (base/'root.crontab').read_text()
print(json.dumps({'changed':records,'helper_mode':'0700','config_mode':'0600',
                  'scheduler':'fixture-crontab','scope':'installation_only_no_backup_execution'}))
"""


@unittest.skipUnless(IMAGE, 'Set BACKUPS_ROLE_TEST_IMAGE to an existing local Linux image with Ansible')
class BackupRoleContainerTests(unittest.TestCase):
    def test_role_is_idempotent_and_installs_protected_current_contract(self):
        result = subprocess.run([
            'docker', 'run', '--rm', '--network', 'none', '--user', '0:0',
            '--mount', f'type=bind,src={ROOT},dst=/inputs,readonly',
            '--entrypoint', 'python3', IMAGE, '-c', PROBE,
        ], capture_output=True, text=True, timeout=210, check=False)
        descriptor, log = tempfile.mkstemp(prefix='backup-role-container-', suffix='.log')
        with os.fdopen(descriptor, 'w') as stream:
            stream.write(result.stdout + result.stderr)
        self.assertEqual(result.returncode, 0, 'Disposable backup-role test failed; log: ' + log)
        evidence = json.loads(result.stdout)
        self.assertEqual(evidence['changed'][1], 0)
        self.assertEqual(evidence['scope'], 'installation_only_no_backup_execution')


if __name__ == '__main__':
    unittest.main()
