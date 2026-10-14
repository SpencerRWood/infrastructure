#!/usr/bin/env python3
"""Retrieve/decrypt an image archive in memory and prove every Docker layer."""
import argparse
import hashlib
import gzip
import io
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tarfile

def digest(path):
    # Standalone attended retrieval runs need no consumer checkout/import path.
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def layer_digest(stream, maximum=32 * 1024**3):
    checksum, count = hashlib.sha256(), 0
    for block in iter(lambda: stream.read(1048576), b''):
        count += len(block)
        if count > maximum:
            raise ValueError('image_layer_size_limit')
        checksum.update(block)
    return checksum.hexdigest()


class HashedReader(io.RawIOBase):
    def __init__(self, stream):
        self.stream, self.hash = stream, hashlib.sha256()
        self.size, self.tail = 0, b''

    def readable(self):
        return True

    def readinto(self, buffer):
        data = self.stream.read(len(buffer))
        self.hash.update(data)
        self.size += len(data)
        self.tail = (self.tail + data)[-1024:]
        buffer[:len(data)] = data
        return len(data)


def inspect_archive(stream, metadata):
    reader = HashedReader(stream)
    buffered = io.BufferedReader(reader, buffer_size=1048576)
    hashes, layer_hashes, documents = {}, {}, {}
    document_bytes = 0
    with tarfile.open(fileobj=buffered, mode='r|') as archive:
        for member in archive:
            if (Path(member.name).is_absolute() or '..' in Path(member.name).parts
                    or not (member.isfile() or member.isdir()) or member.name in hashes):
                raise ValueError('image_archive_member_invalid')
            if member.isfile():
                with archive.extractfile(member) as file:
                    if member.size <= 1048576:
                        data = file.read()
                        hashes[member.name] = hashlib.sha256(data).hexdigest()
                        # Current Docker save archives place config JSON under
                        # content-addressed blobs without a .json suffix.
                        if data.lstrip().startswith((b'{', b'[')):
                            json.loads(data)
                            document_bytes += len(data)
                            if document_bytes > 16 * 1048576:
                                raise ValueError('image_configuration_limit')
                            documents[member.name] = data
                        if data.startswith(b'\x1f\x8b'):
                            with gzip.GzipFile(fileobj=io.BytesIO(data)) as decoded:
                                layer_hashes[member.name] = layer_digest(decoded)
                        else:
                            layer_hashes[member.name] = hashes[member.name]
                    else:
                        if member.name.endswith('.json'):
                            raise ValueError('image_configuration_limit')
                        raw = HashedReader(file)
                        buffered_layer = io.BufferedReader(raw, buffer_size=1048576)
                        prefix = buffered_layer.peek(4)[:4]
                        if prefix == b'\x28\xb5\x2f\xfd':
                            raise ValueError('image_layer_compression_unsupported')
                        if prefix[:2] == b'\x1f\x8b':
                            with gzip.GzipFile(fileobj=buffered_layer) as decoded:
                                layer_hashes[member.name] = layer_digest(decoded)
                            while buffered_layer.read(1048576):
                                pass
                        else:
                            layer_hashes[member.name] = layer_digest(buffered_layer)
                        hashes[member.name] = raw.hash.hexdigest()
                    if member.name.startswith('blobs/sha256/') and member.name.rsplit('/', 1)[-1] != hashes[member.name]:
                        raise ValueError('image_blob_address_mismatch')
    while buffered.read(1048576):
        pass
    if reader.size % 512 or reader.tail != b'\0' * 1024:
        raise ValueError('image_archive_truncated')
    if reader.hash.hexdigest() != metadata['archive_sha256']:
        raise ValueError('image_archive_plaintext_checksum_mismatch')
    manifest = json.loads(documents['manifest.json'])
    if not isinstance(manifest, list) or len(manifest) != 1 or not isinstance(manifest[0], dict):
        raise ValueError('single_image_archive_required')
    entry = manifest[0]
    if (not isinstance(entry.get('Config'), str)
            or entry['Config'] not in documents
            or not isinstance(entry.get('Layers'), list)
            or any(not isinstance(name, str) or name not in hashes for name in entry['Layers'])):
        raise ValueError('image_manifest_inventory_invalid')
    image_hash = hashes[entry['Config']]
    if 'sha256:' + image_hash != metadata['image_id']:
        raise ValueError('image_configuration_identity_mismatch')
    config = json.loads(documents[entry['Config']])
    layers = config['rootfs']['diff_ids']
    if (not isinstance(layers, list) or len(layers) != len(entry['Layers']) or not layers
            or any(not isinstance(value, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', value) for value in layers)):
        raise ValueError('image_layer_inventory_invalid')
    for name, expected in zip(entry['Layers'], layers):
        if 'sha256:' + layer_hashes[name] != expected:
            raise ValueError('image_layer_integrity_failed')
    return {'state': 'passed', 'image_id': metadata['image_id'],
            'ciphertext_sha256': metadata['ciphertext_sha256'],
            'archive_sha256': metadata['archive_sha256'],
            'docker_manifest_sha256': hashes['manifest.json'],
            'configuration_sha256': image_hash,
            'layers': [{'path': name, 'blob_sha256': hashes[name],
                        'diff_id': expected, 'verified_diff_id': 'sha256:' + layer_hashes[name]}
                       for name, expected in zip(entry['Layers'], layers)],
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
            or metadata['artifact'] in ('', '.', '..')
            or any(not isinstance(metadata[key], str) or not re.fullmatch(r'[0-9a-f]{64}', metadata[key])
                   for key in ['archive_sha256', 'ciphertext_sha256'])
            or isinstance(metadata['size_bytes'], bool) or not isinstance(metadata['size_bytes'], int)
            or metadata['size_bytes'] <= 0
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
        result['export_manifest_sha256'] = digest(metadata_path)
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
