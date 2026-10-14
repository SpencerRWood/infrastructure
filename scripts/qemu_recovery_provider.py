"""Offline amd64 QEMU resources, independent expiry and existing SDK binding.

The caller must supply a checksum-bound, reviewed blank Linux template and an
offline input disk with the consumer's guest agent. This module never downloads
credentials, executes a host restore role, enables consumer support or attaches
network/shared-storage devices. Missing capacity/template/input proof fails
before allocation. Guest phases use the existing consumer GuestPhases contract.
"""
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import time

from monthly_bootstrap import BootstrapFailure, GuestPhases
from qemu_resources import admit, capacity

GIB = 1024**3
RESOURCE = re.compile(r'recovery-[0-9a-f]{32}')
HASH = re.compile(r'[0-9a-f]{64}')
LIMIT = 65536


def checksum(file):
    with Path(file).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def safe_file(file, expected):
    file = Path(file)
    if (file.is_symlink() or not file.is_file() or ',' in str(file)
            or '\n' in str(file) or not HASH.fullmatch(expected)
            or checksum(file) != expected):
        raise BootstrapFailure('qemu_immutable_input_invalid')
    return file.resolve()


def save(path, document):
    """Atomic durable records; callers pass only fixed sanitized schemas."""
    path = Path(path)
    temporary = path.with_name('.' + path.name + '.new')
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, 'w') as output:
            json.dump(document, output, sort_keys=True)
            output.write('\n'); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def validate_root(root):
    root = Path(root)
    if (not root.is_absolute() or root.is_symlink() or not root.is_dir()
            or root.stat().st_uid != os.geteuid()
            or root.stat().st_mode & 0o077 or ',' in str(root)):
        raise BootstrapFailure('qemu_private_state_root_required')
    return root.resolve()


def identity_matches(pid, argv):
    if not isinstance(pid, int) or pid <= 1:
        return False
    try:
        actual = subprocess.check_output(['ps', '-p', str(pid), '-o', 'command='],
                                         text=True, stderr=subprocess.DEVNULL, timeout=5).strip()
        # QEMU is invoked without a shell. Exact command/resource binding guards
        # PID reuse; no process with a different argv may ever be signaled.
        return actual == ' '.join(argv) and os.getpgid(pid) == pid
    except (ProcessLookupError, subprocess.SubprocessError):
        return False


