"""Measured macOS admission and bounded recovery profiles; never evict workloads."""
import datetime as dt
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import time

from monthly_bootstrap import BootstrapFailure

GIB = 1024**3
PROFILES = {
    'small': {'memory_gib': 2, 'vcpus': 2, 'disk_gib': 40},
    'standard': {'memory_gib': 4, 'vcpus': 2, 'disk_gib': 40},
    'large': {'memory_gib': 8, 'vcpus': 4, 'disk_gib': 80},
    'full': {'memory_gib': 16, 'vcpus': 4, 'disk_gib': 100},
}
STORAGE_PARTS = ('base_image', 'container_images', 'encrypted_staging',
                 'databases', 'application_state', 'temporary_extraction',
                 'filesystem_overhead', 'verification_cleanup')


def quantity(value, reason, positive=False):
    if type(value) is not int or value < (1 if positive else 0):
        raise BootstrapFailure(reason)
    return value


def allocation(spec):
    name = spec.get('profile', 'standard')
    if name not in PROFILES:
        raise BootstrapFailure('qemu_profile_invalid')
    profile = dict(PROFILES[name])
    for field in ('memory_gib', 'vcpus'):
        if field in spec and (type(spec[field]) is not int or spec[field] != profile[field]):
            raise BootstrapFailure('qemu_profile_allocation_mismatch')
    disk = quantity(spec.get('disk_gib', profile['disk_gib']), 'qemu_disk_limit_invalid', True)
    if not 40 <= disk <= 100:
        raise BootstrapFailure('qemu_disk_limit_invalid')
    return dict(profile, profile=name, disk_gib=disk)


def workload(spec):
    peak = quantity(spec.get('expected_peak_ram_bytes'), 'qemu_workload_estimate_required', True)
    parts = spec.get('storage_requirements_bytes')
    if not isinstance(parts, dict) or set(parts) != set(STORAGE_PARTS):
        raise BootstrapFailure('qemu_storage_estimate_required')
    disk = sum(quantity(parts[key], 'qemu_storage_estimate_invalid') for key in STORAGE_PARTS)
    if not disk:
        raise BootstrapFailure('qemu_storage_estimate_required')
    return peak, disk


def select_profile(spec):
    """Choose the smallest profile meeting the unchanged workload contract.

    An unspecified selection starts at Standard. Small requires an explicit
    bootstrap/basic-check workload selection. Estimates include simultaneous
    essential services and guest OS; unknown estimates fail closed.
    """
    peak, disk = workload(spec)
    minimum = allocation(spec)['profile']
    names = list(PROFILES)
    for name in names[names.index(minimum):]:
        chosen = allocation(dict(profile=name, disk_gib=spec.get('disk_gib', PROFILES[name]['disk_gib'])))
        if peak <= chosen['memory_gib'] * GIB and disk <= chosen['disk_gib'] * GIB:
            return chosen
    raise BootstrapFailure('qemu_workload_exceeds_approved_limits')


def vm_sample():
    output = subprocess.check_output(['vm_stat'], text=True, timeout=5)
    match = re.search(r'page size of (\d+) bytes', output)
    if not match:
        raise BootstrapFailure('qemu_host_measurement_unavailable')
    pages = {key: int(value) for key, value in re.findall(r'^"?([^":]+)"?:\s+(\d+)\.', output, re.M)}
    required = {'Pages free', 'Pages inactive', 'Pages speculative', 'File-backed pages', 'Swapins', 'Swapouts'}
    if not required <= pages.keys():
        raise BootstrapFailure('qemu_host_measurement_unavailable')
    return int(match[1]), pages


def capacity(root, sample_seconds=2):
    """Do not count compressed anonymous memory as immediately reclaimable.

    File-backed and inactive pages overlap: cap reclaimable inactive/speculative
    pages at file-backed pages rather than adding both counters. The sysctl
    returns dispatch pressure bits (1 normal, 2 warning, 4 critical), not XNU's
    internal pressure enum. Any unknown pressure state rejects admission.
    """
    if not 1 <= sample_seconds <= 5:
        raise BootstrapFailure('qemu_measurement_interval_invalid')
    start = time.monotonic()
    page_size, before = vm_sample()
    pressure_before = int(subprocess.check_output(
        ['sysctl', '-n', 'kern.memorystatus_vm_pressure_level'], text=True, timeout=5))
    time.sleep(sample_seconds)
    page_size_after, after = vm_sample()
    if page_size != page_size_after:
        raise BootstrapFailure('qemu_host_measurement_unavailable')
    physical = int(subprocess.check_output(['sysctl', '-n', 'hw.memsize'], text=True, timeout=5))
    pressure = int(subprocess.check_output(
        ['sysctl', '-n', 'kern.memorystatus_vm_pressure_level'], text=True, timeout=5))
    swap = subprocess.check_output(['sysctl', 'vm.swapusage'], text=True, timeout=5)
    used = re.search(r'used\s*=\s*([\d.]+)M', swap)
    if not used:
        raise BootstrapFailure('qemu_host_measurement_unavailable')
    free = after['Pages free'] * page_size
    reclaimable = min(after['Pages inactive'] + after['Pages speculative'],
                      after['File-backed pages']) * page_size
    elapsed = time.monotonic() - start
    if any(after[key] < before[key] for key in ('Swapins', 'Swapouts')):
        raise BootstrapFailure('qemu_host_measurement_unavailable')
    return {'observed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
            'physical_memory_bytes': physical, 'free_memory_bytes': free,
            'reclaimable_memory_bytes': reclaimable,
            'available_memory_bytes': free + reclaimable,
            'pressure': pressure, 'pressure_before': pressure_before,
            'swap_used_bytes': int(float(used[1]) * 1024**2),
            'swap_in_bytes': (after['Swapins'] - before['Swapins']) * page_size,
            'swap_out_bytes': (after['Swapouts'] - before['Swapouts']) * page_size,
            'sample_seconds': elapsed, 'responsive': elapsed <= sample_seconds + 10,
            'free_disk_bytes': shutil.disk_usage(root).free}


