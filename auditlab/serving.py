"""Serving identity checks and sequential stage planning; no model loading here."""
import csv
import io
import json
import re
from pathlib import Path


def snapshot_path(config, model_key, model_root=None):
    if config.get('local_snapshot_path'):
        return Path(config['local_snapshot_path']).expanduser().resolve()
    if not model_root:
        raise ValueError('Managed serving needs --model-root or config.local_snapshot_path')
    return Path(model_root).expanduser().resolve()/model_key/config['revision']


def validate_snapshot(config, snapshot):
    """Validate recorded identity, not the truthfulness of operator provenance."""
    snapshot = Path(snapshot)
    if not (snapshot/'config.json').is_file():
        raise ValueError(f'Model snapshot missing: {snapshot}; supply the installed snapshot path')
    metadata_path = snapshot/'auditlab_snapshot.json'
    if not metadata_path.is_file():
        raise ValueError('Snapshot provenance missing. Independently verify the installed weights before recording identity.')
    metadata = json.loads(metadata_path.read_text())
    fields = ['repository', 'revision', 'precision' if 'precision' in config else 'dtype']
    for field in fields:
        if field not in config or metadata.get(field) != config[field]:
            raise ValueError(f'Snapshot provenance mismatch for {field}; do not relabel different weights')
    local_config = json.loads((snapshot/'config.json').read_text())
    return {'snapshot': str(snapshot), 'recorded_identity': {key: metadata[key] for key in fields},
            'local_model_config': local_config,
            'note': 'Metadata is a provenance assertion, not independent verification of every weight tensor.'}


def validate_external_record(config, path=None):
    if not path:
        if config.get('deployment_status') == 'requires_site_profile':
            raise ValueError('This installed endpoint needs --deployment-record with its verified artifact, '
                             'precision and offload configuration. /v1/models alone cannot establish weight identity.')
        return None
    record = json.loads(Path(path).read_text())
    for field, expected in [('base_repository', config['repository']),
                            ('base_revision', config['revision']), ('precision', config.get('precision'))]:
        if expected is None or record.get(field) != expected:
            raise ValueError(f'Deployment record mismatch for {field}; update the configuration before freezing manifests')
    artifact = record.get('artifact')
    if not isinstance(artifact, dict):
        raise ValueError('Deployment record needs an artifact identity')
    repository_identity = (isinstance(artifact.get('repository'), str) and bool(artifact['repository'].strip())
                           and isinstance(artifact.get('revision'), str)
                           and bool(re.fullmatch('[a-f0-9]{40}', artifact['revision'])))
    manifest_identity = (isinstance(artifact.get('local_manifest_sha256'), str)
                         and bool(re.fullmatch('[a-f0-9]{64}', artifact['local_manifest_sha256'])))
    if not (repository_identity or manifest_identity):
        raise ValueError('Artifact must identify a repository commit or a local file-manifest SHA-256')
    if not isinstance(record.get('offload'), str) or not record['offload'].strip():
        raise ValueError('Deployment record must describe offload, including explicit none')
    launch = record.get('launch_command')
    if not ((isinstance(launch, str) and launch.strip()) or
            (isinstance(launch, list) and launch and all(isinstance(x, str) and x for x in launch))):
        raise ValueError('Deployment record needs the serving launch command')
    if record.get('operator_verified') is not True:
        raise ValueError('The deployment record must be checked by the operator who knows the installed deployment')
    return record


def managed_launch_command(config, snapshot, workers, port):
    if config.get('deployment_status') == 'requires_site_profile':
        raise ValueError('Managed launch is disabled until the site deployment is profiled. '
                         'Use the installed --endpoint with --deployment-record, or explicitly configure '
                         'and record a validated local deployment. No smaller model will be substituted.')
    if workers < 1 or not 1 <= port <= 65535:
        raise ValueError('workers must be positive and port must be valid')
    return ['vllm', 'serve', str(snapshot), '--served-model-name', config['served_name'],
            '--host', '127.0.0.1', '--port', str(port),
            '--tensor-parallel-size', str(config['tensor_parallel_size']),
            '--dtype', config['dtype'], '--max-model-len', str(config['context_length']),
            '--max-num-seqs', str(workers), '--gpu-memory-utilization',
            str(config.get('gpu_memory_utilization', .85)), '--generation-config', 'vllm',
            *config.get('serve_extra', [])]