def destroy(root, resource):
    """Reaper/controller cleanup can only delete this registered owned directory."""
    root = validate_root(root)
    if not RESOURCE.fullmatch(resource):
        raise BootstrapFailure('qemu_resource_invalid')
    directory = root / resource
    lease_file = directory / 'lease.json'
    if not directory.exists():
        evidence = root / ('destruction-' + resource + '.json')
        if evidence.is_file() and json.loads(evidence.read_text()).get('state') == 'passed':
            return json.loads(evidence.read_text())
        raise BootstrapFailure('qemu_destruction_unobserved')
    if directory.is_symlink() or directory.stat().st_uid != os.geteuid():
        raise BootstrapFailure('qemu_owned_directory_required')
    with (directory / 'cleanup.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if lease_file.is_symlink() or not lease_file.is_file():
            raise BootstrapFailure('qemu_registered_lease_required')
        lease = json.loads(lease_file.read_text())
        if (lease['resource'] != resource or lease['owner_uid'] != os.geteuid()
                or lease['directory'] != str(directory)):
            raise BootstrapFailure('qemu_lease_owner_mismatch')
        pid = lease['pid']
        pid_file = directory / 'qemu.pid'
        if pid is None and pid_file.is_file() and not pid_file.is_symlink():
            pid = int(pid_file.read_text().strip())
        if pid is not None:
            if identity_matches(pid, lease['argv']):
                os.killpg(pid, signal.SIGTERM)
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline and identity_matches(pid, lease['argv']):
                    time.sleep(0.1)
                if identity_matches(pid, lease['argv']):
                    os.killpg(pid, signal.SIGKILL)
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline and identity_matches(pid, lease['argv']):
                    time.sleep(0.1)
                if identity_matches(pid, lease['argv']):
                    raise BootstrapFailure('qemu_process_cleanup_unobserved')
            else:
                # Exited processes are safe; a reused/live PID is never ours.
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    pass
                else:
                    raise BootstrapFailure('qemu_process_identity_changed')
        shutil.rmtree(directory)
        proof = {'state': 'passed', 'resource': resource, 'process_stopped': True,
                 'owned_disk_removed': True, 'credential_copies_removed': True,
                 'observed_at': dt.datetime.now(dt.timezone.utc).isoformat()}
        save(root / ('destruction-' + resource + '.json'), proof)
        return proof


def reap(root, resource):
    """Independent process survives controller exit; only this exact lease expires."""
    root = validate_root(root)
    if not RESOURCE.fullmatch(resource):
        raise BootstrapFailure('qemu_resource_invalid')
    next_sample = time.monotonic()
    while (root / resource).exists():
        lease = json.loads((root / resource / 'lease.json').read_text())
        expiry = dt.datetime.fromisoformat(lease['expires_at'])
        if expiry.tzinfo is None or lease['owner_uid'] != os.geteuid():
            raise BootstrapFailure('qemu_lease_invalid')
        remaining = (expiry - dt.datetime.now(dt.timezone.utc)).total_seconds()
        if remaining <= 0:
            return destroy(root, resource)
        if time.monotonic() >= next_sample and 'admission' in lease:
            try:
                observation = capacity(root)
                reason = None
                if observation['pressure'] != 1 or observation['pressure_before'] != 1:
                    reason = 'qemu_host_pressure_unsafe'
                elif observation['swap_in_bytes'] or observation['swap_out_bytes']:
                    reason = 'qemu_host_swap_active'
                elif observation['responsive'] is not True:
                    reason = 'qemu_host_unresponsive'
                elif observation['free_disk_bytes'] < lease['admission']['host_storage_reserve_bytes']:
                    reason = 'qemu_host_disk_reserve_exhausted'
                save(root / ('host-' + resource + '.json'), {'host': observation,
                     'state': 'failed' if reason else 'observed', 'reason': reason})
            except (OSError, ValueError, KeyError, subprocess.SubprocessError):
                reason = 'qemu_host_monitor_unavailable'
                save(root / ('host-' + resource + '.json'), {'state': 'failed', 'reason': reason})
            if reason:
                return destroy(root, resource)
            next_sample = time.monotonic() + 15
        time.sleep(min(remaining, 1))
    return {'state': 'already_removed'}


class OfflineQemu:
    def __init__(self, root, specification, clock=time.monotonic):
        self.root = validate_root(root)
        self.specification = specification
        self.clock = clock
        self.slot = None
        self.process = None

    def provision(self, resource_reference):
        spec = self.specification
        resource = resource_reference.removeprefix('temporary://')
        if not resource_reference.startswith('temporary://') or not RESOURCE.fullmatch(resource):
            raise BootstrapFailure('qemu_resource_invalid')
        if (spec['execution_authorized'] is not True or spec['architecture'] != 'amd64'
                or type(spec['maximum_seconds']) is not int
                or not 1 <= spec['maximum_seconds'] <= 7200
                or spec['production_access'] is not False
                or spec['private_identity_in_inputs'] is not False
                or spec['drill_only_credentials'] is not True
                or spec['guest_agent_verified'] is not True
                or not re.fullmatch(r'[0-9a-f]{40}', spec['source_revision'])
                or not HASH.fullmatch(spec['manifest_sha256'])):
            raise BootstrapFailure('qemu_reviewed_specification_required')
        admission = admit(capacity(self.root), spec)
        resources = admission['allocation']
        base = safe_file(spec['base_image'], spec['base_sha256'])
        inputs = safe_file(spec['input_disk'], spec['input_sha256'])
        qemu = Path(shutil.which('qemu-system-x86_64') or '')
        image_tool = shutil.which('qemu-img')
        if not qemu.is_file() or not image_tool:
            raise BootstrapFailure('qemu_installed_tools_required')
        self.slot = (self.root / 'slot.lock').open('a')
        try:
            fcntl.flock(self.slot, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.slot.close(); self.slot = None
            raise BootstrapFailure('qemu_single_vm_slot_occupied')
        if any(path.is_dir() and RESOURCE.fullmatch(path.name) for path in self.root.iterdir()):
            self.slot.close(); self.slot = None
            raise BootstrapFailure('qemu_prior_cleanup_unreconciled')
        # Recheck under the exclusive slot: input hashing/lock waits can change
        # host conditions. A rejected admission leaves no guest resources.
        try:
            admission = admit(capacity(self.root), spec)
        except Exception:
            self.slot.close(); self.slot = None
            raise
        self.directory = self.root / resource
        self.directory.mkdir(mode=0o700)
        self.resource = resource
        now = dt.datetime.now(dt.timezone.utc)
        expiry = now + dt.timedelta(seconds=spec['maximum_seconds'])
        disk = self.directory / 'guest.qcow2'
        self.channel = self.directory / 'channel.sock'
        argv = [str(qemu.resolve()), '-name', resource, '-machine', 'q35,accel=tcg',
                '-cpu', 'max', '-smp', str(resources['vcpus']),
                '-m', str(resources['memory_gib'] * 1024), '-nodefaults', '-nic', 'none',
                '-display', 'none', '-monitor', 'none', '-serial', 'none', '-no-reboot',
                '-pidfile', str(self.directory / 'qemu.pid'),
                '-drive', f'file={disk},format=qcow2,if=none,id=os',
                '-device', 'virtio-blk-pci,drive=os',
                '-drive', f'file={inputs},format=raw,if=none,id=inputs,readonly=on',
                '-device', 'virtio-blk-pci,drive=inputs',
                '-device', 'virtio-serial-pci', '-chardev',
                f'socket,id=control,path={self.channel},server=on,wait=off',
                '-device', 'virtserialport,chardev=control,name=org.wood.recovery']
        lease = {'schema_version': '1', 'resource': resource, 'directory': str(self.directory),
                 'owner_uid': os.geteuid(), 'expires_at': expiry.isoformat(), 'pid': None,
                 'argv': argv, 'source_revision': spec['source_revision'],
                 'manifest_sha256': spec['manifest_sha256'], 'admission': admission}
        save(self.directory / 'lease.json', lease)
        # Register and start expiry BEFORE creating the owned disk or QEMU process.
        self.reaper = subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
            '--reap', str(self.root), resource], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        subprocess.run([image_tool, 'create', '-f', 'qcow2', '-F', 'qcow2', '-b', str(base),
                        str(disk), str(resources['disk_gib']) + 'G'], check=True, timeout=20,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if dt.datetime.now(dt.timezone.utc) >= expiry:
            raise BootstrapFailure('qemu_allocation_lease_expired')
        self.process = subprocess.Popen(argv, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
            env={'PATH': os.defpath, 'HOME': str(self.directory)})
        lease['pid'] = self.process.pid
        save(self.directory / 'lease.json', lease)
        self.started = self.clock()
        return {'blank_guest': True, 'network_devices': 0, 'shared_mounts': 0,
                **resources, 'maximum_seconds': spec['maximum_seconds'],
                'resource_reference': resource_reference}

    def execute(self, phase, program, maximum_seconds):
        if (phase not in ('bootstrap', 'dependencies', 'secrets', 'recovery', 'restore',
                          'workloads', 'validation') or self.process is None
                or self.process.poll() is not None
                or self.clock() - self.started >= self.specification['maximum_seconds']):
            raise BootstrapFailure('qemu_guest_not_available')
        request = {'schema_version': '1', 'phase': phase,
                   'resource_reference': 'temporary://' + self.resource,
                   'source_revision': self.specification['source_revision'],
                   'manifest_sha256': self.specification['manifest_sha256'],
                   'program_sha256': checksum(program)}
        # No program paths, credentials, environment or arbitrary host command
        # crosses this interface. The sealed guest dispatches its bound programs.
        timeout = min(maximum_seconds, self.specification['maximum_seconds'] - (self.clock() - self.started))
        with socket.socket(socket.AF_UNIX) as channel:
            channel.settimeout(timeout)
            deadline = self.clock() + timeout
            while not self.channel.exists():
                if self.clock() >= deadline or self.process.poll() is not None:
                    raise BootstrapFailure('qemu_guest_channel_unavailable')
                time.sleep(0.1)
            channel.connect(str(self.channel))
            channel.sendall(json.dumps(request).encode() + b'\n')
            output = b''
            while not output.endswith(b'\n'):
                block = channel.recv(min(4096, LIMIT + 1 - len(output)))
                if not block or len(output) + len(block) > LIMIT:
                    raise BootstrapFailure('qemu_guest_response_invalid')
                output += block
            result = json.loads(output)
        return result

    def cleanup(self):
        try:
            result = destroy(self.root, self.resource)
            if self.process is not None:
                self.process.wait(timeout=3)
            return result
        finally:
            if self.slot is not None:
                self.slot.close(); self.slot = None


class QemuLinuxProvider:
    """Plugin for recovery_verification.drill.execute_drill, not a new lifecycle."""
    name = 'qemu-offline'

    def __init__(self, host, plan, prepare_guest):
        self.host, self.plan, self.prepare_guest = host, plan, prepare_guest
        self.guest = None

    def execute(self, phase, target, resource_reference):
        # SDK is an explicit runtime requirement; do not consult another loader.
        from recovery_verification.drill import PhaseResult
        from recovery_verification.models import DrillCheck, SnapshotEvidence
        if phase == 'cleanup':
            proof = self.host.cleanup() if hasattr(self.host, 'resource') else {'state': 'passed'}
            return PhaseResult(check=DrillCheck(id=phase, phase=phase, state=proof['state'],
                                               reason='owned_provider_resources_removed'))
        if phase == 'provision':
            if (target.revision != self.plan['source_revision']
                    or target.id != self.plan['consumer']
                    or {source.id for source in target.backup_sources} != {'current_recovery_group'}):
                raise BootstrapFailure('qemu_consumer_revision_mismatch')
            self.host.provision(resource_reference)
            self.plan = dict(self.plan, resource_reference=resource_reference)
            # The reviewed template's ready handshake generates a guest-only key.
            # Its explicit bridge prepares encrypted transport AFTER the SDK
            # assigned resource identity; presealed inputs for another VM fail.
            inputs, programs = self.prepare_guest(self.host, self.plan)
            self.guest = GuestPhases(self.plan, inputs, '/var/lib/recovery-drill',
                                     programs, self.host.execute)
        else:
            result = self.guest.run(phase)
            # GuestPhases already restricts proof names/values, revision/group
            # and phase order. Retain that sanitized result outside the VM disk.
            save(self.host.root / (self.host.resource + '-' + phase + '.json'), result)
        evidence = (SnapshotEvidence(source_id='current_recovery_group',
                    timestamp=dt.datetime.fromisoformat(self.plan['completed_at']),
                    artifact_sha256=self.plan['manifest_sha256']),) if phase == 'restore' else ()
        return PhaseResult(check=DrillCheck(id=phase, phase=phase, state='passed',
                                           reason='isolated_guest_phase_verified'), snapshots=evidence)


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] != '--reap':
        raise SystemExit('Explicit registered resource reaper required')
    try:
        reap(sys.argv[2], sys.argv[3])
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        raise SystemExit('Owned QEMU cleanup requires reconciliation')
