"""Verify the declaration reaches release, reboot, retirement, and rollback."""
import copy
import importlib.machinery
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from jinja2 import Environment, nativetypes
import yaml


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))


def load_script(name):
    path = ROOT / 'scripts' / name
    loader = importlib.machinery.SourceFileLoader(name.replace('-', '_'), str(path))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


FILTER = load_script('../ansible/filter_plugins/dagster_locations.py')
RETIRE = load_script('retire-dagster-external-locations')
ROLLBACK = load_script('rollback-infrastructure-infisical-service')
DEPLOY = load_script('deploy-infrastructure-infisical-service')


def deployment_inputs(manifest):
    """Render the actual manifest expressions and role payloads used by Ansible."""
    native = nativetypes.NativeEnvironment()
    native.filters.update(FILTER.FilterModule().filters())
    native.filters['to_nice_json'] = lambda value: json.dumps(value, indent=4)
    metadata = copy.deepcopy(manifest['infrastructure_infisical_runtime_services'])
    for key, value in list(metadata['dagster'].items()):
        if isinstance(value, str) and '{{' in value:
            metadata['dagster'][key] = native.from_string(value).render(**manifest)
    context = {**manifest, 'infrastructure_infisical_runtime_services': metadata}
    role = yaml.safe_load((ROOT / 'ansible/roles/dagster/tasks/main.yml').read_text())
    health_task = next(task for task in role if task['name'].startswith('Publish external Dagster'))
    health = native.from_string(health_task['ansible.builtin.copy']['content']).render(**context)
    engine = Environment(autoescape=False)
    compose = yaml.safe_load(engine.from_string(
        (ROOT / 'ansible/roles/dagster/templates/compose.infisical.yml.j2').read_text()
    ).render(**manifest))
    workspace = yaml.safe_load(engine.from_string(
        (ROOT / 'ansible/roles/dagster/templates/workspace.yaml.j2').read_text()
    ).render(**manifest))
    return metadata, compose, workspace, health, role