def admit(observation, spec):
    chosen = select_profile(spec)
    peak, disk = workload(spec)
    staged = quantity(spec.get('staged_bundle_bytes'), 'qemu_staged_bundle_size_required')
    reserve = quantity(spec.get('host_storage_reserve_bytes', 40 * GIB), 'qemu_disk_reserve_invalid')
    if reserve < 40 * GIB:
        raise BootstrapFailure('qemu_disk_reserve_invalid')
    if (observation['pressure'] != 1 or observation['pressure_before'] != 1
            or observation['responsive'] is not True):
        raise BootstrapFailure('qemu_host_pressure_unsafe')
    if observation['swap_in_bytes'] or observation['swap_out_bytes']:
        raise BootstrapFailure('qemu_host_swap_active')
    required = (chosen['memory_gib'] + 2) * GIB
    if (observation['physical_memory_bytes'] < required
            or observation['available_memory_bytes'] < required):
        raise BootstrapFailure('qemu_host_memory_insufficient')
    # Reserve maximum possible sparse growth, not just current allocated blocks.
    if observation['free_disk_bytes'] < chosen['disk_gib'] * GIB + reserve + staged:
        raise BootstrapFailure('qemu_host_disk_insufficient')
    return {'state': 'passed', 'allocation': chosen, 'expected_peak_ram_bytes': peak,
            'expected_disk_bytes': disk, 'host_storage_reserve_bytes': reserve,
            'required_available_memory_bytes': required, 'host': observation}


def adaptive(spec, attempt, retain, clock=time.monotonic):
    """Run bounded attempts; callback MUST return independently observed cleanup.

    Only guest OOM/disk exhaustion with numeric measurements allows one-profile
    escalation. Restore defects, unavailable proof and unsafe host conditions stop.
    The callback owns the standard SDK lifecycle and receives the same criteria
    on every attempt; no phase is skipped or converted to a passing result here.
    """
    chosen = select_profile(spec)
    started = clock()
    names = list(PROFILES)
    while True:
        remaining = math.floor(7200 - (clock() - started))
        if remaining <= 0:
            raise BootstrapFailure('qemu_adaptive_deadline_expired')
        current = dict(spec, **chosen, maximum_seconds=remaining)
        result = attempt(current)
        # Preserve the failure before examining retry eligibility or cleanup.
        retain(chosen['profile'], result)
        if result.get('cleanup_state') != 'passed':
            raise BootstrapFailure('qemu_cleanup_unreconciled')
        if result.get('state') == 'passed':
            return result
        metrics = result.get('metrics', {})
        reason = result.get('reason')
        exhausted = (reason == 'guest_oom' and metrics.get('guest_oom_events', 0) > 0
                     and quantity(metrics.get('peak_guest_ram_bytes'), 'qemu_retry_measurement_required')
                     >= chosen['memory_gib'] * GIB * 0.9)
        exhausted = exhausted or (reason == 'guest_disk_full' and metrics.get('guest_enospc_events', 0) > 0
                     and quantity(metrics.get('peak_guest_disk_bytes'), 'qemu_retry_measurement_required')
                     >= chosen['disk_gib'] * GIB * 0.9)
        if not exhausted or chosen['profile'] == 'full':
            return result
        next_name = names[names.index(chosen['profile']) + 1]
        chosen = allocation({'profile': next_name, 'disk_gib': max(chosen['disk_gib'], PROFILES[next_name]['disk_gib'])})


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--spec', type=Path)
    args = parser.parse_args()
    observed = capacity(args.root)
    result = {'state': 'observed', 'host': observed, 'launch_permitted': False}
    if args.spec:
        try:
            result = admit(observed, json.loads(args.spec.read_text()))
        except BootstrapFailure as error:
            result = {'state': 'rejected', 'reason': str(error), 'host': observed, 'launch_permitted': False}
    print(json.dumps(result, sort_keys=True))
