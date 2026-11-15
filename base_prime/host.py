"""Download pinned base weights on the GPU node and launch one localhost server."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import subprocess
import sys
from pathlib import Path
from .common import ROOT, config, now, read, write


def command_output(command):
    p = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if p.returncode:
        raise RuntimeError('Command failed: ' + command[0])
    return p.stdout.strip()


def prepare(model, record_dir):
    from huggingface_hub import snapshot_download
    cfg = config()
    m = cfg['models'][model]
    record_dir = Path(record_dir)
    if (record_dir / 'prepared.json').exists():
        old = read(record_dir / 'prepared.json')
        if old['model'] != m or not Path(old['snapshot']).is_dir():
            raise ValueError('prepared_record_changed_or_snapshot_missing')
        print(json.dumps({'snapshot': old['snapshot'], 'reused': True}))
        return old
    # HF's cache resumes partial downloads; use the immutable revision, never main.
    snapshot = Path(snapshot_download(m['repository'], revision=m['revision'],
        allow_patterns=['*.json', '*.safetensors', '*.model', '*.tiktoken', '*.txt']))
    if snapshot.name != m['revision']:
        raise ValueError('snapshot_revision_mismatch')
    weights = [{'path': str(p.relative_to(snapshot)), 'bytes': p.stat().st_size}
               for p in sorted(snapshot.glob('*.safetensors'))]
    if not weights:
        raise ValueError('no_safetensor_weights')
    metadata = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(snapshot.glob('*.json'))}
    record = {'model': m, 'snapshot': str(snapshot), 'created': now(),
              'weight_files': weights, 'metadata_sha256': metadata,
              'provenance': 'Official HF snapshot pinned by repository commit; weight sizes inventoried. No conversion or finetuning.'}
    write(record_dir / 'prepared.json', record)
    print(json.dumps({'snapshot': str(snapshot), 'weight_bytes': sum(p['bytes'] for p in weights)}))
    return record


def serve(model, record_dir, port=8000):
    cfg = config()
    m = cfg['models'][model]
    record_dir = Path(record_dir)
    prepared = read(record_dir / 'prepared.json')
    if prepared['model'] != m or not Path(prepared['snapshot']).is_dir():
        raise ValueError('prepare_model_first')
    if importlib.metadata.version('vllm') != cfg['vllm_version']:
        raise ValueError('install_pinned_vllm_version')
    smi = command_output(['nvidia-smi', '--query-gpu=name,memory.total,driver_version', '--format=csv'])
    cmd = [str(Path(sys.executable).with_name('vllm')), 'serve', prepared['snapshot'],
           '--served-model-name', m['served_name'], '--host', '127.0.0.1', '--port', str(port),
           '--dtype', m['dtype'], '--tensor-parallel-size', '1', '--max-model-len', str(m['max_model_len']),
           '--max-num-seqs', '2', '--max-num-batched-tokens', '2048', '--gpu-memory-utilization', '0.90',
           '--enforce-eager', '--generation-config', 'vllm', '--seed', '20261115']
    packages = {d.metadata['Name']: d.version for d in importlib.metadata.distributions() if d.metadata['Name']}
    deployment = {**m, 'quantization': None, 'adapters': [], 'offload': 'none',
                  'snapshot': prepared['snapshot'], 'weight_files': prepared['weight_files'],
                  'metadata_sha256': prepared['metadata_sha256'], 'launch_command': cmd,
                  'vllm_version': cfg['vllm_version'], 'packages': packages,
                  'gpu': smi, 'python': sys.version,
                  'source_commit': command_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'])}
    destination = record_dir / 'deployment.json'
    if destination.exists() and read(destination) != deployment:
        raise ValueError('deployment_changed_use_new_record_directory_and_cohort')
    write(destination, deployment)
    print(json.dumps({'launch_command': cmd, 'deployment': str(destination)}), flush=True)
    # exec keeps the server owned by tmux/the caller, not by a transient SSH session.
    os.execv(cmd[0], cmd)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('command', choices=['prepare', 'serve'])
    p.add_argument('--model', choices=config()['models'], default='llama8b')
    p.add_argument('--record-dir', type=Path, required=True)
    p.add_argument('--port', type=int, default=8000)
    a = p.parse_args()
    if a.command == 'prepare':
        prepare(a.model, a.record_dir)
    else:
        serve(a.model, a.record_dir, a.port)


if __name__ == '__main__':
    main()
