"""Provider-independent offline bootstrap inputs and fail-closed guest execution.

This module is called by a reviewed disposable-VM backend, never by normal host
roles. It does not create a VM, obtain credentials, mount NAS or enable capability.
The existing provider SDK owns phase ordering and independent resource cleanup.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import tarfile
import uuid

from recovery_manifest import digest, instant, load_policy, validate

PHASES = ('bootstrap', 'dependencies', 'secrets', 'recovery', 'restore',
          'workloads', 'validation')
NAME = re.compile(r'[a-z][a-z0-9_-]{0,62}')


class BootstrapFailure(ValueError):
    """Only stable identifiers may escape the guest boundary."""


def regular(path, maximum=None):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or (maximum and path.stat().st_size > maximum):
        raise BootstrapFailure('bootstrap_input_invalid')
    return path


def prepare(root, now=None):
    """Read the current authoritative inventory; return no secret or file bytes."""
    root = Path(root).resolve()
    policy = load_policy(root / 'recovery/backup-policy.yml')
    manifest, group, group_hash = validate(policy['pointer'], policy, now=now)
    process = subprocess.run(['git', 'status', '--porcelain'], cwd=root,
                             capture_output=True, text=True, timeout=10, check=True)
    if process.stdout:
        raise BootstrapFailure('clean_consumer_required')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root,
                                       text=True, timeout=10).strip()
    catalog = json.loads((root / 'recovery/artifacts.v1.json').read_text())
    workloads = json.loads((root / 'recovery/monthly-workloads.v1.json').read_text())
    images, missing = [], []
    for reference in catalog['references']:
        if re.fullmatch(r'oci://[A-Za-z0-9_./:-]+@sha256:[0-9a-f]{64}', reference):
            images.append(reference)
        elif reference.startswith('image-archive:///'):
            images.append(reference)
        elif reference.startswith('build://'):
            missing.append(reference)
        else:
            raise BootstrapFailure('immutable_image_required')
    return {
        'schema_version': '1', 'consumer': policy['consumer'],
        'source_revision': revision, 'group': manifest['recovery_group'],
        'manifest_sha256': group_hash, 'completed_at': manifest['completed_at'],
        'encryption_recipient': policy['encryption_recipient'],
        'required_sources': policy['required_sources'],
        'artifacts': [{key: entry[key] for key in ('source', 'artifact', 'format', 'sha256', 'size_bytes')}
                      for entry in manifest['artifacts']],
        'images': images, 'unretained_images': missing,
        'required_services': workloads['required_services'],
        'representative_queries': {policy['restore_database']: policy['representative_queries']},
        'group_path': str(group), 'execution_authorized': False,
        'resource_reference': None,
        'maximum_lifetime_seconds': 7200,
        'required_guest_programs': ['age', 'docker', 'python3', 'initdb', 'pg_ctl',
                                    'psql', 'pg_restore', 'pg_amcheck', 'mongod',
                                    'mongorestore', 'mongosh', 'redis-server',
                                    'redis-cli', 'redis-check-rdb'],
        'required_phases': list(PHASES),
    }


def verify_staged(plan, inputs, now=None):
    """Validate all copied ciphertext before a guest can decrypt any artifact."""
    inputs = Path(inputs).resolve()
    now = now or dt.datetime.now(dt.timezone.utc)
    if not re.fullmatch(r'[0-9a-f]{40}', plan['source_revision']):
        raise BootstrapFailure('source_revision_invalid')
    age = (now - instant(plan['completed_at'])).total_seconds()
    if not 0 <= age <= 86400:
        raise BootstrapFailure('staged_group_stale')
    manifest_path = regular(inputs / 'manifest.json', 1048576)
    if digest(manifest_path) != plan['manifest_sha256']:
        raise BootstrapFailure('staged_manifest_mismatch')
    manifest = json.loads(manifest_path.read_text())
    if (manifest['recovery_group'] != plan['group']
            or manifest['completed_at'] != plan['completed_at']
            or not set(plan['required_sources']) <= {e['source'] for e in manifest['artifacts']}):
        raise BootstrapFailure('staged_group_identity_mismatch')
    expected = [{key: e[key] for key in ('source', 'artifact', 'format', 'sha256', 'size_bytes')}
                for e in manifest['artifacts']]
    if expected != plan['artifacts']:
        raise BootstrapFailure('staged_inventory_mismatch')
    sources = set()
    transfer = json.loads(regular(inputs / 'transport.json', 1048576).read_text())
    if (transfer['source_revision'] != plan['source_revision']
            or transfer['manifest_sha256'] != plan['manifest_sha256']
            or transfer['resource_reference'] != plan['resource_reference']
            or not re.fullmatch(r'age1[0-9a-z]{58}', transfer['guest_recipient'])
            or transfer['guest_recipient'] == plan['encryption_recipient']
            or set(transfer['artifacts']) != {entry['source'] for entry in plan['artifacts']}):
        raise BootstrapFailure('drill_transport_identity_invalid')
    for entry in plan['artifacts']:
        if (not NAME.fullmatch(entry['source']) or entry['source'] in sources
                or Path(entry['artifact']).name != entry['artifact']
                or entry['artifact'] in {'.', '..'} or not entry['format'].endswith('-age')):
            raise BootstrapFailure('staged_artifact_reference_invalid')
        sources.add(entry['source'])
        transported = transfer['artifacts'][entry['source']]
        if (transported['source_ciphertext_sha256'] != entry['sha256']
                or Path(transported['artifact']).name != transported['artifact']
                or not re.fullmatch(r'[0-9a-f]{64}', transported['plaintext_sha256'])):
            raise BootstrapFailure('drill_transport_source_binding_invalid')
        path = regular(inputs / transported['artifact'])
        if path.stat().st_size != transported['size_bytes'] or digest(path) != transported['ciphertext_sha256']:
            raise BootstrapFailure('staged_ciphertext_mismatch')
        original = next(e for e in manifest['artifacts'] if e['source'] == entry['source'])
        if original.get('encryption') != {'format': 'age', 'recipient': plan['encryption_recipient']}:
            raise BootstrapFailure('staged_recipient_mismatch')
        with path.open('rb') as stream:
            if stream.read(22) != b'age-encryption.org/v1\n':
                raise BootstrapFailure('staged_encryption_invalid')
    if plan['unretained_images']:
        raise BootstrapFailure('independent_image_artifacts_required')
    return {'state': 'passed', 'manifest_sha256': plan['manifest_sha256'],
            'source_revision': plan['source_revision'], 'artifacts': len(sources)}


def verify_workloads(document, workspace, images, limits):
    """Reject Compose escape routes before starting applications in the guest."""
    workspace = Path(workspace).resolve()
    if set(document) != {'services', 'networks'} or not document['services']:
        raise BootstrapFailure('isolated_workload_contract_invalid')
    networks = document['networks']
    if networks != {'recovery': {'internal': True}}:
        raise BootstrapFailure('isolated_network_required')
    memory, cpus = 0, 0
    required = {'image', 'networks', 'mem_limit', 'cpus', 'volumes', 'healthcheck'}
    optional = {'command', 'entrypoint', 'environment', 'env_file', 'user', 'read_only',
                'tmpfs', 'depends_on', 'restart', 'security_opt', 'cap_drop'}
    for name, service in document['services'].items():
        if (not NAME.fullmatch(name) or not required <= set(service)
                or set(service) - required - optional
                or (service['image'] if service['image'].startswith('image-archive://')
                    else 'oci://' + service['image']) not in images
                or service['networks'] != ['recovery']
                or service.get('restart', 'no') != 'no'
                or service.get('security_opt') != ['no-new-privileges:true']
                or service.get('cap_drop') != ['ALL']):
            raise BootstrapFailure('isolated_workload_boundary_invalid')
        if service.get('environment'):
            raise BootstrapFailure('drill_credentials_require_protected_file')
        if isinstance(service['mem_limit'], bool) or isinstance(service['cpus'], bool):
            raise BootstrapFailure('workload_limits_invalid')
        if not 0 < service['mem_limit'] <= limits['memory_bytes'] or not 0 < service['cpus'] <= limits['vcpus']:
            raise BootstrapFailure('workload_limits_invalid')
        memory += service['mem_limit']
        cpus += service['cpus']
        for volume in service['volumes']:
            if (not isinstance(volume, dict) or set(volume) != {'type', 'source', 'target', 'read_only'}
                    or volume['type'] != 'bind' or not isinstance(volume['read_only'], bool)):
                raise BootstrapFailure('guest_local_bind_required')
            source = Path(volume['source'])
            if (not source.is_absolute() or '..' in source.parts or source.is_symlink()
                    or not source.resolve().is_relative_to(workspace)
                    or volume['target'] in {'/', '/var/run/docker.sock', '/run/docker.sock'}):
                raise BootstrapFailure('workload_mount_escape')
        for filename in service.get('env_file', []):
            file = regular(filename)
            if not file.resolve().is_relative_to(workspace) or stat.S_IMODE(file.stat().st_mode) != 0o600:
                raise BootstrapFailure('drill_credentials_unprotected')
        health = service['healthcheck']
        if (set(health) != {'test', 'interval', 'timeout', 'retries'}
                or not isinstance(health['test'], list) or not health['test']
                or health['test'][0] != 'CMD'
                or health['interval'] != '10s' or health['timeout'] != '5s'
                or not isinstance(health['retries'], int) or not 1 <= health['retries'] <= 12):
            raise BootstrapFailure('bounded_health_check_required')
    if memory > limits['memory_bytes'] or cpus > limits['vcpus']:
        raise BootstrapFailure('aggregate_workload_limits_exceeded')
    return {'state': 'passed', 'services': sorted(document['services'])}


class GuestPhases:
    """Guest actions for a reviewed backend; no controller/production execution.

    Backend provision must attest a blank guest and stage source, encrypted inputs,
    exact image exports, per-phase programs and drill-only credentials read-only.
    Each phase program is source-bound, executes entirely in the guest, and must
    emit sanitized proof. Provider destruction remains independent of this class.
    """

    def __init__(self, plan, inputs, workspace, programs, execute):
        self.plan, self.inputs = plan, Path(inputs)
        self.workspace, self.programs = Path(workspace), programs
        self.execute = execute
        self.completed = []

    def run(self, phase):
        if (phase not in PHASES or len(self.completed) >= len(PHASES)
                or PHASES[len(self.completed)] != phase):
            raise BootstrapFailure('bootstrap_phase_order_invalid')
        verify_staged(self.plan, self.inputs)
        program = self.programs[phase]
        path = regular(program['path'])
        if digest(path) != program['sha256']:
            raise BootstrapFailure('guest_program_revision_mismatch')
        # The backend executes this in its guest, never as a local subprocess.
        result = self.execute(phase, path, min(600, self.plan['maximum_lifetime_seconds']))
        if (set(result) != {'state', 'phase', 'manifest_sha256', 'source_revision', 'proofs'}
                or result['state'] != 'passed' or result['phase'] != phase
                or result['manifest_sha256'] != self.plan['manifest_sha256']
                or result['source_revision'] != self.plan['source_revision']):
            raise BootstrapFailure('guest_phase_evidence_invalid')
        proofs = result['proofs']
        required = {
            'bootstrap': {'blank_guest', 'offline_tools', 'no_production_access'},
            'dependencies': {'all_repositories', 'all_exact_image_exports'},
            'secrets': {'drill_only_identity', 'no_operator_credentials'},
            'recovery': {'guest_local_storage', 'no_nas_mounts', 'no_active_jobs'},
            'restore': set(self.plan['required_sources']),
            'workloads': {'all_required_services', 'bounded_healthy_services'},
            'validation': {'application_queries', 'restored_integrity', 'group_binding'},
        }[phase]
        if set(proofs) != required or any(value is not True for value in proofs.values()):
            raise BootstrapFailure('guest_phase_proof_incomplete')
        self.completed.append(phase)
        return result


def extract_archive(archive, destination, maximum_bytes):
    """Materialize only regular files/directories under private guest storage."""
    destination = Path(destination)
    destination.mkdir(mode=0o700)
    with tarfile.open(regular(archive), 'r:gz') as source:
        members = source.getmembers()
        if (not members or len(members) > 1000000
                or sum(m.size for m in members) > maximum_bytes
                or any(not (m.isdir() or m.isfile()) or Path(m.name).is_absolute()
                       or '..' in Path(m.name).parts for m in members)):
            raise BootstrapFailure('guest_archive_boundary_invalid')
        source.extractall(destination, filter='data')
        for member in members:
            if member.isfile():
                with source.extractfile(member) as expected, (destination / member.name).open('rb') as actual:
                    if hashlib.file_digest(expected, 'sha256').digest() != hashlib.file_digest(actual, 'sha256').digest():
                        raise BootstrapFailure('guest_archive_integrity_failed')
    return {'state': 'passed', 'members': len(members)}


class GuestRuntime:
    """Concrete offline restoration and workload actions inside a blank VM.

    The VM launcher supplies the attestation and sealed inputs. No controller may
    invoke these actions until the provider has been separately approved. Host
    bootstrap/deployment playbooks and network credential discovery are never used.
    """

    def __init__(self, plan, inputs, workspace, attestation):
        self.plan, self.inputs, self.workspace = plan, Path(inputs), Path(workspace)
        self.attestation = attestation
        self.engines = []
        self.project = 'rv-' + uuid.uuid4().hex

    def boundary(self):
        if (os.geteuid() != 10001 or self.attestation.get('execution_authorized') is not True
                or self.attestation.get('source_revision') != self.plan['source_revision']
                or self.attestation.get('manifest_sha256') != self.plan['manifest_sha256']
                or self.attestation.get('production_access') is not False
                or self.attestation.get('resource_reference') != self.plan['resource_reference']
                or not re.fullmatch(r'temporary://recovery-[0-9a-f]{32}', self.attestation.get('resource_reference', ''))):
            raise BootstrapFailure('approved_guest_required')
        expiry = instant(self.attestation['expires_at'])
        remaining = (expiry - dt.datetime.now(dt.timezone.utc)).total_seconds()
        if not 0 < remaining <= 7200:
            raise BootstrapFailure('guest_lease_expired')
        if self.workspace.parent != Path('/var/lib/recovery-drill') or not re.fullmatch(r'recovery-[0-9a-f]{32}', self.workspace.name):
            raise BootstrapFailure('guest_workspace_invalid')
        if self.workspace.name != self.attestation['resource_reference'].removeprefix('temporary://'):
            raise BootstrapFailure('guest_resource_ownership_mismatch')
        virtual = subprocess.run(['systemd-detect-virt', '--vm'], capture_output=True,
                                 text=True, timeout=5, check=False)
        if virtual.returncode or virtual.stdout.strip() not in {'qemu', 'kvm'}:
            raise BootstrapFailure('disposable_vm_required')
        mounts = Path('/proc/self/mountinfo').read_text()
        if any(' - ' + kind + ' ' in mounts for kind in ('nfs', 'nfs4', 'cifs', '9p', 'virtiofs')):
            raise BootstrapFailure('shared_or_production_mount_forbidden')
        routes = subprocess.run(['ip', '-json', 'route', 'show', 'table', 'all'],
                                capture_output=True, text=True, timeout=5, check=True)
        if any(r.get('dst') == 'default' for r in json.loads(routes.stdout)):
            raise BootstrapFailure('guest_egress_forbidden')

    def command(self, argv, timeout=120):
        self.boundary()
        remaining = int((instant(self.attestation['expires_at']) - dt.datetime.now(dt.timezone.utc)).total_seconds())
        if remaining <= 0:
            raise BootstrapFailure('guest_lease_expired')
        result = subprocess.run(argv, cwd=self.workspace, env={
            'PATH': os.defpath, 'LANG': 'C.UTF-8', 'HOME': str(self.workspace),
            'TMPDIR': str(self.workspace)}, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=min(timeout, remaining), check=False)
        if result.returncode or len(result.stdout) > 1048576:
            raise BootstrapFailure('guest_command_failed')
        return result.stdout.decode().strip()

    def bootstrap(self):
        self.boundary()
        if self.workspace.exists():
            raise BootstrapFailure('blank_guest_workspace_required')
        self.workspace.mkdir(mode=0o700)
        verify_staged(self.plan, self.inputs)
        self.command(['docker', 'version', '--format', '{{.Server.Version}}'])
        self.command(['age', '--version'])

    def dependencies(self, exports):
        self.boundary()
        transfer = json.loads(regular(self.inputs / 'transport.json', 1048576).read_text())
        if exports != transfer.get('images'):
            raise BootstrapFailure('image_transport_binding_invalid')
        if set(exports) != set(self.plan['images']):
            raise BootstrapFailure('complete_image_inventory_required')
        for reference, entry in exports.items():
            if (set(entry) != {'archive', 'archive_sha256', 'ciphertext_sha256', 'image_id'}
                    or Path(entry['archive']).name != entry['archive']
                    or not re.fullmatch(r'sha256:[0-9a-f]{64}', entry['image_id'])):
                raise BootstrapFailure('image_export_identity_invalid')
            archive = regular(self.inputs / entry['archive'])
            if digest(archive) != entry['ciphertext_sha256']:
                raise BootstrapFailure('image_export_integrity_failed')
        # Retrieve/validate encrypted dependencies first; decryption waits until
        # the subsequent secrets phase has supplied the authorized recovery key.
        self.exports = exports

    def secrets(self, identity, files):
        self.boundary()
        identity = regular(identity)
        if (identity.stat().st_uid != os.geteuid()
                or stat.S_IMODE(identity.stat().st_mode) != 0o600):
            raise BootstrapFailure('guest_key_unprotected')
        self.identity = identity
        transfer = json.loads((self.inputs / 'transport.json').read_text())
        recipient = self.command(['age-keygen', '-y', str(identity)])
        if recipient != transfer['guest_recipient'] or recipient == self.plan['encryption_recipient']:
            raise BootstrapFailure('private_recovery_identity_transfer_forbidden')
        if not files:
            raise BootstrapFailure('drill_credentials_required')
        for entry in files:
            file = regular(entry['file'])
            if (entry['scope'] != 'drill-only' or file.stat().st_uid != os.geteuid()
                    or stat.S_IMODE(file.stat().st_mode) != 0o600
                    or not file.resolve().is_relative_to(self.workspace)
                    or digest(file) != entry['sha256']):
                raise BootstrapFailure('drill_credentials_unprotected')

    def recovery(self):
        self.boundary()
        # Source snapshots and phase programs arrive read-only in the guest.
        # All mutable paths are new VM-local storage, never normal host paths.
        for name in ('application-state', 'queries'):
            (self.workspace / name).mkdir(mode=0o700, exist_ok=False)
        self.loaded_images = {}
        for reference, entry in self.exports.items():
            output = self.workspace / (entry['image_id'].removeprefix('sha256:') + '.tar')
            try:
                self.command(['age', '--decrypt', '--identity', str(self.identity), '--output', str(output),
                              str(self.inputs / entry['archive'])], 600)
                output.chmod(0o600)
                if digest(output) != entry['archive_sha256']:
                    raise BootstrapFailure('image_export_plaintext_integrity_failed')
                self.command(['docker', 'load', '--input', str(output)], 600)
                actual = self.command(['docker', 'image', 'inspect', entry['image_id'], '--format', '{{.Id}}'])
                if actual != entry['image_id']:
                    raise BootstrapFailure('image_export_registry_binding_failed')
                self.loaded_images[reference] = entry['image_id']
            finally:
                output.unlink(missing_ok=True)
        return {'guest_local_storage': True, 'no_nas_mounts': True, 'no_active_jobs': True}

    def restore(self):
        """Restore every encrypted inventory member without touching its source."""
        verify_staged(self.plan, self.inputs)
        manifest = json.loads((self.inputs / 'manifest.json').read_text())
        transfer = json.loads((self.inputs / 'transport.json').read_text())
        decrypted = {}
        for entry in self.plan['artifacts']:
            output = self.workspace / entry['source']
            self.command(['age', '--decrypt', '--identity', str(self.identity),
                          '--output', str(output), str(self.inputs / transfer['artifacts'][entry['source']]['artifact'])], 600)
            output.chmod(0o600)
            if digest(output) != transfer['artifacts'][entry['source']]['plaintext_sha256']:
                raise BootstrapFailure('drill_transport_plaintext_mismatch')
            decrypted[entry['source']] = output
        pg = self.workspace / 'postgres'
        socket = self.workspace / 'socket'
        socket.mkdir(mode=0o700)
        user = 'rv_' + uuid.uuid4().hex
        self.postgres_user = user
        self.command(['initdb', '-D', str(pg), '-U', user, '--auth=trust', '--no-locale', '--encoding=UTF8'])
        # Register ownership before starting so cleanup also covers partial starts.
        self.engines.append(('postgres', pg))
        self.command(['pg_ctl', '-D', str(pg), '-l', str(self.workspace / 'postgres.log'),
                      '-o', f"-k {socket} -p 55479 -c listen_addresses='' -c unix_socket_permissions=0700",
                      '-w', '-t', '20', 'start'])
        connection = ['-h', str(socket), '-p', '55479', '-U', user]
        self.command(['psql', '-X', *connection, '-d', 'template1', '-v', 'ON_ERROR_STOP=1',
                      '-f', str(decrypted['postgres-globals'])])
        proofs = {'postgres-globals': True}
        for entry in manifest['artifacts']:
            source, format_name = entry['source'], entry['format']
            if format_name == 'postgres-custom-age':
                if source == 'postgres':
                    self.command(['dropdb', *connection, 'postgres'])
                self.command(['pg_restore', *connection, '--create', '--exit-on-error', '--no-tablespaces',
                              '--dbname=template1', str(decrypted[source])], 600)
                self.command(['pg_amcheck', *connection, '--database', source, '--install-missing'], 600)
                owner = self.command(['psql', '-X', *connection, '-d', source, '-At', '-c',
                                      'SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=current_database();'])
                if owner != entry['recovery_prerequisites']['database_settings']['owner']:
                    raise BootstrapFailure('restored_database_owner_mismatch')
                proofs[source] = True
            elif format_name == 'tar-gzip-age':
                extract_archive(decrypted[source], self.workspace / ('files-' + source), 100 * 1024**3)
                proofs[source] = True
            elif format_name == 'redis-rdb-age':
                self.command(['redis-check-rdb', str(decrypted[source])], 600)
                socket_path = self.workspace / (source + '.socket')
                self.engines.append(('redis', socket_path))
                self.command(['redis-server', '--daemonize', 'yes', '--port', '0',
                              '--unixsocket', str(socket_path), '--unixsocketperm', '700',
                              '--dir', str(self.workspace), '--dbfilename', decrypted[source].name,
                              '--pidfile', str(self.workspace / (source + '.pid')),
                              '--logfile', str(self.workspace / (source + '.log')),
                              '--maxmemory', '512mb', '--maxmemory-policy', 'noeviction'])
                if self.command(['redis-cli', '-s', str(socket_path), 'PING']) != 'PONG':
                    raise BootstrapFailure('restored_redis_unhealthy')
                int(self.command(['redis-cli', '-s', str(socket_path), 'DBSIZE']))
                proofs[source] = True
            elif format_name == 'mongo-archive-gzip-age':
                data = self.workspace / ('mongo-' + source)
                data.mkdir(mode=0o700)
                self.engines.append(('mongo', data))
                self.command(['mongod', '--fork', '--dbpath', str(data), '--bind_ip', '127.0.0.1',
                              '--port', '27017', '--logpath', str(self.workspace / 'mongo.log'),
                              '--pidfilepath', str(self.workspace / 'mongo.pid')])
                self.command(['mongorestore', '--host', '127.0.0.1', '--port', '27017',
                              '--archive=' + str(decrypted[source]), '--gzip', '--drop'], 600)
                self.command(['mongosh', '--host', '127.0.0.1', '--port', '27017', '--quiet',
                              '--eval', 'if(db.adminCommand({ping:1}).ok!==1)quit(1); '
                              'for(const d of db.adminCommand({listDatabases:1}).databases) '
                              'for(const c of db.getSiblingDB(d.name).getCollectionNames()) '
                              'if(db.getSiblingDB(d.name).runCommand({validate:c}).valid!==true)quit(1);'])
                proofs[source] = True
            elif source != 'postgres-globals':
                raise BootstrapFailure('guest_artifact_format_unsupported')
        if not set(self.plan['required_sources']) <= set(proofs):
            raise BootstrapFailure('guest_restore_incomplete')
        return proofs

    def workloads(self, document, limits):
        if set(document.get('services', {})) != set(self.plan['required_services']):
            raise BootstrapFailure('complete_application_inventory_required')
        verify_workloads(document, self.workspace, self.plan['images'], limits)
        # Docker save/load retains config identities but need not retain registry
        # RepoDigests. Bind offline startup to the verified archive config ID.
        document = json.loads(json.dumps(document))
        for service in document['services'].values():
            reference = service['image'] if service['image'].startswith('image-archive://') else 'oci://' + service['image']
            service['image'] = self.loaded_images[reference]
        path = self.workspace / 'workloads.json'
        path.write_text(json.dumps(document))
        path.chmod(0o600)
        self.workload_file = path
        self.command(['docker', 'compose', '-p', self.project, '-f', str(path),
                      'up', '--detach', '--wait', '--wait-timeout', '120', '--pull', 'never'], 150)
        return {'all_required_services': True, 'bounded_healthy_services': True}

    def validation(self):
        output = self.command(['docker', 'compose', '-p', self.project,
                               '-f', str(self.workload_file), 'ps', '--format', 'json'])
        # Compose releases use either an array or one JSON object per service.
        # This is the upstream command wire format, not a legacy config loader.
        status = json.loads(output) if output.startswith('[') else [json.loads(line) for line in output.splitlines()]
        if (not isinstance(status, list)
                or {s['Service'] for s in status} != set(self.plan['required_services'])
                or any(s.get('Health') != 'healthy' or s.get('State') != 'running' for s in status)):
            raise BootstrapFailure('application_health_incomplete')
        # Every database must expose restored relations and resolved ownership.
        for entry in self.plan['artifacts']:
            if entry['format'] == 'postgres-custom-age':
                result = self.command(['psql', '-X', '-h', str(self.workspace / 'socket'),
                                       '-p', '55479', '-U', self.postgres_user, '-d', entry['source'],
                                       '-At', '-c', 'SELECT count(*)=0 FROM pg_class c '
                                       'LEFT JOIN pg_roles r ON r.oid=c.relowner WHERE r.oid IS NULL;'])
                if result != 't':
                    raise BootstrapFailure('application_query_failed')
                for query in self.plan['representative_queries'].get(entry['source'], []):
                    if self.command(['psql', '-X', '-h', str(self.workspace / 'socket'), '-p', '55479',
                                     '-U', self.postgres_user, '-d', entry['source'], '-At',
                                     '-v', 'ON_ERROR_STOP=1', '-c', query]) != 't':
                        raise BootstrapFailure('representative_application_query_failed')
        verify_staged(self.plan, self.inputs)
        return {'application_queries': True, 'restored_integrity': True, 'group_binding': True}

    def cleanup(self):
        """Local cleanup is evidence; provider expiry/destruction is separate."""
        self.boundary()
        failures = []
        if hasattr(self, 'workload_file'):
            try:
                self.command(['docker', 'compose', '-p', self.project, '-f', str(self.workload_file),
                              'down', '--volumes', '--remove-orphans', '--timeout', '5'], 10)
            except (BootstrapFailure, OSError, subprocess.SubprocessError):
                failures.append('workload_cleanup_failed')
        for engine, path in self.engines:
            if engine == 'postgres' and (path / 'postmaster.pid').exists():
                try:
                    self.command(['pg_ctl', '-D', str(path), '-m', 'immediate', '-w', '-t', '5', 'stop'], 8)
                except (BootstrapFailure, OSError, subprocess.SubprocessError):
                    failures.append('database_cleanup_failed')
            elif engine == 'redis' and path.exists():
                try:
                    self.command(['redis-cli', '-s', str(path), 'SHUTDOWN', 'NOSAVE'], 8)
                except (BootstrapFailure, OSError, subprocess.SubprocessError):
                    failures.append('redis_cleanup_failed')
            elif engine == 'redis' and path.with_suffix('.pid').exists():
                failures.append('redis_cleanup_unobserved')
            elif engine == 'mongo':
                try:
                    self.command(['mongod', '--shutdown', '--dbpath', str(path)], 8)
                except (BootstrapFailure, OSError, subprocess.SubprocessError):
                    failures.append('mongo_cleanup_failed')
        # Failed or expired guest cleanup must be reconciled by backend destruction.
        # Never delete state before engines have stopped successfully.
        if failures:
            raise BootstrapFailure('guest_cleanup_failed')
        import shutil
        if self.workspace.exists():
            shutil.rmtree(self.workspace)
        return {'state': 'passed', 'reason': 'guest_resources_removed'}
