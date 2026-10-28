#!/usr/bin/env python3
"""Validate supplied TLS material and probe PostgreSQL without credentials."""

import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import socket
import ssl
import stat
import struct
import subprocess
import time


class TLSFailure(ValueError):
    pass


def openssl(*arguments):
    result = subprocess.run(
        ["openssl", *map(str, arguments)], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15,
        check=False,
    )
    if result.returncode or len(result.stdout) > 65536:
        raise TLSFailure("certificate_validation_failed")
    return result.stdout


def validate(directory, host, *, key_owner=None, min_valid_seconds=2592000):
    directory = Path(directory)
    if not directory.is_absolute() or not directory.is_dir():
        raise TLSFailure("certificate_directory_invalid")
    # A root-controlled current symlink is the managed atomic generation pointer.
    # Neither source nor installed files may be symlinks or writable by others.
    if stat.S_IMODE(directory.stat().st_mode) & 0o022:
        raise TLSFailure("certificate_directory_permissions_invalid")
    for name in ("server.crt", "server.key", "ca.crt"):
        path = directory / name
        status = path.lstat()
        if not stat.S_ISREG(status.st_mode) or status.st_size > 65536:
            raise TLSFailure("certificate_file_invalid")
        if stat.S_IMODE(status.st_mode) & 0o022:
            raise TLSFailure("certificate_file_permissions_invalid")
        if name == "server.key" and (
            status.st_uid != (os.geteuid() if key_owner is None else key_owner)
            or stat.S_IMODE(status.st_mode) & 0o077
        ):
            raise TLSFailure("private_key_permissions_invalid")
    if not isinstance(min_valid_seconds, int) or min_valid_seconds < 86400:
        raise TLSFailure("certificate_lifetime_policy_invalid")
    cert, key, ca = (directory / name for name in ("server.crt", "server.key", "ca.crt"))
    if b"ENCRYPTED" in key.read_bytes():
        raise TLSFailure("encrypted_private_key_unsupported")
    try:
        ipaddress.ip_address(host)
        identity_option = "-verify_ip"
    except ValueError:
        if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?", host):
            raise TLSFailure("certificate_hostname_invalid") from None
        identity_option = "-verify_hostname"
    openssl("x509", "-in", cert, "-checkend", min_valid_seconds, "-noout")
    openssl("x509", "-in", ca, "-checkend", min_valid_seconds, "-noout")
    # Check the whole chain both now and at the renewal threshold, including
    # intermediates that may expire before the leaf certificate.
    for when in ((), ("-attime", str(int(time.time()) + min_valid_seconds))):
        openssl("verify", "-x509_strict", "-auth_level", "2", *when,
                "-CAfile", ca, "-untrusted", cert, "-purpose", "sslserver",
                identity_option, host, cert)
    public_cert = openssl("x509", "-in", cert, "-pubkey", "-noout")
    public_key = openssl("pkey", "-in", key, "-passin", "pass:", "-pubout")
    if public_cert != public_key:
        raise TLSFailure("certificate_key_mismatch")
    generation = hashlib.sha256(cert.read_bytes() + b"\0" + ca.read_bytes()).hexdigest()
    return {"state": "validated", "generation": generation}


def probe(host, port, ca_file):
    """Negotiate PostgreSQL SSLRequest, then authenticate only the server."""
    context = ssl.create_default_context(cafile=str(ca_file))
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    with socket.create_connection((host, port), timeout=10) as connection:
        connection.sendall(struct.pack("!II", 8, 80877103))
        if connection.recv(1) != b"S":
            raise TLSFailure("postgresql_tls_unavailable")
        with context.wrap_socket(connection, server_hostname=host) as protected:
            return {"state": "verified", "protocol": protected.version()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    check = commands.add_parser("validate")
    check.add_argument("--directory", required=True)
    check.add_argument("--host", required=True)
    check.add_argument("--key-owner", type=int)
    check.add_argument("--min-valid-seconds", type=int, default=2592000)
    endpoint = commands.add_parser("probe")
    endpoint.add_argument("--host", required=True)
    endpoint.add_argument("--port", type=int, required=True)
    endpoint.add_argument("--ca-file", required=True)
    args = parser.parse_args()
    try:
        if args.operation == "validate":
            result = validate(args.directory, args.host, key_owner=args.key_owner,
                              min_valid_seconds=args.min_valid_seconds)
        else:
            result = probe(args.host, args.port, args.ca_file)
        print(json.dumps(result, sort_keys=True))
        return 0
    except TLSFailure as error:
        reason = str(error)
    except (OSError, ValueError, subprocess.SubprocessError):
        reason = "tls_operation_failed"
    print(json.dumps({"state": "failed", "reason": reason}))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
