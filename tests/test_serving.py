"""Serving controls do not require GPU weights or start a real server."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from auditlab.common import digest
from auditlab.serving import (check_obvious_memory_shortfall, managed_launch_command,
                             snapshot_path, stage_destinations, validate_external_record,
                             validate_snapshot)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = {'id': 'frontier', 'repository': 'author/full-model', 'revision': 'a'*40,
          'precision': 'native_fp8', 'served_name': 'frontier', 'dtype': 'auto',
          'tensor_parallel_size': 4, 'context_length': 65536,
          'deployment_status': 'requires_site_profile', 'serve_extra': []}
RECORD = {'base_repository': CONFIG['repository'], 'base_revision': CONFIG['revision'],
          'precision': CONFIG['precision'], 'artifact': {'repository': CONFIG['repository'], 'revision': CONFIG['revision']},
          'offload': 'none', 'launch_command': ['site-server', 'full-model'], 'operator_verified': True}


def load_wrapper():
    spec = importlib.util.spec_from_file_location('serving_wrapper_test', ROOT/'scripts/serve_and_run.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ServingTests(unittest.TestCase):
    def test_managed_launch_refuses_unprofiled_frontier(self):
        with self.assertRaisesRegex(ValueError, 'No smaller model'):
            managed_launch_command(CONFIG, '/no/weights', 2, 8000)
        command = managed_launch_command({**CONFIG, 'deployment_status': 'site_validated'}, '/weights', 2, 8000)
        self.assertEqual(command[command.index('--max-num-seqs')+1], '2')
        self.assertEqual(command[command.index('--tensor-parallel-size')+1], '4')

    def test_snapshot_override_and_provenance_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve()
            self.assertEqual(snapshot_path({**CONFIG, 'local_snapshot_path': directory}, 'frontier'), path)
            (path/'config.json').write_text('{}')
            (path/'auditlab_snapshot.json').write_text(json.dumps(CONFIG))
            self.assertEqual(validate_snapshot(CONFIG, path)['recorded_identity']['precision'], 'native_fp8')
            for field in ('repository', 'revision', 'precision'):
                with self.subTest(field=field):
                    (path/'auditlab_snapshot.json').write_text(json.dumps({**CONFIG, field: 'other'}))
                    with self.assertRaisesRegex(ValueError, field):
                        validate_snapshot(CONFIG, path)

    def test_external_record_requires_exact_identity_and_artifact(self):
        with self.assertRaisesRegex(ValueError, '--deployment-record'):
            validate_external_record(CONFIG)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'deployment.json'
            path.write_text(json.dumps(RECORD))
            self.assertEqual(validate_external_record(CONFIG, path), RECORD)
            for field, value in [('precision', 'int4'), ('base_revision', 'b'*40),
                                 ('artifact', {}), ('operator_verified', False), ('offload', ''),
                                 ('launch_command', [])]:
                with self.subTest(field=field):
                    path.write_text(json.dumps({**RECORD, field: value}))
                    with self.assertRaises(ValueError):
                        validate_external_record(CONFIG, path)
            local = {**RECORD, 'artifact': {'local_manifest_sha256': 'c'*64}}
            path.write_text(json.dumps(local))
            self.assertEqual(validate_external_record(CONFIG, path), local)

    def test_stage_roots_preserve_legacy_and_reject_duplicate_names(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            first, second = root/'first.json', root/'second.json'
            first.write_text(json.dumps({'stage': 'ste'}))
            second.write_text(json.dumps({'stage': 'duration'}))
            out = root/'results'
            self.assertEqual(stage_destinations(str(first), results=out), [(first, out)])
            self.assertEqual(stage_destinations(manifests=[first, second], results=out),
                             [(first, out/'ste'), (second, out/'duration')])
            with self.assertRaisesRegex(ValueError, 'Duplicate'):
                stage_destinations(manifests=[first, first], results=out)
            second.write_text(json.dumps({'stage': '../other'}))
            with self.assertRaisesRegex(ValueError, 'safe stage'):
                stage_destinations(manifests=[second], results=out)

    def test_obvious_weight_memory_shortfall_does_not_trigger_substitution(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory).resolve()
            (path/'model.safetensors').write_bytes(b'0'*(2**21))
            hardware = {'gpu': {'returncode': 0, 'stdout':
                        'name, memory.total [MiB], uuid, driver_version\nGPU, 1 MiB, id, driver\n'}}
            config = {**CONFIG, 'tensor_parallel_size': 1}
            with self.assertRaisesRegex(ValueError, 'Sequential loading does not fix'):
                check_obvious_memory_shortfall(config, path, hardware)
            value = check_obvious_memory_shortfall({**config, 'serve_extra': ['--cpu-offload-gb', '2']}, path, hardware)
            self.assertEqual(value['status'], 'not_checked')
            self.assertEqual(value['local_safetensor_bytes'], 2**21)

    def _external_campaign(self, returncodes):
        module = load_wrapper()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            models, deployment = root/'models.json', root/'deployment.json'
            models.write_text(json.dumps({'frontier': CONFIG}))
            deployment.write_text(json.dumps(RECORD))
            manifests = []
            for stage in ('ste', 'duration'):
                path = root/(stage+'.json')
                path.write_text(json.dumps({'stage': stage}))
                manifests.append(str(path))
            calls, runs = [], []

            def run(command, **kwargs):
                runs.append(command)
                if 'collect_hardware.py' in command[1]:
                    Path(command[-1]).write_text(json.dumps({'gpu': {'returncode': 1}}))
                return subprocess.CompletedProcess(command, 0)

            class Process:
                def __init__(self, command, **kwargs):
                    self.command = command
                    self.returncode = returncodes[len(calls)]
                    calls.append(command)
                def wait(self, timeout=None):
                    return self.returncode
                def poll(self):
                    return self.returncode

            argv = ['serve_and_run.py', '--models', str(models), '--model', 'frontier',
                    '--endpoint', 'http://installed:8000', '--deployment-record', str(deployment),
                    '--results', str(root/'results'), '--manifests', *manifests, '--wall-seconds', '100']
            with patch.object(sys, 'argv', argv), patch.object(module.subprocess, 'run', side_effect=run), \
                 patch.object(module.subprocess, 'Popen', Process), \
                 patch.object(module.time, 'monotonic', side_effect=[100, 101, 102]), \
                 patch.object(module.signal, 'signal'):
                status = module.main()
            self.assertTrue(all(command[1:3] == ['-m', 'auditlab.cli'] for command in calls))
            preflight = next(command for command in runs if 'preflight' in command)
            effective = Path(preflight[preflight.index('--models')+1])
            effective_config = json.loads(effective.read_text())['frontier']
            self.assertEqual(effective_config['deployment_record_sha256'], digest(RECORD))
            launch = next((root/'results/runtime/frontier').glob('*/launch.json'))
            self.assertFalse(json.loads(launch.read_text())['managed_server'])
            return status, calls

    def test_external_campaign_never_launches_server_and_shares_time_allowance(self):
        status, calls = self._external_campaign([0, 0])
        self.assertEqual(status, 0)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0][calls[0].index('--out')+1].endswith('/ste'))
        self.assertTrue(calls[1][calls[1].index('--out')+1].endswith('/duration'))
        self.assertEqual([float(c[c.index('--wall-seconds')+1]) for c in calls], [99, 98])

    def test_external_campaign_stops_after_failed_stage(self):
        status, calls = self._external_campaign([3])
        self.assertEqual(status, 3)
        self.assertEqual(len(calls), 1)

    def test_capture_refuses_unvalidated_adapter_before_loading_weights(self):
        with tempfile.TemporaryDirectory() as directory:
            index = Path(directory)/'index.json'
            index.write_text(json.dumps([{'model': {**CONFIG, 'capture_supported': False}}]))
            result = subprocess.run([sys.executable, str(ROOT/'scripts/capture_replay.py'),
                        '--index', str(index), '--model', 'frontier', '--model-root', '/no/weights',
                        '--out', str(Path(directory)/'capture')], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Activation capture is disabled', result.stderr)
            self.assertNotIn('ModuleNotFoundError', result.stderr)


if __name__ == '__main__':
    unittest.main()
