"""Exercise the canonical Caddy boundary with loopback and untrusted connections."""

from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


ROOT = Path(__file__).parents[1]
IMAGE = "caddy:2.11.2-alpine"


class RagIngressTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("docker"), "Requires Docker")
    def test_untrusted_clients_and_spoofed_forwarding_headers_are_denied(self):
        available = subprocess.run(["docker", "info"], capture_output=True, timeout=10)
        if available.returncode:
            self.skipTest("Requires a running Docker daemon")
        name = "rag-ingress-test-" + uuid4().hex

        def docker(*arguments):
            return subprocess.run(
                ["docker", *arguments], text=True, capture_output=True,
                timeout=30, check=True,
            ).stdout.strip()

        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory)
            route = (ROOT / "compose/caddy/routes/rag-service.caddy").read_text()
            (config / "Caddyfile").write_text(
                route + '\n:8000 {\n respond "fixture" 200\n}\n'
            )
            try:
                docker("run", "--rm", "-d", "--name", name,
                       "-p", "127.0.0.1::80", "--add-host", "rag-service:127.0.0.1",
                       "-v", f"{config}:/etc/caddy:ro", IMAGE)
                binding = docker("port", name, "80/tcp")
                base = "http://" + binding

                def request(path):
                    return Request(base + path, headers={
                        "Host": "dev-rag-service.woodhost.cloud",
                        "X-Forwarded-For": "192.168.1.21",
                    })

                for attempt in range(30):
                    try:
                        with urlopen(request("/health"), timeout=2) as response:
                            self.assertEqual(response.status, 200)
                        break
                    except (URLError, ConnectionResetError):
                        if attempt == 29:
                            raise
                        time.sleep(0.1)
                for path in ("/mcp", "/mcp/nested", "/metrics", "/ready"):
                    with self.subTest(path=path):
                        with self.assertRaises(HTTPError) as caught:
                            urlopen(request(path), timeout=2)
                        self.assertEqual(caught.exception.code, 403)
                        caught.exception.close()
                        permitted = docker(
                            "exec", name, "wget", "-q", "-O", "-",
                            "--header=Host: dev-rag-service.woodhost.cloud",
                            "http://127.0.0.1" + path,
                        )
                        self.assertEqual(permitted, "fixture")
            finally:
                subprocess.run(["docker", "rm", "-f", name], capture_output=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
