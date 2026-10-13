"""Offline monthly preparation must never authorize or affect a live host."""
import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import monthly_bootstrap as BOOTSTRAP


class MonthlyInputsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        artifact = self.root / 'database.dump.age'
        artifact.write_bytes(b'age-encryption.org/v1\nfixture-ciphertext')
        completed = dt.datetime.now(dt.timezone.utc).isoformat()
        entry = {'source': 'application', 'artifact': artifact.name,
                 'format': 'postgres-custom-age', 'sha256': BOOTSTRAP.digest(artifact),
                 'size_bytes': artifact.stat().st_size,
                 'encryption': {'format': 'age', 'recipient': 'age-fixture'}}
        manifest = {'recovery_group': 'fixture', 'completed_at': completed, 'artifacts': [entry]}
        (self.root / 'manifest.json').write_text(json.dumps(manifest))
        self.plan = {'source_revision': 'a' * 40, 'manifest_sha256': BOOTSTRAP.digest(self.root / 'manifest.json'),
                     'group': 'fixture', 'completed_at': completed, 'encryption_recipient': 'age-fixture',
                     'required_sources': ['application'], 'unretained_images': [],
                     'artifacts': [{k: entry[k] for k in ('source', 'artifact', 'format', 'sha256', 'size_bytes')}],
                     'maximum_lifetime_seconds': 7200, 'resource_reference': 'temporary://recovery-' + 'a' * 32}
        transfer = {'source_revision': 'a' * 40, 'manifest_sha256': self.plan['manifest_sha256'],
                    'guest_recipient': 'age1' + 'a' * 58, 'resource_reference': self.plan['resource_reference'],
                    'artifacts': {'application': {'artifact': artifact.name, 'source_ciphertext_sha256': entry['sha256'],
                        'plaintext_sha256': 'b' * 64, 'ciphertext_sha256': entry['sha256'], 'size_bytes': entry['size_bytes']}}}
        (self.root / 'transport.json').write_text(json.dumps(transfer))

    def test_staging_binds_complete_group_and_source_without_execution(self):
        result = BOOTSTRAP.verify_staged(self.plan, self.root)
        self.assertEqual(result['manifest_sha256'], self.plan['manifest_sha256'])
        self.assertEqual(result['source_revision'], 'a' * 40)

    def test_ciphertext_change_missing_image_and_stale_group_fail_closed(self):
        for mutation, reason in [
                ({'unretained_images': ['build://Dockerfile']}, 'independent_image_artifacts_required'),
                ({'source_revision': 'main'}, 'source_revision_invalid'),
                ({'manifest_sha256': 'b' * 64}, 'staged_manifest_mismatch')]:
            with self.subTest(reason=reason), self.assertRaisesRegex(BOOTSTRAP.BootstrapFailure, reason):
                BOOTSTRAP.verify_staged(self.plan | mutation, self.root)
        with self.assertRaisesRegex(BOOTSTRAP.BootstrapFailure, 'staged_group_stale'):
            BOOTSTRAP.verify_staged(self.plan, self.root, now=dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=2))
        (self.root / 'database.dump.age').write_bytes(b'corrupt')
        with self.assertRaisesRegex(BOOTSTRAP.BootstrapFailure, 'staged_ciphertext_mismatch'):
            BOOTSTRAP.verify_staged(self.plan, self.root)

    def workload(self):
        return {'services': {'application': {
            'image': 'example/app@sha256:' + 'a' * 64, 'networks': ['recovery'],
            'mem_limit': 128 * 1024**2, 'cpus': 0.5, 'volumes': [],
            'security_opt': ['no-new-privileges:true'], 'cap_drop': ['ALL'],
            'healthcheck': {'test': ['CMD', '/app/health'], 'interval': '10s', 'timeout': '5s', 'retries': 6}}},
            'networks': {'recovery': {'internal': True}}}

    def test_workloads_reject_host_network_socket_privilege_and_unbounded_resources(self):
        images = ['oci://example/app@sha256:' + 'a' * 64]
        limits = {'memory_bytes': 1024**3, 'vcpus': 4}
        self.assertEqual(BOOTSTRAP.verify_workloads(self.workload(), self.root, images, limits)['state'], 'passed')
        for key, value in [('network_mode', 'host'), ('privileged', True), ('ports', ['80:80']),
                           ('mem_limit', 2 * 1024**3), ('environment', {'TOKEN': 'fixture'}),
                           ('volumes', [{'type': 'bind', 'source': '/var/run/docker.sock',
                                         'target': '/run/docker.sock', 'read_only': True}])]:
            document = self.workload()
            document['services']['application'][key] = value
            with self.subTest(key=key), self.assertRaises(BOOTSTRAP.BootstrapFailure):
                BOOTSTRAP.verify_workloads(document, self.root, images, limits)

    def test_archive_traversal_links_and_size_limit_are_rejected(self):
        for name, kind, size in [('../escape', tarfile.REGTYPE, 1), ('link', tarfile.SYMTYPE, 0),
                                 ('oversize', tarfile.REGTYPE, 2)]:
            archive = self.root / 'archive.tar.gz'
            with tarfile.open(archive, 'w:gz') as stream:
                member = tarfile.TarInfo(name); member.type = kind; member.size = size
                stream.addfile(member, io.BytesIO(b'xx') if size else None)
            with self.assertRaisesRegex(BOOTSTRAP.BootstrapFailure, 'guest_archive_boundary_invalid'):
                BOOTSTRAP.extract_archive(archive, self.root / ('out-' + kind.decode()), 1)
            # Each subtest owns a distinct clean output.
            import shutil
            shutil.rmtree(self.root / ('out-' + kind.decode()))

    def test_phase_order_and_incomplete_proof_cannot_advance(self):
        program = self.root / 'bootstrap.py'; program.write_text('fixture-only')
        evidence = {'state': 'passed', 'phase': 'bootstrap', 'manifest_sha256': self.plan['manifest_sha256'],
                    'source_revision': self.plan['source_revision'], 'proofs': {'blank_guest': True}}
        phases = BOOTSTRAP.GuestPhases(self.plan, self.root, self.root,
                                      {'bootstrap': {'path': str(program), 'sha256': BOOTSTRAP.digest(program)}},
                                      lambda *args: evidence)
        with self.assertRaisesRegex(BOOTSTRAP.BootstrapFailure, 'bootstrap_phase_order_invalid'):
            phases.run('restore')
        with self.assertRaisesRegex(BOOTSTRAP.BootstrapFailure, 'guest_phase_proof_incomplete'):
            phases.run('bootstrap')
        self.assertEqual(phases.completed, [])

    def test_live_controller_cannot_run_guest_actions(self):
        runtime = BOOTSTRAP.GuestRuntime(self.plan, self.root, self.root, {'execution_authorized': False})
        with patch.object(BOOTSTRAP.subprocess, 'run') as command:
            with self.assertRaisesRegex(BOOTSTRAP.BootstrapFailure, 'approved_guest_required'):
                runtime.bootstrap()
            with self.assertRaisesRegex(BOOTSTRAP.BootstrapFailure, 'approved_guest_required'):
                runtime.cleanup()
            command.assert_not_called()
        self.assertTrue(self.root.exists())

    def test_export_configuration_must_match_the_selected_guest_transport(self):
        runtime = BOOTSTRAP.GuestRuntime(self.plan, self.root, self.root, {})
        with patch.object(runtime, 'boundary'), patch.object(BOOTSTRAP, 'digest') as digest:
            with self.assertRaisesRegex(BOOTSTRAP.BootstrapFailure, 'image_transport_binding_invalid'):
                runtime.dependencies({'oci://unbound/image': {'image_id': 'sha256:' + 'c' * 64}})
            digest.assert_not_called()

    def test_other_disposable_resource_cannot_use_the_plan(self):
        attestation = {'execution_authorized': True, 'source_revision': self.plan['source_revision'],
                       'manifest_sha256': self.plan['manifest_sha256'], 'production_access': False,
                       'resource_reference': 'temporary://recovery-' + 'b' * 32}
        runtime = BOOTSTRAP.GuestRuntime(self.plan, self.root, self.root, attestation)
        with patch.object(BOOTSTRAP.os, 'geteuid', return_value=10001), \
                patch.object(BOOTSTRAP.subprocess, 'run') as command:
            with self.assertRaisesRegex(BOOTSTRAP.BootstrapFailure, 'approved_guest_required'):
                runtime.boundary()
            command.assert_not_called()


if __name__ == '__main__':
    unittest.main()
