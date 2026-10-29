"""Exercise dedicated CA custody boundaries using disposable synthetic keys."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("postgres_ca", ROOT / "scripts/postgres-ca.py")
CA = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CA)
PASSPHRASE = b"OFFLINE_SYNTHETIC_CANARY_" * 3


class DedicatedCATests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("openssl"):
            raise RuntimeError("OpenSSL required for CA acceptance")
        cls.temporary = tempfile.TemporaryDirectory(prefix="postgres-ca-fixture-")
        cls.folder = Path(cls.temporary.name).resolve()
        cls.folder.chmod(0o700)
        cls.authority = cls.folder / "authority"
        cls.initial = CA.initialize(cls.authority, PASSPHRASE)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_encrypted_authority_and_deployment_compatible_server_bundle(self):
        key = self.authority / "ca.key.enc"
        self.assertTrue(key.read_bytes().startswith(b"-----BEGIN " + b"ENCRYPTED PRIVATE KEY-----"))
        self.assertEqual(key.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.authority.stat().st_mode & 0o777, 0o700)
        denied = subprocess.run(
            ["openssl", "pkey", "-in", str(key), "-passin", "pass:", "-pubout"],
            capture_output=True, timeout=10,
        )
        self.assertNotEqual(denied.returncode, 0)
        with tempfile.TemporaryDirectory(dir=self.folder) as temporary:
            parent = Path(temporary)
            result = CA.issue(self.authority, parent / "bundle", "192.168.1.21", PASSPHRASE)
            self.assertEqual(result["ca_sha256"], self.initial["ca_sha256"])
            self.assertEqual(result["validity_days"], 90)
            self.assertEqual({p.name for p in (parent / "bundle").iterdir()},
                             {"server.crt", "server.key", "ca.crt"})
            self.assertNotIn("ENCRYPTED", (parent / "bundle/server.key").read_text())
            self.handshake(parent / "bundle")
            renewed = CA.issue(self.authority, parent / "renewed", "192.168.1.21", PASSPHRASE)
            self.assertEqual(renewed["ca_sha256"], result["ca_sha256"])
            self.assertNotEqual(renewed["server_sha256"], result["server_sha256"])

    def test_no_overwrite_wrong_passphrase_and_scope_fail_closed(self):
        before = hashlib.sha256((self.authority / "ca.key.enc").read_bytes()).hexdigest()
        with self.assertRaisesRegex(CA.CAError, "output_already_exists"):
            CA.initialize(self.authority, PASSPHRASE)
        with self.assertRaisesRegex(CA.CAError, "custody_must_be_separate"):
            CA.issue(self.authority, self.authority / "bundle", "192.168.1.21", PASSPHRASE)
        for host, password in (("192.0.2.1", PASSPHRASE), ("192.168.1.21", b"WRONG_SYNTHETIC_PASSPHRASE_" * 3)):
            output = self.folder / "rejected"
            with self.assertRaises(CA.CAError):
                CA.issue(self.authority, output, host, password)
            self.assertFalse(output.exists())
        self.assertEqual(before, hashlib.sha256((self.authority / "ca.key.enc").read_bytes()).hexdigest())
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            with self.assertRaisesRegex(CA.CAError, "outside_git"):
                CA.protected_directory(Path(temporary))

    def handshake(self, bundle):
        client_context = ssl.create_default_context(cafile=str(bundle / "ca.crt"))
        server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        server_context.load_cert_chain(bundle / "server.crt", bundle / "server.key")
        client_in, client_out, server_in, server_out = (ssl.MemoryBIO() for _ in range(4))
        client = client_context.wrap_bio(client_in, client_out, server_hostname="192.168.1.21")
        server = server_context.wrap_bio(server_in, server_out, server_side=True)
        completed = set()
        for _ in range(12):
            for name, connection in (("client", client), ("server", server)):
                if name not in completed:
                    try:
                        connection.do_handshake()
                        completed.add(name)
                    except ssl.SSLWantReadError:
                        pass
            server_in.write(client_out.read())
            client_in.write(server_out.read())
            if completed == {"client", "server"}:
                self.assertIn(("IP Address", "192.168.1.21"), client.getpeercert()["subjectAltName"])
                return
        self.fail("Dedicated CA server certificate could not complete verified TLS")

    def test_descriptor_cli_never_logs_passphrase_or_private_material(self):
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, PASSPHRASE + b"\n")
            os.close(write_fd)
            write_fd = None
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts/postgres-ca.py"),
                 "--passphrase-fd", str(read_fd), "issue",
                 "--authority-directory", str(self.authority),
                 "--output-directory", str(self.folder / "cli-bundle"), "--host", "192.168.1.21"],
                pass_fds=(read_fd,), capture_output=True, timeout=30,
            )
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["state"], "bundle_prepared")
        self.assertNotIn(PASSPHRASE, result.stdout + result.stderr)
        self.assertNotIn(b"PRIVATE KEY", result.stdout + result.stderr)