class DeclarationHandoffTests(unittest.TestCase):
    def setUp(self):
        self.manifest = yaml.safe_load((ROOT / 'environments/dev.yml').read_text())
        self.minimal = {
            'name': 'data_cleanup', 'service_name': 'data-cleanup-code',
            'image': 'ghcr.io/example/data-cleanup:v1@sha256:' + 'a' * 64,
            'port': 4000,
        }

    def test_normal_dev_release_installs_current_reconciliation_inputs(self):
        dev = yaml.safe_load((ROOT / 'ansible/playbooks/dev.yml').read_text())
        deploy = yaml.safe_load((ROOT / 'ansible/playbooks/deploy.yml').read_text())
        self.assertEqual(dev[0]['import_playbook'], 'deploy.yml')
        self.assertEqual(dev[0]['vars']['infrastructure_environment'], 'dev')
        self.assertTrue(any(task.get('ansible.builtin.include_role', {}).get('name') == 'dagster'
                            for task in deploy[0]['tasks']))
        metadata, _, _, _, role = deployment_inputs(self.manifest)
        install = next(task for task in role if task['name'] == 'Install current Dagster Infisical reconciliation tools')
        self.assertIn('deploy-infrastructure-infisical-service', str(install['loop']))
        self.assertIn('retire-dagster-external-locations', str(install['loop']))
        publish = next(task for task in role if task['name'] == 'Publish current Dagster Infisical reconciliation metadata')
        self.assertEqual(publish['ansible.builtin.copy']['dest'],
                         '/etc/infrastructure/infisical-runtime-services.json')
        self.assertIn('infrastructure_infisical_runtime_services', publish['ansible.builtin.copy']['content'])
        self.assertEqual(metadata['dagster']['external_code_locations'],
                         self.manifest['dagster_code_locations'])
        self.assertLess(role.index(install), role.index(publish))
        self.assertLess(next(i for i, task in enumerate(role) if task['name'].startswith('Start selected Dagster')),
                        role.index(publish))
        capture = next(task for task in role if task['name'] ==
                       'Retain Compose interpolation values for Dagster rollback')
        rewrite = next(task for task in role if task['name'] == 'Deploy Dagster Compose environment')
        retain_locations = next(task for task in role if task['name'] ==
                                'Retain external Dagster rollback target metadata')
        bootstrap = next(task for task in role if task['name'] ==
                         'Bootstrap external Dagster ownership before first Compose rewrite')
        self.assertLess(role.index(capture), role.index(retain_locations))
        self.assertLess(role.index(retain_locations), role.index(bootstrap))
        self.assertLess(role.index(bootstrap), role.index(rewrite))
        self.assertIn('not dagster_rollback_environment.stat.exists', capture['when'])
        self.assertNotIn('ignore_errors', capture)

    def test_declaration_reaches_all_deployment_inputs(self):
        self.manifest['dagster_code_locations'].append(self.minimal)
        metadata, compose, workspace, health, _ = deployment_inputs(self.manifest)
        self.assertIn('data-cleanup-code', compose['services'])
        self.assertIn({'grpc_server': {'host': 'data-cleanup-code', 'port': 4000,
                                      'location_name': 'data_cleanup'}}, workspace['load_from'])
        self.assertIn('data-cleanup-code', health)
        self.assertIn('data-cleanup-code', metadata['dagster']['compose_services'])
        self.assertIn(self.minimal, metadata['dagster']['external_code_locations'])
        self.assertEqual(compose['services']['data-cleanup-code']['env_file'], [
            '/srv/infrastructure/secrets/static/dagster.env',
            '/srv/infrastructure/secrets/runtime/dagster.env'])
        self.assertEqual(compose['services']['data-cleanup-code']['networks'], ['postgres'])

    def test_runtime_mapping_is_consumed_only_when_referenced(self):
        self.manifest['dagster_code_locations'] = [self.minimal]
        metadata, compose, _, _, _ = deployment_inputs(self.manifest)
        self.assertEqual(metadata['dagster']['runtime_environments'], {})
        self.assertNotIn('openproject-reports.env', str(compose['services']['data-cleanup-code']))
        self.manifest['dagster_code_locations'][0]['runtime_env'] = 'openproject_reports'
        metadata, compose, _, _, _ = deployment_inputs(self.manifest)
        self.assertEqual(set(metadata['dagster']['runtime_environments']), {'openproject_reports'})
        self.assertEqual(compose['services']['data-cleanup-code']['env_file'][-1],
                         self.manifest['dagster_runtime_environments']['openproject_reports']['output'])

    def test_removing_declaration_changes_only_external_retirement_set(self):
        current, _, _, _, _ = deployment_inputs(self.manifest)
        self.manifest['dagster_code_locations'] = []
        target, compose, workspace, health, _ = deployment_inputs(self.manifest)
        removed = ({item['service_name'] for item in current['dagster']['external_code_locations']}
                   - {item['service_name'] for item in target['dagster']['external_code_locations']})
        self.assertEqual(removed, {'openproject-reports-code'})
        self.assertEqual(health, [])
        self.assertNotIn('openproject-reports-code', compose['services'])
        self.assertNotIn('openproject-reports-code', str(workspace))
        self.assertTrue({'dagster-user-code', 'dagster-codex-usage',
                         'dagster-webserver', 'dagster-daemon'} <= set(target['dagster']['compose_services']))

    def test_retained_target_metadata_uses_snapshot_services(self):
        tasks = yaml.safe_load((ROOT / 'ansible/roles/dagster/tasks/retain_rollback_locations.yml').read_text())
        publish = next(task for task in tasks if task['name'] ==
                       'Retain external Dagster rollback target metadata once')
        template = publish['ansible.builtin.copy']['content']
        native = nativetypes.NativeEnvironment()
        native.filters['to_nice_json'] = lambda value: json.dumps(value)
        context = {
            'dagster_previous_external_locations':
                deployment_inputs(self.manifest)[0]['dagster']['external_code_locations'],
            'dagster_retained_compose_services': {'stdout_lines': [
                'dagster-user-code', 'dagster-webserver', 'dagster-daemon']},
        }
        self.assertEqual(native.from_string(template).render(**context), [])
        context['dagster_retained_compose_services']['stdout_lines'].append('openproject-reports-code')
        rendered = native.from_string(template).render(**context)
        self.assertEqual(json.loads(rendered) if isinstance(rendered, str) else rendered,
                         self.manifest['dagster_code_locations'])


