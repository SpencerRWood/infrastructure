#!/usr/bin/env python3
"""Re-encrypt validated backup copies for a guest without transferring its DR key."""
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess

from recovery_manifest import digest, load_policy, validate

spec = importlib.util.spec_from_file_location('image_stream', Path(__file__).with_name('export-recovery-images.py'))
STREAM = importlib.util.module_from_spec(spec); spec.loader.exec_module(STREAM)
TRANSPORT_ROOT = Path('/var/tmp/recovery-drill/transports')


def stage(root, destination, guest_recipient, resource_reference, approved_plan):
    """Called only by an approved provider after its guest generates its own key."""
    root, destination = Path(root), Path(destination)
    if (not re.fullmatch(r'age1[0-9a-z]{58}', guest_recipient)
            or not re.fullmatch(r'temporary://recovery-[0-9a-f]{32}', resource_reference)
            or destination.parent != TRANSPORT_ROOT
            or destination.name != resource_reference.removeprefix('temporary://')
            or destination.exists() or destination.is_symlink()):
        raise ValueError('owned_guest_transport_required')
    policy = load_policy(root / 'recovery/backup-policy.yml')
    manifest, group, group_hash = validate(policy['pointer'], policy)
    if (approved_plan['execution_authorized'] is not True
            or approved_plan['manifest_sha256'] != group_hash
            or approved_plan['guest_recipient'] != guest_recipient
            or approved_plan['resource_reference'] != resource_reference
            or guest_recipient == policy['encryption_recipient']):
        raise ValueError('approved_transport_plan_required')
    revision = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True, timeout=10).strip()
    dirty = subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True, timeout=10)
    if revision != approved_plan['source_revision'] or dirty:
        raise ValueError('clean_approved_transport_source_required')
    # The controller explicitly selects the existing protected host identity.
    # Consumer restore policy paths refer to its container namespace and are
    # never consulted as a compatibility fallback for this distinct interface.
    identity = Path(approved_plan['controller_identity_file'])
    if (identity.is_symlink() or not identity.is_file() or identity.stat().st_uid != os.geteuid()
            or stat.S_IMODE(identity.stat().st_mode) != 0o600):
        raise ValueError('protected_controller_identity_required')
    destination.mkdir(mode=0o700)
    result = {'schema_version': '1', 'source_revision': approved_plan['source_revision'],
              'manifest_sha256': group_hash, 'guest_recipient': guest_recipient,
              'resource_reference': resource_reference, 'artifacts': {}, 'images': {}}
    try:
        for entry in manifest['artifacts']:
            source = group / entry['artifact']
            if digest(source) != entry['sha256']:
                raise ValueError('transport_source_changed')
            output = destination / entry['artifact']
            plaintext_hash = STREAM.encrypt_stream(
                ['age', '--decrypt', '--identity', str(identity), str(source)],
                output, guest_recipient, 900, 32 * 1024**3)
            output.chmod(0o600)
            result['artifacts'][entry['source']] = {
                'artifact': output.name, 'source_ciphertext_sha256': entry['sha256'],
                'plaintext_sha256': plaintext_hash, 'ciphertext_sha256': digest(output),
                'size_bytes': output.stat().st_size}
        for index, (reference, selected) in enumerate(approved_plan['image_exports'].items()):
            if selected['kind'] == 'registry':
                if (not reference.startswith('oci://')
                        or subprocess.check_output(['docker', 'image', 'inspect', reference.removeprefix('oci://'),
                            '--format', '{{.Id}}'], text=True, timeout=10).strip() != selected['image_id']):
                    raise ValueError('transport_registry_image_changed')
                command = ['docker', 'save', selected['image_id']]
            elif selected['kind'] == 'encrypted-export':
                path = Path(selected['metadata'])
                if path.is_symlink() or digest(path) != selected['metadata_sha256']:
                    raise ValueError('transport_image_manifest_changed')
                metadata = json.loads(path.read_text())
                artifact = path.parent / metadata['artifact']
                if (artifact.is_symlink() or not artifact.resolve().is_relative_to(path.parent.resolve())
                        or metadata['image_id'] != selected['image_id']
                        or digest(artifact) != metadata['ciphertext_sha256']):
                    raise ValueError('transport_image_ciphertext_changed')
                command = ['age', '--decrypt', '--identity', str(identity), str(artifact)]
            else:
                raise ValueError('transport_image_source_invalid')
            output = destination / ('image-' + str(index) + '.tar.age')
            checksum = STREAM.encrypt_stream(command, output, guest_recipient, 900, 32 * 1024**3)
            output.chmod(0o600)
            result['images'][reference] = {'archive': output.name, 'archive_sha256': checksum,
                'ciphertext_sha256': digest(output), 'image_id': selected['image_id']}
        (destination / 'manifest.json').write_bytes((group / 'manifest.json').read_bytes())
        (destination / 'transport.json').write_text(json.dumps(result, sort_keys=True) + '\n')
        if digest(destination / 'manifest.json') != group_hash:
            raise ValueError('transport_manifest_changed')
        return {'state': 'staged', 'resource_reference': resource_reference,
                'manifest_sha256': group_hash, 'private_identity_transferred': False}
    except BaseException:
        # This is exclusively a newly created owned transport directory.
        import shutil
        shutil.rmtree(destination)
        raise
