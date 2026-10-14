"""QEMU admission, isolation and owned independent cleanup without a VM launch."""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parents[1] / 'scripts'))
import qemu_recovery_provider as QEMU
import qemu_resources as RESOURCES


class QemuProviderTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.root.chmod(0o700)
        self.resource = 'recovery-' + 'a' * 32
        self.reference = 'temporary://' + self.resource
        self.base = self.root / 'base.qcow2'; self.base.write_bytes(b'fixture-template')
        self.inputs = self.root / 'inputs.raw'; self.inputs.write_bytes(b'fixture-offline-inputs')
        self.observation = {'physical_memory_bytes': 32 * QEMU.GIB,
                            'available_memory_bytes': 7 * QEMU.GIB,
                            'pressure': 1, 'pressure_before': 1, 'responsive': True,
                            'swap_in_bytes': 0, 'swap_out_bytes': 0,
                            'free_disk_bytes': 200 * QEMU.GIB}
        self.spec = {'execution_authorized': True, 'architecture': 'amd64',
                     'maximum_seconds': 7200,
                     'expected_peak_ram_bytes': 3 * QEMU.GIB,
                     'storage_requirements_bytes': {key: QEMU.GIB for key in RESOURCES.STORAGE_PARTS},
                     'production_access': False, 'private_identity_in_inputs': False,
                     'drill_only_credentials': True, 'guest_agent_verified': True,
                     'source_revision': 'b' * 40, 'manifest_sha256': 'c' * 64,
                     'staged_bundle_bytes': self.inputs.stat().st_size,
                     'base_image': str(self.base), 'base_sha256': QEMU.checksum(self.base),
                     'input_disk': str(self.inputs), 'input_sha256': QEMU.checksum(self.inputs)}

    def lease(self, pid=None):
        directory = self.root / self.resource; directory.mkdir(mode=0o700)
        document = {'resource': self.resource, 'owner_uid': os.geteuid(),
                    'directory': str(directory), 'pid': pid, 'argv': ['qemu', '-name', self.resource],
                    'expires_at': (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)).isoformat()}
        QEMU.save(directory / 'lease.json', document)
        (directory / 'guest.qcow2').write_bytes(b'owned-disk')
        return directory

    def test_capacity_rejection_never_allocates_or_starts_any_process(self):
        host = QEMU.OfflineQemu(self.root, self.spec)
        with patch.object(QEMU, 'capacity', return_value=self.observation | {'available_memory_bytes': 5 * QEMU.GIB}), \
                patch.object(QEMU.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(QEMU.BootstrapFailure, 'memory_insufficient'):
                host.provision(self.reference)
            start.assert_not_called()
        self.assertFalse((self.root / self.resource).exists())

    def test_disk_reserve_accounts_for_staged_bundle_and_entire_guest_disk(self):
        spec = self.spec | {'staged_bundle_bytes': QEMU.GIB}
        QEMU.admit(self.observation | {'free_disk_bytes': 81 * QEMU.GIB}, spec)
        with self.assertRaisesRegex(QEMU.BootstrapFailure, 'disk_insufficient'):
            QEMU.admit(self.observation | {'free_disk_bytes': 80 * QEMU.GIB}, spec)
        with self.assertRaisesRegex(QEMU.BootstrapFailure, 'size_required'):
            QEMU.admit(self.observation, self.spec | {'staged_bundle_bytes': True})

    def test_changed_template_or_authorization_is_rejected_before_launch(self):
        for changed in [{'execution_authorized': False}, {'production_access': True},
                        {'architecture': 'arm64'}, {'memory_gib': 17},
                        {'base_sha256': 'd' * 64}, {'private_identity_in_inputs': True}]:
            with self.subTest(changed=changed), \
                    patch.object(QEMU, 'capacity', return_value=self.observation), \
                    patch.object(QEMU.subprocess, 'Popen') as start:
                with self.assertRaises(QEMU.BootstrapFailure):
                    QEMU.OfflineQemu(self.root, self.spec | changed).provision(self.reference)
                start.assert_not_called()

    def test_launcher_has_no_network_shared_folders_socket_or_host_monitor(self):
        host = QEMU.OfflineQemu(self.root, self.spec)
        reaper, guest = Mock(pid=100), Mock(pid=101)
        def start(argv, **kwargs):
            lease = json.loads((self.root / self.resource / 'lease.json').read_text())
            self.assertEqual(lease['pid'], None)
            self.assertEqual(kwargs['start_new_session'], True)
            return reaper if '--reap' in argv else guest
        with patch.object(QEMU, 'capacity', return_value=self.observation), \
                patch.object(QEMU.shutil, 'which', side_effect=lambda name: sys.executable), \
                patch.object(QEMU.subprocess, 'run'), patch.object(QEMU.subprocess, 'Popen', side_effect=start) as launch:
            host.provision(self.reference)
        argv = launch.call_args.args[0]
        self.assertEqual(argv[argv.index('-nic') + 1], 'none')
        self.assertIn('-nodefaults', argv)
        self.assertEqual(argv[argv.index('-monitor') + 1], 'none')
        self.assertEqual(argv[argv.index('-m') + 1], '4096')
        self.assertEqual(argv[argv.index('-smp') + 1], '2')
        self.assertFalse(any(item in argv for item in ['-netdev', '-virtfs', '-fsdev', '-daemonize']))
        self.assertIn('readonly=on', ' '.join(argv))
        self.assertEqual(launch.call_count, 2)
        host.slot.close()

    def test_partial_allocation_cleanup_is_owned_and_durable(self):
        directory = self.lease()
        unrelated = self.root / 'unrelated'; unrelated.mkdir(); (unrelated / 'keep').write_text('keep')
        proof = QEMU.destroy(self.root, self.resource)
        self.assertFalse(directory.exists())
        self.assertTrue((unrelated / 'keep').exists())
        self.assertEqual(proof['state'], 'passed')
        self.assertEqual(QEMU.destroy(self.root, self.resource), proof)

    def test_pid_reuse_never_signals_process_or_deletes_its_evidence(self):
        directory = self.lease(pid=12345)
        with patch.object(QEMU, 'identity_matches', return_value=False), \
                patch.object(QEMU.os, 'kill') as probe, patch.object(QEMU.os, 'killpg') as terminate:
            with self.assertRaisesRegex(QEMU.BootstrapFailure, 'identity_changed'):
                QEMU.destroy(self.root, self.resource)
            probe.assert_called_once_with(12345, 0)
            terminate.assert_not_called()
        self.assertTrue(directory.exists())

    def test_reaper_covers_an_expired_partially_allocated_resource(self):
        self.lease()
        self.assertEqual(QEMU.reap(self.root, self.resource)['state'], 'passed')
        self.assertFalse((self.root / self.resource).exists())

    def test_independent_monitor_destroys_only_owned_guest_on_pressure_warning(self):
        directory = self.lease()
        lease = json.loads((directory / 'lease.json').read_text())
        lease['expires_at'] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=30)).isoformat()
        lease['admission'] = {'host_storage_reserve_bytes': 40 * QEMU.GIB}
        QEMU.save(directory / 'lease.json', lease)
        with patch.object(QEMU, 'capacity', return_value=self.observation | {'pressure': 2}):
            self.assertEqual(QEMU.reap(self.root, self.resource)['state'], 'passed')
        self.assertFalse(directory.exists())
        evidence = json.loads((self.root / ('host-' + self.resource + '.json')).read_text())
        self.assertEqual(evidence['reason'], 'qemu_host_pressure_unsafe')

    def test_independent_monitor_failure_is_not_a_safe_host_observation(self):
        directory = self.lease()
        lease = json.loads((directory / 'lease.json').read_text())
        lease['expires_at'] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=30)).isoformat()
        lease['admission'] = {'host_storage_reserve_bytes': 40 * QEMU.GIB}
        QEMU.save(directory / 'lease.json', lease)
        with patch.object(QEMU, 'capacity', side_effect=OSError):
            self.assertEqual(QEMU.reap(self.root, self.resource)['state'], 'passed')
        self.assertFalse(directory.exists())

    def test_unregistered_or_foreign_resources_cannot_be_destroyed(self):
        with self.assertRaises(QEMU.BootstrapFailure):
            QEMU.destroy(self.root, '../escape')
        directory = self.lease()
        lease = json.loads((directory / 'lease.json').read_text()); lease['owner_uid'] += 1
        QEMU.save(directory / 'lease.json', lease)
        with self.assertRaisesRegex(QEMU.BootstrapFailure, 'owner_mismatch'):
            QEMU.destroy(self.root, self.resource)
        self.assertTrue(directory.exists())

    def test_unreconciled_prior_resource_prevents_another_vm(self):
        self.lease()
        with patch.object(QEMU, 'capacity', return_value=self.observation), \
                patch.object(QEMU.shutil, 'which', side_effect=lambda name: sys.executable), \
                patch.object(QEMU.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(QEMU.BootstrapFailure, 'prior_cleanup_unreconciled'):
                QEMU.OfflineQemu(self.root, self.spec).provision('temporary://recovery-' + 'f' * 32)
            start.assert_not_called()

    def test_warning_pressure_and_swap_reject_even_with_plenty_of_memory(self):
        for changed in ({'pressure': 2}, {'pressure_before': 4}, {'pressure': 99},
                        {'responsive': False}, {'swap_out_bytes': 1}, {'swap_in_bytes': 1}):
            with self.subTest(changed=changed), self.assertRaises(QEMU.BootstrapFailure):
                QEMU.admit(self.observation | changed, self.spec)

    def test_workload_estimate_can_escalate_but_never_weaken_acceptance(self):
        selected = RESOURCES.select_profile(self.spec | {'expected_peak_ram_bytes': 7 * QEMU.GIB})
        self.assertEqual(selected['profile'], 'large')
        self.assertEqual(selected['memory_gib'], 8)
        with self.assertRaisesRegex(QEMU.BootstrapFailure, 'exceeds_approved'):
            RESOURCES.select_profile(self.spec | {'expected_peak_ram_bytes': 17 * QEMU.GIB})
        with self.assertRaisesRegex(QEMU.BootstrapFailure, 'estimate_required'):
            RESOURCES.select_profile(self.spec | {'expected_peak_ram_bytes': None})
        with self.assertRaises(QEMU.BootstrapFailure):
            RESOURCES.select_profile(self.spec | {'disk_gib': 101})
        self.assertEqual(RESOURCES.select_profile(self.spec | {'profile': 'small',
            'expected_peak_ram_bytes': QEMU.GIB})['profile'], 'small')

    def test_measured_oom_retries_one_profile_only_after_retained_cleanup_proof(self):
        calls, evidence = [], []
        criteria = ['all essential services healthy together']
        def attempt(spec):
            calls.append(spec)
            self.assertEqual(spec['acceptance_criteria'], criteria)
            if spec['profile'] == 'standard':
                return {'state': 'failed', 'reason': 'guest_oom', 'cleanup_state': 'passed',
                        'metrics': {'guest_oom_events': 1, 'peak_guest_ram_bytes': 4 * QEMU.GIB}}
            self.assertEqual(len(evidence), 1)
            return {'state': 'passed', 'cleanup_state': 'passed'}
        result = RESOURCES.adaptive(self.spec | {'acceptance_criteria': criteria}, attempt,
            lambda profile, proof: evidence.append((profile, proof)))
        self.assertEqual(result['state'], 'passed')
        self.assertEqual([item['profile'] for item in calls], ['standard', 'large'])

    def test_restore_defects_and_unreconciled_cleanup_never_escalate(self):
        for reason in ('restore_failed', 'guest_oom'):
            attempt = Mock(return_value={'state': 'failed', 'reason': reason,
                                         'cleanup_state': 'passed', 'metrics': {}})
            RESOURCES.adaptive(self.spec, attempt, lambda *args: None)
            self.assertEqual(attempt.call_count, 1)
        attempt = Mock(return_value={'state': 'failed', 'reason': 'guest_oom', 'cleanup_state': 'failed'})
        with self.assertRaisesRegex(QEMU.BootstrapFailure, 'cleanup_unreconciled'):
            RESOURCES.adaptive(self.spec, attempt, lambda *args: None)
        self.assertEqual(attempt.call_count, 1)

    def test_pressure_change_under_slot_rejects_before_allocation(self):
        host = QEMU.OfflineQemu(self.root, self.spec)
        with patch.object(QEMU, 'capacity', side_effect=[self.observation,
                self.observation | {'pressure': 2}]), \
                patch.object(QEMU.shutil, 'which', return_value=sys.executable), \
                patch.object(QEMU.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(QEMU.BootstrapFailure, 'pressure_unsafe'):
                host.provision(self.reference)
            start.assert_not_called()
        self.assertIsNone(host.slot)
        self.assertFalse((self.root / self.resource).exists())


if __name__ == '__main__':
    unittest.main()
