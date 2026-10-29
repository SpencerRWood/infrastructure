#!/usr/bin/env python3
"""Attended offline PostgreSQL CA creation and server-bundle issuance."""

import argparse
import contextlib
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import secrets
import shutil
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


class CAError(ValueError):
    pass


def protected_directory(path):
    path = Path(path)
    if not path.is_absolute() or path.is_symlink() or not path.is_dir():
        raise CAError("protected_directory_required")
    path = path.resolve()
    status = path.stat()
    if status.st_uid != os.geteuid() or stat.S_IMODE(status.st_mode) != 0o700:
        raise CAError("protected_directory_permissions_invalid")
    if path.is_relative_to(ROOT) or any((parent / ".git").exists() for parent in (path, *path.parents)):
        raise CAError("key_material_must_be_outside_git")
    return path


def private_file(path):
    status = path.lstat()
    if (not stat.S_ISREG(status.st_mode) or status.st_uid != os.geteuid()
            or stat.S_IMODE(status.st_mode) != 0o600 or status.st_size > 65536):
        raise CAError("private_file_permissions_invalid")


@contextlib.contextmanager
def new_directory(path):
    path = Path(path)
    if not path.is_absolute() or path.name in {"", ".", ".."}:
        raise CAError("absolute_output_directory_required")
    parent = protected_directory(path.parent)
    path = parent / path.name
    if path.exists() or path.is_symlink():
        raise CAError("output_already_exists")
    path.mkdir(mode=0o700)
    old_mask = os.umask(0o077)
    try:
        yield path
    except BaseException:
        shutil.rmtree(path)
        raise
    finally:
        os.umask(old_mask)


