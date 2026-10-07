"""Exercise the compiler network/authentication boundary and runtime smoke probe."""
import base64
import importlib.util
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

import yaml
from ansible.parsing.dataloader import DataLoader
from ansible.template import Templar

ROOT = Path(__file__).parents[1]
IMAGE = 'caddy:2.11.7-alpine@sha256:d8542f48d34a9cf4e4c11a478865229840e87e4c96ea3f439101f31a5d35f75f'
SPEC = importlib.util.spec_from_file_location('overleaf_verification', ROOT / 'scripts/verify-overleaf.py')
VERIFY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY)


class Response(io.BytesIO):
    def __init__(self, body=b'', status=200):
        super().__init__(body)
        self.status = status


class Opener:
    def __init__(self, *, deny=True, compile_status='success', output_origin='https://clsi.woodhost.cloud', pdf=b'%PDF-fixture', cleanup=204):
        self.deny = deny
        self.compile_status = compile_status
        self.output_origin = output_origin
        self.pdf = pdf
        self.cleanup = cleanup
        self.requests = []

    def open(self, request, timeout):
        self.assert_timeout(timeout)
        if isinstance(request, str):
            return Response()
        self.requests.append(request)
        if not request.has_header('Authorization'):
            if self.deny:
                raise HTTPError(request.full_url, 401, 'denied', {}, io.BytesIO())
            return Response()
        if request.get_method() == 'DELETE':
            return Response(status=self.cleanup)
        if request.get_method() == 'POST':
            project = request.full_url.split('/')[4]
            return Response(json.dumps({'compile': {
                'status': self.compile_status,
                'outputFiles': [{'type': 'pdf', 'url': self.output_origin + '/project/' + project + '/build/test/output/output.pdf'}],
            }}).encode())
        if request.full_url.endswith('output.pdf'):
            return Response(self.pdf)
        return Response()

    @staticmethod
    def assert_timeout(timeout):
        if not 0 < timeout <= 180:
            raise AssertionError('unbounded request')


class VerificationTests(unittest.TestCase):
    def test_success_authenticates_download_and_cleans_its_own_project(self):
        opener = Opener()
        result = VERIFY.verify({'CLSI_USERNAME': 'fixture', 'CLSI_PASSWORD': 'test'}, opener=opener)
        self.assertEqual(result['status'], 'passed')
        post = next(req for req in opener.requests
                    if req.get_method() == 'POST' and req.has_header('Authorization'))
        source = json.loads(post.data)['compile']
        self.assertEqual(source['options']['compiler'], 'lualatex')
        self.assertEqual(source['options']['timeout'], 60)
        download = next(req for req in opener.requests if req.full_url.endswith('output.pdf') and req.has_header('Authorization'))
        self.assertEqual(download.get_header('Authorization'), post.get_header('Authorization'))
        self.assertEqual(opener.requests[-1].get_method(), 'DELETE')
        self.assertEqual(opener.requests[-1].full_url, post.full_url.removesuffix('/compile'))

    def test_auth_bypass_compile_failure_unsafe_output_and_cleanup_failure_are_rejected(self):
        for arguments in ({'deny': False}, {'compile_status': 'error'},
                          {'output_origin': 'http://clsi.woodhost.cloud'},
                          {'output_origin': 'https://attacker.invalid'},
                          {'pdf': b'not a PDF'}, {'cleanup': 500}):
            with self.subTest(arguments=arguments):
                opener = Opener(**arguments)
                with self.assertRaises(ValueError):
                    VERIFY.verify({'CLSI_USERNAME': 'fixture', 'CLSI_PASSWORD': 'test'}, opener=opener)
                if arguments.get('deny') is not False:
                    self.assertEqual(opener.requests[-1].get_method(), 'DELETE')
                self.assertFalse(any('attacker.invalid' in req.full_url for req in opener.requests))

    def test_credentials_require_protected_ownership_and_exact_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'credentials.env'
            path.write_text('CLSI_USERNAME=fixture\nCLSI_PASSWORD=test\n')
            info = type('Info', (), {'st_mode': 0o100600, 'st_uid': 0, 'st_gid': 0})()
            with patch.object(Path, 'stat', return_value=info):
                self.assertEqual(VERIFY.credentials(path)['CLSI_USERNAME'], 'fixture')
                for mode, uid in ((0o100644, 0), (0o100600, 1000)):
                    info.st_mode, info.st_uid = mode, uid
                    with self.assertRaises(ValueError):
                        VERIFY.credentials(path)
                info.st_mode, info.st_uid = 0o100600, 0
                path.write_text('CLSI_USERNAME=fixture\nCLSI_PASSWORD=test\nEXTRA=unexpected\n')
                with self.assertRaises(ValueError):
                    VERIFY.credentials(path)

    def test_oversized_response_and_redirect_are_rejected(self):
        with self.assertRaises(ValueError):
            VERIFY.read_bounded(Response(b'x' * (VERIFY.MAX_RESPONSE + 1)))
        self.assertIsNone(VERIFY.NoRedirect().redirect_request(None, None, 302, '', {}, 'https://attacker.invalid'))


class ComposeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('docker'), 'Requires Docker Compose')
    def test_resolved_compose_has_no_published_ports_or_cross_domain_secrets(self):
        fixture_hash = '$2a$14$fixturehashwithdollars'
        with tempfile.TemporaryDirectory() as directory:
            gateway = Path(directory) / 'gateway.env'
            gateway.write_text('CLSI_USERNAME=fixture\nCLSI_PASSWORD_HASH=' + fixture_hash + '\n')
            result = subprocess.run(
                ['docker', 'compose', '-f', str(ROOT / 'compose/overleaf/compose.yml'), 'config', '--format', 'json'],
                env={**os.environ, 'OVERLEAF_PROJECT_NAME': 'syntax-overleaf',
                     'OVERLEAF_IMAGE': 'syntax-only/overleaf:test', 'OVERLEAF_STATE_PATH': '/tmp/overleaf-test',
                     'OVERLEAF_RUNTIME_ENV_FILE': '/dev/null', 'CLSI_GATEWAY_ENV_FILE': str(gateway),
                     'OVERLEAF_PROXY_NETWORK': 'syntax-proxy'},
                capture_output=True, text=True, timeout=15, check=True,
            )
        config = json.loads(result.stdout)
        services = config['services']
        # Compose escapes dollars in serialized config so it can be read again.
        self.assertEqual(services['clsi-gateway']['environment']['CLSI_PASSWORD_HASH'],
                         fixture_hash.replace('$', '$$'))
        self.assertEqual(set(services), {'overleaf', 'mongo', 'mongo-init', 'redis', 'clsi', 'clsi-gateway'})
        self.assertTrue(all(not service.get('ports') for service in services.values()))
        self.assertEqual(set(services['clsi']['networks']), {'compiler'})
        self.assertEqual(set(services['mongo']['networks']), {'database'})
        self.assertEqual(set(services['redis']['networks']), {'database'})
        self.assertEqual(services['clsi']['user'], '1000:1000')
        self.assertEqual(services['clsi']['security_opt'], ['no-new-privileges:true'])
        self.assertTrue(config['networks']['compiler']['internal'])
        self.assertTrue(config['networks']['database']['internal'])
        self.assertEqual(services['overleaf']['environment']['OVERLEAF_ALLOW_PUBLIC_ACCESS'], 'false')
        self.assertEqual(services['overleaf']['image'], services['clsi']['image'])
        for service in services.values():
            self.assertFalse(any('/srv/docker/docs' in mount.get('source', '') or 'docker.sock' in mount.get('source', '') for mount in service.get('volumes', [])))
        for environment, selected in [('dev', True), ('prod', False)]:
            manifest = yaml.safe_load((ROOT / 'environments' / (environment + '.yml')).read_text())
            self.assertIs(manifest['services']['overleaf'], selected)