class RetirementTests(unittest.TestCase):
    def test_only_previously_declared_external_container_is_retired(self):
        old = {'name': 'old', 'service_name': 'old-code', 'port': 4000}
        current = {'name': 'current', 'service_name': 'new-code', 'port': 4000}
        previous = RETIRE.locations_from_json([old, current])
        desired = RETIRE.locations_from_json([current])
        containers = [
            {'Id': 'old', 'Config': {'Labels': {'com.docker.compose.project': RETIRE.PROJECT,
                                             'com.docker.compose.service': 'old-code'}}},
            {'Id': 'current', 'Config': {'Labels': {'com.docker.compose.project': RETIRE.PROJECT,
                                                 'com.docker.compose.service': 'new-code'}}},
            {'Id': 'owned', 'Config': {
                'Image': 'ghcr.io/example/owned@sha256:' + 'c' * 64,
                'Env': ['DAGSTER_GRPC_PORT=4000'],
                'Labels': {'com.docker.compose.project': RETIRE.PROJECT,
                           'com.docker.compose.service': 'dagster-codex-usage'}}},
            {'Id': 'other', 'Config': {
                'Image': 'ghcr.io/example/unknown@sha256:' + 'd' * 64,
                'Env': ['DAGSTER_GRPC_PORT=4000'],
                'Labels': {'com.docker.compose.project': RETIRE.PROJECT,
                           'com.docker.compose.service': 'unknown-owned'}}},
            {'Id': 'foreign', 'Config': {'Labels': {
                'com.docker.compose.project': 'different-project',
                'com.docker.compose.service': 'old-code'}}},
        ]
        removed = []
        def fake_run(argv, **kwargs):
            if argv[1:3] == ['rm', '-f']:
                removed.extend(argv[3:])
                containers[:] = [item for item in containers if item['Id'] not in removed]
            class Result:
                stdout = ('\n'.join(item['Id'] for item in containers)
                          if argv[1] == 'ps' else json.dumps(containers))
            return Result()
        with patch.object(RETIRE.subprocess, 'run', side_effect=fake_run):
            self.assertEqual(RETIRE.obsolete_containers(previous, desired), ['old'])
            self.assertEqual(RETIRE.retire(previous, desired), 1)
            self.assertEqual(RETIRE.retire(previous, desired), 0)
        self.assertEqual(removed, ['old'])
        self.assertEqual(RETIRE.obsolete_services({}, desired), set())
        with self.assertRaisesRegex(ValueError, 'infrastructure-owned'):
            RETIRE.locations_from_json([
                {'name': 'owned', 'service_name': 'dagster-codex-usage', 'port': 4000}])

    def test_boot_reconciliation_publishes_desired_deployment_metadata(self):
        manifest = yaml.safe_load((ROOT / 'environments/dev.yml').read_text())
        item = deployment_inputs(manifest)[0]['dagster']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'runtime-services.json'
            config.write_text(json.dumps({'dagster': item}))
            current = root / 'external-locations.json'
            current.write_text('[]\n')
            calls = []
            def fake_run(argv, **kwargs):
                calls.append(argv)
                class Result:
                    stdout = ''
                return Result()
            with patch.object(DEPLOY, 'CONFIG', config), patch.object(DEPLOY, 'CURRENT', current), \
                 patch.object(DEPLOY.os, 'geteuid', return_value=0), \
                 patch.object(DEPLOY.sys, 'argv', ['deploy', 'dagster']), \
                 patch.object(DEPLOY.subprocess, 'run', side_effect=fake_run):
                DEPLOY.run()
            self.assertIn('--desired-json', calls[-1])
            self.assertEqual(json.loads(current.read_text()), manifest['dagster_code_locations'])

    def test_service_transferred_to_infrastructure_ownership_is_protected(self):
        previous = RETIRE.locations_from_json([
            {'name': 'former_external', 'service_name': 'future-owned-code', 'port': 4000}])
        self.assertEqual(RETIRE.obsolete_services(previous, {}, ['future-owned-code']), set())
        with patch.object(RETIRE.subprocess, 'run') as docker:
            self.assertEqual(RETIRE.retire(previous, {}, ['future-owned-code']), 0)
        docker.assert_not_called()

    def test_old_boot_metadata_cannot_retire_newly_bootstrapped_ownership(self):
        manifest = yaml.safe_load((ROOT / 'environments/dev.yml').read_text())
        item = deployment_inputs(manifest)[0]['dagster']
        del item['external_code_locations']
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'runtime-services.json'
            config.write_text(json.dumps({'dagster': item}))
            current = root / 'external-locations.json'
            current.write_text(json.dumps(manifest['dagster_code_locations']))
            calls = []
            def fake_run(argv, **kwargs):
                calls.append(argv)
                class Result:
                    stdout = ''
                return Result()
            with patch.object(DEPLOY, 'CONFIG', config), patch.object(DEPLOY, 'CURRENT', current), \
                 patch.object(DEPLOY.os, 'geteuid', return_value=0), \
                 patch.object(DEPLOY.sys, 'argv', ['deploy', 'dagster']), \
                 patch.object(DEPLOY.subprocess, 'run', side_effect=fake_run):
                DEPLOY.run()
            self.assertFalse(any('retire-dagster-external-locations' in argv[0] for argv in calls))
            self.assertEqual(json.loads(current.read_text()), manifest['dagster_code_locations'])


