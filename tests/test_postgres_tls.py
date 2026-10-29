"""Real certificate validation and credential-free PostgreSQL TLS negotiation."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("postgres_tls", ROOT / "scripts/postgres-tls.py")
TLS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(TLS)


class CertificateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not shutil.which("openssl"):
            if os.environ.get("POSTGRES_TLS_REQUIRE_LOCAL_POSTGRES") == "1":
                raise RuntimeError("Required local OpenSSL unavailable")
            raise unittest.SkipTest("OpenSSL unavailable")
        cls.temporary = tempfile.TemporaryDirectory(prefix="postgres-tls-fixture-")
        cls.root = Path(cls.temporary.name)
        cls.root.chmod(0o700)
        cls.make_bundle(cls.root, "127.0.0.1")
        cls.other = cls.root / "other"
        cls.other.mkdir(mode=0o700)
        cls.make_bundle(cls.other, "192.0.2.1")

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    @staticmethod
    def make_bundle(directory, host):
        def run(*args):
            subprocess.run(["openssl", *map(str, args)], cwd=directory,
                           capture_output=True, check=True, timeout=15)
        run("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "90",
            "-subj", "/CN=offline-test-CA", "-keyout", "ca.key", "-out", "ca.crt",
            "-addext", "basicConstraints=critical,CA:TRUE",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign")
        run("req", "-new", "-newkey", "rsa:2048", "-nodes", "-subj", "/CN=offline-server",
            "-keyout", "server.key", "-out", "server.csr")
        extensions = directory / "extensions.cnf"
        extensions.write_text("subjectAltName=IP:" + host + "\nextendedKeyUsage=serverAuth\n"
                              "basicConstraints=critical,CA:FALSE\n"
                              "keyUsage=critical,digitalSignature,keyEncipherment\n"
                              "subjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\n")
        run("x509", "-req", "-in", "server.csr", "-CA", "ca.crt", "-CAkey", "ca.key",
            "-CAcreateserial", "-days", "60", "-out", "server.crt", "-extfile", extensions)
        (directory / "server.key").chmod(0o600)
        (directory / "ca.key").chmod(0o600)

    def test_valid_bundle_is_stable_and_wrong_identity_and_lifetime_fail(self):
        first = TLS.validate(self.root, "127.0.0.1")
        self.assertEqual(first, TLS.validate(self.root, "127.0.0.1"))
        self.assertRegex(first["generation"], r"^[0-9a-f]{64}$")
        for fields in ({"host": "192.0.2.1"},
                       {"host": "127.0.0.1", "min_valid_seconds": 100 * 86400}):
            with self.subTest(fields=fields), self.assertRaises(TLS.TLSFailure):
                TLS.validate(self.root, **fields)

    def test_wrong_key_ca_and_unsafe_permissions_fail_without_values(self):
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            for name in ("server.crt", "server.key", "ca.crt"):
                shutil.copy(self.root / name, stage / name)
            key = stage / "server.key"
            key.chmod(0o644)
            with self.assertRaisesRegex(TLS.TLSFailure, "private_key_permissions_invalid"):
                TLS.validate(stage, "127.0.0.1")
            key.chmod(0o600)
            shutil.copy(self.other / "server.key", key)
            with self.assertRaisesRegex(TLS.TLSFailure, "certificate_key_mismatch"):
                TLS.validate(stage, "127.0.0.1")
            shutil.copy(self.root / "server.key", key)
            shutil.copy(self.other / "ca.crt", stage / "ca.crt")
            with self.assertRaisesRegex(TLS.TLSFailure, "certificate_validation_failed"):
                TLS.validate(stage, "127.0.0.1")
            result = subprocess.run(
                ["python3", str(ROOT / "scripts/postgres-tls.py"), "validate",
                 "--directory", str(stage), "--host", "127.0.0.1"],
                capture_output=True, text=True, timeout=15,
            )
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["state"], "failed")
            self.assertNotIn("PRIVATE KEY", result.stdout + result.stderr)

    def serve_once(self, *, tls=True):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        server.settimeout(5)
        port = server.getsockname()[1]
        errors = []

        def serve():
            try:
                with server, server.accept()[0] as client:
                    client.settimeout(5)
                    self.assertEqual(client.recv(8), b"\0\0\0\x08\x04\xd2\x16/")
                    client.sendall(b"S" if tls else b"N")
                    if tls:
                        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
                        context.load_cert_chain(self.root / "server.crt", self.root / "server.key")
                        try:
                            with context.wrap_socket(client, server_side=True) as connection:
                                connection.recv(1)
                        except (ssl.SSLError, ConnectionResetError):
                            # Wrong-CA rejection may close TCP before the server
                            # receives a TLS alert (notably on macOS).
                            pass
            except Exception as error:
                errors.append(error)

        thread = threading.Thread(target=serve)
        thread.start()
        return port, thread, errors

    def test_probe_authenticates_endpoint_and_rejects_wrong_ca_and_plaintext(self):
        for tls, ca, expected in (
            (True, self.root / "ca.crt", None),
            (True, self.other / "ca.crt", ssl.SSLCertVerificationError),
            (False, self.root / "ca.crt", TLS.TLSFailure),
        ):
            port, thread, errors = self.serve_once(tls=tls)
            try:
                if expected:
                    with self.assertRaises(expected):
                        TLS.probe("127.0.0.1", port, ca)
                else:
                    self.assertEqual(TLS.probe("127.0.0.1", port, ca)["state"], "verified")
            finally:
                thread.join(timeout=6)
            self.assertFalse(thread.is_alive())
            self.assertEqual(errors, [])

    def test_real_postgres_accepts_verified_tls_and_ordinary_existing_client(self):
        if any(not shutil.which(name) for name in ("initdb", "pg_ctl", "psql")):
            if os.environ.get("POSTGRES_TLS_REQUIRE_LOCAL_POSTGRES") == "1":
                self.fail("Required local PostgreSQL binaries unavailable")
            self.skipTest("Local PostgreSQL binaries unavailable")
        with tempfile.TemporaryDirectory(prefix="postgres-tls-server-") as temporary:
            folder = Path(temporary)
            data = folder / "data"
            with socket.socket() as available:
                available.bind(("127.0.0.1", 0))
                port = available.getsockname()[1]
            subprocess.run(["initdb", "-D", str(data), "-U", "tls_test", "--auth=trust", "--no-locale"],
                           capture_output=True, check=True, timeout=30)
            for name in ("server.crt", "server.key"):
                shutil.copy(self.root / name, data / name)
            (data / "server.key").chmod(0o600)
            with (data / "postgresql.conf").open("a") as stream:
                stream.write(f"\nssl=on\nlisten_addresses='127.0.0.1'\nport={port}\nunix_socket_directories='{folder}'\n")
            subprocess.run(["pg_ctl", "-D", str(data), "-l", str(folder / "server.log"), "-w", "start"],
                           capture_output=True, check=True, timeout=30)
            try:
                self.assertEqual(TLS.probe("127.0.0.1", port, self.root / "ca.crt")["state"], "verified")
                for mode in ("verify-full", "disable"):
                    result = subprocess.run(
                        ["psql", "-X", "-At", "-c", "SELECT 1", "-d",
                         f"host=127.0.0.1 port={port} user=tls_test dbname=postgres sslmode={mode} sslrootcert={self.root / 'ca.crt'}"],
                        env={key: value for key, value in os.environ.items() if not key.startswith("PG")},
                        capture_output=True, text=True, timeout=10,
                    )
                    self.assertEqual(result.returncode, 0, "Disposable client connection failed")
                    self.assertEqual(result.stdout.strip(), "1")
            finally:
                subprocess.run(["pg_ctl", "-D", str(data), "-m", "fast", "-w", "stop"],
                               capture_output=True, check=True, timeout=30)