class CutoverSafetyTests(unittest.TestCase):
    def test_service_selection_rejects_production_or_missing_platform_dependencies(self):
        tasks = DataLoader().load_from_file(
            str(ROOT / 'ansible/roles/overleaf/tasks/main.yml'), trusted_as_template=True,
        )
        conditions = tasks[0]['ansible.builtin.assert']['that']
        for environment, caddy, infisical, expected in (
                ('dev', True, True, True), ('prod', True, True, False),
                ('dev', False, True, False), ('dev', True, False, False)):
            with self.subTest(environment=environment, caddy=caddy, infisical=infisical):
                templar = Templar(variables={'infrastructure_environment': environment,
                                            'services': {'caddy': caddy, 'infisical': infisical}})
                self.assertEqual(all(templar.evaluate_conditional(condition)
                                     for condition in conditions), expected)

    def test_retirement_rejects_unrelated_containers_and_unexpected_mounts(self):
        document = DataLoader().load_from_file(
            str(ROOT / 'ansible/playbooks/remove-homelab-overleaf.yml'), trusted_as_template=True,
        )
        task = next(task for task in document[0]['tasks'] if task['name'].startswith('Reject unrelated'))
        conditions = task['ansible.builtin.assert']['that']

        def permitted(service, mounts):
            templar = Templar(variables={'item': {
                'Config': {'Labels': {'com.docker.compose.service': service}}, 'Mounts': mounts,
            }})
            return all(templar.evaluate_conditional(condition) for condition in conditions)

        self.assertTrue(permitted('overleaf', [{'Type': 'bind', 'Source': '/srv/docker/docs/overleaf_data'}]))
        self.assertTrue(permitted('mongo', [{'Type': 'volume', 'Destination': '/data/configdb'}]))
        self.assertFalse(permitted('unrelated-service', []))
        self.assertFalse(permitted('mongo', [{'Type': 'bind', 'Source': '/srv/other-database'}]))
        self.assertFalse(permitted('mongo', [{'Type': 'volume', 'Destination': '/unrelated'}]))


class GatewayTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('docker'), 'Requires Docker')
    def test_real_gateway_denies_all_anonymous_requests_and_strips_upstream_credentials(self):
        if subprocess.run(['docker', 'info'], capture_output=True, timeout=10).returncode:
            self.skipTest('Requires a running Docker daemon')

        def docker(*arguments):
            return subprocess.run(['docker', *arguments], text=True, capture_output=True, timeout=90, check=True).stdout.strip()

        password_hash = docker('run', '--rm', IMAGE, 'caddy', 'hash-password', '--plaintext', 'fixture-password')
        name = 'overleaf-gateway-test-' + uuid4().hex
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'Caddyfile'
            route = (ROOT / 'compose/overleaf/clsi.Caddyfile').read_text().replace('clsi:3013', '127.0.0.1:3013')
            path.write_text(route + '\n:3013 {\n @credential header Authorization *\n respond @credential "credential leaked" 500\n respond "fixture" 200\n}\n')
            # Match the deployed config mode even when earlier secret tests
            # leave a restrictive process umask. This contains no secrets.
            path.chmod(0o644)
            try:
                docker('run', '-d', '--name', name, '-p', '127.0.0.1::8080',
                       '--read-only', '--tmpfs', '/data', '--tmpfs', '/config',
                       '--cap-drop', 'ALL', '--cap-add', 'NET_BIND_SERVICE',
                       '--security-opt', 'no-new-privileges:true',
                       '-e', 'CLSI_USERNAME=fixture', '-e', 'CLSI_PASSWORD_HASH=' + password_hash,
                       '-v', str(path) + ':/etc/caddy/Caddyfile:ro', IMAGE)
                base = 'http://' + docker('port', name, '8080/tcp')
                # Hosted runners can take longer to start Caddy than dev hosts.
                # Allow a bounded 30s window and retain the fixture's logs when
                # readiness fails so startup errors are diagnosable in CI.
                deadline = time.monotonic() + 30
                while True:
                    try:
                        urlopen(base + '/status', timeout=2).close()
                    except HTTPError as error:
                        self.assertEqual(error.code, 401)
                        error.close()
                        break
                    except (URLError, ConnectionResetError):
                        if time.monotonic() >= deadline:
                            logs = subprocess.run(['docker', 'logs', name], text=True,
                                                  capture_output=True, timeout=10)
                            self.fail('Gateway did not start within 30s:\n' + logs.stdout + logs.stderr)
                        time.sleep(0.5)
                for endpoint, data in [('/status', None), ('/project/test/compile', b'{}'),
                                       ('/project/test/build/test/output/output.pdf', None)]:
                    for auth in (None, 'Basic ' + base64.b64encode(b'fixture:wrong').decode()):
                        with self.subTest(endpoint=endpoint, auth=auth):
                            headers = {'Authorization': auth} if auth else {}
                            with self.assertRaises(HTTPError) as caught:
                                urlopen(Request(base + endpoint, data=data, headers=headers), timeout=5)
                            self.assertEqual(caught.exception.code, 401)
                            caught.exception.close()
                    auth = 'Basic ' + base64.b64encode(b'fixture:fixture-password').decode()
                    with urlopen(Request(base + endpoint, data=data, headers={'Authorization': auth}), timeout=5) as response:
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.read(), b'fixture')
            finally:
                subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=10)


if __name__ == '__main__':
    unittest.main()