def command(*arguments, passphrase=None):
    """OpenSSL passphrases travel only through an inherited pipe descriptor."""
    read_fd = write_fd = None
    try:
        args = list(map(str, arguments))
        if passphrase is not None:
            if not isinstance(passphrase, bytes) or not 32 <= len(passphrase) <= 256 or any(c in passphrase for c in (b"\n", b"\r", b"\0")):
                raise CAError("passphrase_policy_invalid")
            read_fd, write_fd = os.pipe()
            os.write(write_fd, passphrase + b"\n")
            os.close(write_fd)
            write_fd = None
            args = [f"fd:{read_fd}" if value == "PASSPHRASE_FD" else value for value in args]
        result = subprocess.run(
            ["openssl", *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, timeout=20,
            env={"PATH": os.environ.get("PATH", os.defpath), "LANG": "C.UTF-8"},
            pass_fds=() if read_fd is None else (read_fd,), check=False,
        )
        if result.returncode or len(result.stdout) > 65536:
            raise CAError("certificate_operation_failed")
        return result.stdout
    finally:
        for descriptor in (read_fd, write_fd):
            if descriptor is not None:
                os.close(descriptor)


def public_fingerprint(certificate):
    return hashlib.sha256(command("x509", "-in", certificate, "-outform", "DER")).hexdigest()


def initialize(directory, passphrase):
    with new_directory(directory) as authority:
        key, cert = authority / "ca.key.enc", authority / "ca.crt"
        command("genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-384",
                "-aes-256-cbc", "-pass", "PASSPHRASE_FD", "-out", key, passphrase=passphrase)
        command("req", "-new", "-x509", "-sha384", "-days", "3650",
                "-key", key, "-passin", "PASSPHRASE_FD", "-out", cert,
                "-set_serial", "0x" + secrets.token_hex(16),
                "-subj", "/CN=Wood Infrastructure PostgreSQL CA",
                "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
                "-addext", "keyUsage=critical,keyCertSign,cRLSign",
                "-addext", "subjectKeyIdentifier=hash",
                "-addext", "authorityKeyIdentifier=keyid:always", passphrase=passphrase)
        private_file(key)
        if not key.read_bytes().startswith(b"-----BEGIN " + b"ENCRYPTED PRIVATE KEY-----"):
            raise CAError("encrypted_ca_key_required")
        command("verify", "-x509_strict", "-auth_level", "2", "-CAfile", cert, cert)
        return {"state": "authority_prepared", "ca_sha256": public_fingerprint(cert)}


def issue(authority_directory, output_directory, host, passphrase):
    authority = protected_directory(authority_directory)
    key, cert = authority / "ca.key.enc", authority / "ca.crt"
    private_file(key)
    private_file(cert)
    if not key.read_bytes().startswith(b"-----BEGIN " + b"ENCRYPTED PRIVATE KEY-----"):
        raise CAError("encrypted_ca_key_required")
    output = Path(output_directory).resolve()
    if output.is_relative_to(authority) or authority.is_relative_to(output):
        raise CAError("authority_and_server_custody_must_be_separate")
    # This tool deliberately issues for the explicit current private endpoint.
    # No wildcard names or automatic future-service identities are inferred.
    if str(ipaddress.ip_address(host)) != "192.168.1.21":
        raise CAError("postgres_endpoint_outside_approved_scope")
    command("x509", "-in", cert, "-checkend", 100 * 86400, "-noout")
    with new_directory(output_directory) as bundle:
        server_key = bundle / "server.key"
        request, extensions = bundle / "server.csr", bundle / "extensions.cnf"
        command("genpkey", "-algorithm", "EC", "-pkeyopt", "ec_paramgen_curve:P-256",
                "-out", server_key)
        command("req", "-new", "-sha256", "-key", server_key,
                "-subj", "/CN=Infrastructure PostgreSQL", "-out", request)
        extensions.write_text(
            "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n"
            "extendedKeyUsage=serverAuth\nsubjectAltName=IP:192.168.1.21\n"
            "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n"
        )
        command("x509", "-req", "-in", request, "-CA", cert, "-CAkey", key,
                "-passin", "PASSPHRASE_FD", "-set_serial", "0x" + secrets.token_hex(16),
                "-days", "90", "-sha384", "-extfile", extensions,
                "-out", bundle / "server.crt", passphrase=passphrase)
        shutil.copyfile(cert, bundle / "ca.crt")
        request.unlink()
        extensions.unlink()
        private_file(server_key)
        # Reuse the actual deployment validator, not a second issuance-only policy.
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts/postgres-tls.py"), "validate",
             "--directory", str(bundle), "--host", host],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30, check=False,
        )
        if result.returncode:
            raise CAError("issued_bundle_failed_deployment_validation")
        return {"state": "bundle_prepared", "ca_sha256": public_fingerprint(cert),
                "server_sha256": public_fingerprint(bundle / "server.crt"),
                "validity_days": 90}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--passphrase-fd", type=int,
                        help="Read one passphrase line from an already open descriptor")
    commands = parser.add_subparsers(dest="operation", required=True)
    create = commands.add_parser("init")
    create.add_argument("--directory", required=True)
    sign = commands.add_parser("issue")
    sign.add_argument("--authority-directory", required=True)
    sign.add_argument("--output-directory", required=True)
    sign.add_argument("--host", required=True)
    try:
        args = parser.parse_args()
        if args.passphrase_fd is None:
            if not sys.stdin.isatty():
                raise CAError("interactive_passphrase_or_descriptor_required")
            passphrase = getpass.getpass("CA passphrase (32+ characters): ").encode()
            if args.operation == "init" and passphrase != getpass.getpass("Confirm CA passphrase: ").encode():
                raise CAError("passphrase_confirmation_mismatch")
        else:
            with os.fdopen(os.dup(args.passphrase_fd), "rb") as stream:
                passphrase = stream.readline(258).removesuffix(b"\n")
        if args.operation == "init":
            result = initialize(args.directory, passphrase)
        else:
            result = issue(args.authority_directory, args.output_directory, args.host, passphrase)
        print(json.dumps(result, sort_keys=True))
        return 0
    except CAError as error:
        reason = str(error)
    except (OSError, ValueError, subprocess.SubprocessError):
        reason = "ca_operation_failed"
    print(json.dumps({"state": "failed", "reason": reason}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