def stage_destinations(manifest=None, manifests=None, results='results'):
    """A legacy single manifest keeps its root; a campaign gets one root per stage."""
    if bool(manifest) == bool(manifests):
        raise ValueError('Provide exactly one of --manifest or --manifests for run mode')
    root = Path(results).expanduser().resolve()
    if manifest:
        return [(Path(manifest).expanduser().resolve(), root)]
    planned, seen = [], set()
    for item in manifests:
        path = Path(item).expanduser().resolve()
        value = json.loads(path.read_text())
        stage = value.get('stage')
        if not isinstance(stage, str) or not re.fullmatch('[a-zA-Z0-9_-]+', stage):
            raise ValueError(f'Manifest needs a safe stage name: {path}')
        if stage in seen:
            raise ValueError(f'Duplicate stage {stage}; use separate campaign roots')
        seen.add(stage)
        planned.append((path, root/stage))
    return planned


def local_weight_bytes(snapshot):
    snapshot = Path(snapshot)
    index = snapshot/'model.safetensors.index.json'
    if index.is_file():
        names = set(json.loads(index.read_text())['weight_map'].values())
        paths = [snapshot/name for name in names]
    else:
        paths = list(snapshot.glob('*.safetensors'))
    if not paths:
        return None
    return sum(path.stat().st_size for path in paths)


def check_obvious_memory_shortfall(config, snapshot, hardware):
    """Reject a clear all-GPU weight shortfall; success is not a fit guarantee."""
    weight_bytes = local_weight_bytes(snapshot)
    result = {'local_safetensor_bytes': weight_bytes, 'status': 'not_checked',
              'note': 'File sizes are only a coarse weight-memory check; KV cache and runtime overhead need a pilot.'}
    extras = config.get('serve_extra', [])
    changes_placement = any(arg.split('=')[0] in {'--cpu-offload-gb', '--offload-group-size',
                            '--quantization', '-q'} for arg in extras)
    if changes_placement or config.get('offload', 'none') != 'none':
        result['reason'] = 'Explicit quantization/offload requires the site profile; file size is not resident GPU size.'
        return result
    gpu = hardware.get('gpu', {})
    if gpu.get('returncode') != 0 or weight_bytes is None:
        result['reason'] = 'GPU memory or safetensor byte count unavailable.'
        return result
    try:
        rows = list(csv.DictReader(io.StringIO(gpu['stdout'])))
        memory = [float(next(value for key, value in row.items()
                             if key.strip().startswith('memory.total')).strip().split()[0])*(2**20)
                  for row in rows]
        devices = int(config['tensor_parallel_size'])
        if devices < 1 or len(memory) < devices:
            raise ValueError('Requested tensor parallelism exceeds reported GPU count')
        # Largest devices provide a conservative upper bound even when CUDA visibility differs.
        budget = sum(sorted(memory, reverse=True)[:devices])*float(config.get('gpu_memory_utilization', .85))
    except (KeyError, TypeError, StopIteration, ValueError) as exc:
        result['reason'] = 'Could not establish GPU memory bound: '+str(exc)
        return result
    result.update(status='coarse_check_passed', configured_gpu_memory_upper_bound_bytes=int(budget))
    if weight_bytes > budget:
        raise ValueError('Local weight files exceed the configured GPU-memory upper bound before KV cache. '
                         'Sequential loading does not fix this. Configure a verified quantized/offloaded '
                         'deployment or obtain more memory; no automatic model substitution is performed.')
    return result
