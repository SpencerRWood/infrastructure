#!/usr/bin/env python3
"""Retrieve/decrypt an image archive in memory and prove every Docker layer."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tarfile

from recovery_manifest import digest


class HashedReader(io.RawIOBase):
    def __init__(self, stream):
        self.stream, self.hash = stream, hashlib.sha256()

    def readable(self):
        return True

    def readinto(self, buffer):
        data = self.stream.read(len(buffer))
        self.hash.update(data)
        buffer[:len(data)] = data
        return len(data)


def inspect_archive(stream, metadata):
    reader = HashedReader(stream)
    buffered = io.BufferedReader(reader, buffer_size=1048576)
    hashes, documents = {}, {}
    with tarfile.open(fileobj=buffered, mode='r|') as archive:
        for member in archive:
            if (Path(member.name).is_absolute() or '..' in Path(member.name).parts
                    or not (member.isfile() or member.isdir()) or member.name in hashes):
                raise ValueError('image_archive_member_invalid')
            if member.isfile():
                with archive.extractfile(member) as file:
                    if member.name.endswith('.json'):
                        if member.size > 1048576:
                            raise ValueError('image_configuration_limit')
                        data = file.read()
                        documents[member.name] = data
                        hashes[member.name] = hashlib.sha256(data).hexdigest()
                    else:
                        hashes[member.name] = hashlib.file_digest(file, 'sha256').hexdigest()
    while buffered.read(1048576):
        pass
    if reader.hash.hexdigest() != metadata['archive_sha256']:
        raise ValueError('image_archive_plaintext_checksum_mismatch')
    manifest = json.loads(documents['manifest.json'])
    if len(manifest) != 1:
        raise ValueError('single_image_archive_required')
    entry = manifest[0]
    image_hash = hashes[entry['Config']]
    if 'sha256:' + image_hash != metadata['image_id']:
        raise ValueError('image_configuration_identity_mismatch')
    config = json.loads(documents[entry['Config']])
    layers = config['rootfs']['diff_ids']
    if len(layers) != len(entry['Layers']) or not layers:
        raise ValueError('image_layer_inventory_invalid')
    for name, expected in zip(entry['Layers'], layers):
        if 'sha256:' + hashes[name] != expected:
            raise ValueError('image_layer_integrity_failed')
    return {'state': 'passed', 'image_id': metadata['image_id'],
            'ciphertext_sha256': metadata['ciphertext_sha256'],
            'archive_sha256': metadata['archive_sha256'],
            'layer_count': len(layers), 'plaintext_persisted': False}


def verify(metadata_path, identity):
    metadata_path, identity = Path(metadata_path), Path(identity)
    if (metadata_path.is_symlink() or identity.is_symlink() or not identity.is_file()
            or stat.S_IMODE(identity.stat().st_mode) != 0o600
            or identity.stat().st_uid != os.geteuid()):
        raise ValueError('protected_retrieval_inputs_required')
    metadata = json.loads(metadata_path.read_text())
    if (metadata['schema_version'] != '1' or metadata['format'] != 'docker-save-age'
            or Path(metadata['artifact']).name != metadata['artifact']
            or not re.fullmatch(r'sha256:[0-9a-f]{64}', metadata['image_id'])):
        raise ValueError('retrieval_metadata_invalid')
    artifact = metadata_path.parent / metadata['artifact']
    if (artifact.is_symlink() or artifact.stat().st_size != metadata['size_bytes']
            or digest(artifact) != metadata['ciphertext_sha256']):
        raise ValueError('retrieval_ciphertext_checksum_mismatch')
    process = subprocess.Popen(['age', '--decrypt', '--identity', str(identity), str(artifact)],
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               start_new_session=True)
    previous = signal.getsignal(signal.SIGALRM)
    def expired(signum, frame):
        raise ValueError('image_retrieval_timeout')
    signal.signal(signal.SIGALRM, expired); signal.alarm(900)
    try:
        result = inspect_archive(process.stdout, metadata)
        if process.wait(timeout=10):
            raise ValueError('image_retrieval_decryption_failed')
        return result
    finally:
        signal.alarm(0); signal.signal(signal.SIGALRM, previous)
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL); process.wait(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--metadata', required=True)
    parser.add_argument('--identity-file', required=True)
    args = parser.parse_args()
    try:
        result = verify(args.metadata, args.identity_file)
    except (OSError, ValueError, KeyError, TypeError, tarfile.TarError, subprocess.SubprocessError):
        print(json.dumps({'state': 'failed', 'reason': 'recovery_image_retrieval_unverified'}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
