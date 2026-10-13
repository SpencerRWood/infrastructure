#!/usr/bin/env python3
"""Plan, or explicitly apply, encrypted exports of exact local recovery images."""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import time
import uuid

DESTINATION = Path('/mnt/wood-server-nas/backup_server/swood-server/infrastructure-dev/image-artifacts')
NFS = '192.168.1.10:/volume1/recovery_backups/infrastructure-dev'
RECIPIENT = 'age1544rwqert2c0u5wks57lcgfw6saymcfmc7slhdr58js69w3m7d4st3la33'
SELECTIONS = {
    'homelab-caddy': ('container', 'caddy', 'SpencerRWood/homelab', 'compose/platform/caddy/Dockerfile'),
    'homelab-code-server': ('image', 'code-server-codex:latest', 'SpencerRWood/homelab', 'compose/platform/code-server/Dockerfile'),
    'infrastructure-dagster': ('container', 'infrastructure-dev-dagster-dagster-webserver-1', 'SpencerRWood/infrastructure', 'compose/dagster/Dockerfile'),
    'infrastructure-overleaf': ('container', 'infrastructure-dev-overleaf-overleaf-1', 'SpencerRWood/infrastructure', 'compose/overleaf/Dockerfile'),
}


def command(argv):
    result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            check=True, timeout=30, text=True)
    if len(result.stdout) > 65536:
        raise ValueError('image_inspection_limit')
    return result.stdout.strip()


def fingerprint(document):
    return hashlib.sha256(json.dumps(document, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def prepare():
    images = []
    for name, (kind, source, repository, build_source) in SELECTIONS.items():
        image_id = command(['docker', kind, 'inspect', source, '--format', '{{.Image}}' if kind == 'container' else '{{.Id}}'])
        if not re.fullmatch(r'sha256:[0-9a-f]{64}', image_id):
            raise ValueError('exact_image_identity_required')
        metadata = json.loads(command(['docker', 'image', 'inspect', image_id]))[0]
        images.append({'name': name, 'image_id': image_id,
                       'image_size_bytes': metadata['Size'],
                       'architecture': metadata['Architecture'], 'os': metadata['Os'],
                       'source_repository': repository, 'build_source': build_source,
                       'source_revision': (metadata.get('Config', {}).get('Labels') or {}).get('org.opencontainers.image.revision'),
                       'destination': str(DESTINATION / name / image_id.removeprefix('sha256:'))})
    return {'schema_version': '1', 'recipient': RECIPIENT, 'nfs_source': NFS,
            'images': images, 'maximum_seconds_per_image': 900,
            'maximum_archive_bytes_per_image': 32 * 1024**3,
            'registry_writes': False, 'private_identity_required': False}


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1048576), b''):
            result.update(block)
    return result.hexdigest()


def encrypt_stream(source_command, output, recipient, maximum_seconds, maximum_bytes):
    """Hash and encrypt a fixed caller's stream without a plaintext file."""
    start, archive_hash, count = time.monotonic(), hashlib.sha256(), 0
    save = subprocess.Popen(source_command, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, start_new_session=True)
    age = None
    try:
        age = subprocess.Popen(['age', '--recipient', recipient, '--output', str(output)],
                               stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, start_new_session=True)
        selector = selectors.DefaultSelector()
        selector.register(save.stdout, selectors.EVENT_READ)
        selector.register(age.stdin, selectors.EVENT_WRITE)
        pending, eof = b'', False
        while not eof or pending:
            if time.monotonic() - start > maximum_seconds or age.poll() is not None:
                raise ValueError('image_export_interrupted_or_expired')
            for key, _ in selector.select(timeout=1):
                if key.fileobj is save.stdout and not eof and len(pending) < 1048576:
                    block = os.read(save.stdout.fileno(), 65536)
                    if block:
                        count += len(block)
                        if count > maximum_bytes:
                            raise ValueError('image_export_size_limit')
                        archive_hash.update(block); pending += block
                    else:
                        eof = True; selector.unregister(save.stdout)
                elif key.fileobj is age.stdin and pending:
                    written = os.write(age.stdin.fileno(), pending[:4096])
                    pending = pending[written:]
        age.stdin.close()
        remaining = max(1, maximum_seconds - (time.monotonic() - start))
        if save.wait(timeout=remaining) or age.wait(timeout=remaining):
            raise ValueError('image_export_failed')
        if not count:
            raise ValueError('image_export_empty')
        return archive_hash.hexdigest()
    finally:
        for process in (save, age):
            if process is not None and process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)


def apply(plan, approved_hash):
    if fingerprint(plan) != approved_hash or prepare() != plan:
        raise ValueError('approved_export_plan_stale')
    if DESTINATION.is_symlink() or not DESTINATION.is_dir():
        raise ValueError('approved_storage_not_provisioned')
    filesystem = json.loads(command(['findmnt', '--json', '--target', str(DESTINATION),
                                     '--output', 'SOURCE,FSTYPE']))['filesystems']
    if filesystem != [{'source': NFS, 'fstype': 'nfs'}]:
        raise ValueError('independent_export_mount_mismatch')
    os.umask(0o027)
    results = []
    for image in plan['images']:
        directory = Path(image['destination'])
        if directory.exists() or directory.is_symlink():
            raise ValueError('immutable_export_already_exists')
        directory.mkdir(mode=0o750, parents=True)
        temporary = directory / ('.partial-' + uuid.uuid4().hex + '.age')
        completed = directory / 'image.tar.age'
        try:
            archive_hash = encrypt_stream(['docker', 'save', image['image_id']], temporary, RECIPIENT,
                                          plan['maximum_seconds_per_image'],
                                          plan['maximum_archive_bytes_per_image'])
            temporary.chmod(0o640)
            ciphertext_hash = digest(temporary)
            with temporary.open('rb') as stream:
                if stream.read(22) != b'age-encryption.org/v1\n':
                    raise ValueError('image_export_encryption_invalid')
            os.replace(temporary, completed)
            record = {'schema_version': '1', 'format': 'docker-save-age',
                      'image_id': image['image_id'], 'artifact': completed.name,
                      'archive_sha256': archive_hash, 'ciphertext_sha256': ciphertext_hash,
                      'size_bytes': completed.stat().st_size, 'recipient': RECIPIENT,
                      'source_repository': image['source_repository'], 'build_source': image['build_source'],
                      'source_revision': image['source_revision'],
                      'completed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                      'independent_storage_source': NFS, 'retrieval_verified': False}
            metadata = directory / 'manifest.json'
            metadata.write_text(json.dumps(record, sort_keys=True) + '\n'); metadata.chmod(0o640)
            results.append({'name': image['name'], 'image_id': image['image_id'],
                            'manifest': str(metadata), 'ciphertext_sha256': ciphertext_hash,
                            'retrieval_verified': False})
        finally:
            temporary.unlink(missing_ok=True)
    return {'state': 'exported_retrieval_unverified', 'images': results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--approved-plan-sha256')
    args = parser.parse_args()
    try:
        plan = prepare()
        result = apply(plan, args.approved_plan_sha256) if args.apply else {'state': 'prepared', 'plan': plan, 'plan_sha256': fingerprint(plan)}
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print(json.dumps({'state': 'failed', 'reason': 'recovery_image_export_unverified'}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