class RollbackTests(unittest.TestCase):
    def test_snapshot_variables_come_from_retained_env_not_process(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot = root / 'compose.pre-infisical.yml'
            snapshot.write_text('image: ${OPENPROJECT_REPORTS_IMAGE_REF:?required}\n'
                                'name: ${DAGSTER_PROJECT_NAME:?required}\n')
            current = root / 'current.env'
            current.write_text('DAGSTER_PROJECT_NAME=current\n')
            with patch.dict(os.environ, {'OPENPROJECT_REPORTS_IMAGE_REF': 'ambient'}):
                with self.assertRaisesRegex(ValueError, 'retained rollback Compose environment unavailable'):
                    ROLLBACK.snapshot_environment(snapshot)
                retained = root / 'compose.pre-infisical.env'
                retained.write_text('DAGSTER_PROJECT_NAME=retained\n')
                with self.assertRaisesRegex(ValueError, 'OPENPROJECT_REPORTS_IMAGE_REF'):
                    ROLLBACK.snapshot_environment(snapshot)
                retained.write_text('DAGSTER_PROJECT_NAME=retained\n'
                                    'OPENPROJECT_REPORTS_IMAGE_REF=pinned\n')
                selected, process_env = ROLLBACK.snapshot_environment(snapshot)
                self.assertEqual(selected, retained)
                self.assertNotIn('OPENPROJECT_REPORTS_IMAGE_REF', process_env)

    def test_rollback_validates_before_changes_and_retires_absent_external(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / 'compose.yml'
            active.write_text('current')
            workspace = root / 'config/workspace.yaml'
            workspace.parent.mkdir()
            workspace.write_text('load_from:\n'
                                 '  - grpc_server: {host: dagster-user-code, port: 4000, location_name: owned}\n'
                                 '  - grpc_server: {host: old-code, port: 4000, location_name: old}\n')
            snapshot = root / 'compose.pre-infisical.yml'
            snapshot.write_text('name: ${DAGSTER_PROJECT_NAME:?required}\nservices: {}\n')
            (root / 'compose.pre-infisical.env').write_text('DAGSTER_PROJECT_NAME=test\n')
            (root / 'compose.pre-infisical-locations.json').write_text('[]\n')
            (root / 'legacy.env').write_text('legacy')
            current = root / 'current-locations.json'
            current.write_text(json.dumps([
                {'name': 'old', 'service_name': 'old-code', 'port': 4000}]))
            config = root / 'metadata.json'
            config.write_text(json.dumps({'dagster': {
                'compose_file': str(active), 'legacy_env_file': str(root / 'legacy.env'),
                'compose_env_file': str(root / 'current.env')}}))
            health = root / 'health.json'
            calls = []
            def fake_run(argv, **kwargs):
                calls.append(argv)
                class Result:
                    stdout = ('dagster-user-code\ndagster-daemon\n'
                              if argv[-2:] == ['config', '--services'] else '')
                return Result()
            with patch.object(ROLLBACK, 'CONFIG', config), patch.object(ROLLBACK, 'HEALTH', health), \
                 patch.object(ROLLBACK, 'CURRENT', current), \
                 patch.object(ROLLBACK.os, 'geteuid', return_value=0), \
                 patch.object(ROLLBACK.sys, 'argv', ['rollback', 'dagster']), \
                 patch.object(ROLLBACK.subprocess, 'run', side_effect=fake_run):
                ROLLBACK.run()
            self.assertEqual(calls[0][-2:], ['config', '--quiet'])
            self.assertEqual(calls[1][-2:], ['config', '--services'])
            self.assertEqual(calls[2][0], 'systemctl')
            self.assertIn('retire-dagster-external-locations', calls[-1][0])
            self.assertIn('--desired-file', calls[-1])
            self.assertEqual(json.loads(health.read_text()), [])
            self.assertEqual(json.loads(current.read_text()), [])
            self.assertNotIn('old-code', workspace.read_text())
            self.assertIn('dagster-user-code', workspace.read_text())

    def test_unknown_workspace_entry_blocks_rollback_before_service_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / 'workspace.yaml'
            workspace.write_text('load_from:\n  - grpc_server:\n      host: old-code\n')
            with self.assertRaisesRegex(ValueError, 'unknown format'):
                ROLLBACK.rollback_workspace(
                    workspace, {'old-code': {'name': 'old', 'service_name': 'old-code', 'port': 4000}}, {})
            self.assertIn('old-code', workspace.read_text())

    def test_workspace_uses_deployment_metadata_when_container_is_absent(self):
        manifest = yaml.safe_load((ROOT / 'environments/dev.yml').read_text())
        manifest['dagster_code_locations'].append({
            'name': 'data_cleanup', 'service_name': 'data-cleanup-code',
            'image': 'ghcr.io/example/data-cleanup:v1@sha256:' + 'a' * 64,
            'port': 4001,
        })
        current_metadata = deployment_inputs(manifest)[0]['dagster']['external_code_locations']
        target_metadata = current_metadata[:1]
        current = RETIRE.locations_from_json(current_metadata)
        target = RETIRE.locations_from_json(target_metadata)
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory) / 'workspace.yaml'
            workspace.write_text(Environment(autoescape=False).from_string(
                (ROOT / 'ansible/roles/dagster/templates/workspace.yaml.j2').read_text()
            ).render(**manifest))
            result = ROLLBACK.rollback_workspace(workspace, current, target).decode()
        self.assertNotIn('data-cleanup-code', result)
        self.assertIn('openproject-reports-code', result)
        self.assertIn('dagster-user-code', result)
        self.assertIn('dagster-codex-usage', result)

    def test_prerequisite_failure_reports_phase_and_leaves_runtime_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / 'compose.yml'
            active.write_text('current')
            (root / 'compose.pre-infisical.yml').write_text(
                'name: ${DAGSTER_PROJECT_NAME:?required}\nservices: {}\n')
            (root / 'compose.pre-infisical.env').write_text('OTHER=value\n')
            (root / 'legacy.env').write_text('legacy')
            config = root / 'metadata.json'
            config.write_text(json.dumps({'dagster': {
                'compose_file': str(active), 'legacy_env_file': str(root / 'legacy.env'),
                'compose_env_file': str(root / 'current.env')}}))
            calls = []
            with patch.object(ROLLBACK, 'CONFIG', config), \
                 patch.object(ROLLBACK.os, 'geteuid', return_value=0), \
                 patch.object(ROLLBACK.sys, 'argv', ['rollback', 'dagster']), \
                 patch.object(ROLLBACK.subprocess, 'run', side_effect=lambda *a, **k: calls.append(a)):
                with self.assertRaises(ROLLBACK.RollbackFailure) as error:
                    ROLLBACK.run()
            self.assertEqual(error.exception.category, 'prerequisite')
            self.assertEqual(error.exception.phase, 'retained environment validation')
            self.assertIn('DAGSTER_PROJECT_NAME', str(error.exception))
            self.assertEqual(calls, [])
            self.assertEqual(active.read_text(), 'current')

    def test_service_start_failure_reports_restoration_phase(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            active = root / 'compose.yml'
            active.write_text('current')
            (root / 'compose.pre-infisical.yml').write_text(
                'name: ${DAGSTER_PROJECT_NAME:?required}\nservices: {}\n')
            (root / 'compose.pre-infisical.env').write_text('DAGSTER_PROJECT_NAME=test\n')
            (root / 'compose.pre-infisical-locations.json').write_text('[]\n')
            (root / 'legacy.env').write_text('legacy')
            current = root / 'current-locations.json'
            current.write_text('[]\n')
            workspace = root / 'config/workspace.yaml'
            workspace.parent.mkdir()
            workspace.write_text('load_from: []\n')
            config = root / 'metadata.json'
            config.write_text(json.dumps({'dagster': {
                'compose_file': str(active), 'legacy_env_file': str(root / 'legacy.env'),
                'compose_env_file': str(root / 'current.env')}}))
            def fake_run(argv, **kwargs):
                if 'up' in argv:
                    raise subprocess.CalledProcessError(
                        17, argv, output='secret-value', stderr='secret-value')
                class Result:
                    stdout = 'dagster-user-code\n' if argv[-2:] == ['config', '--services'] else ''
                return Result()
            with patch.object(ROLLBACK, 'CONFIG', config), patch.object(ROLLBACK, 'CURRENT', current), \
                 patch.object(ROLLBACK.os, 'geteuid', return_value=0), \
                 patch.object(ROLLBACK.sys, 'argv', ['rollback', 'dagster']), \
                 patch.object(ROLLBACK.subprocess, 'run', side_effect=fake_run):
                with self.assertRaises(ROLLBACK.RollbackFailure) as error:
                    ROLLBACK.run()
            self.assertEqual(error.exception.category, 'restoration')
            self.assertEqual(error.exception.phase, 'service restoration')
            self.assertIn('status 17', str(error.exception))
            self.assertNotIn('secret-value', str(error.exception))
            self.assertIn('DAGSTER_PROJECT_NAME', active.read_text())


if __name__ == '__main__':
    unittest.main()
