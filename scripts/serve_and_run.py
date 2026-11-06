#!/usr/bin/env python3
"""One model per node. A local inference server plus concurrent isolated episodes."""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('--models', default='configs/models.lock.json')
parser.add_argument('--model', required=True)
parser.add_argument('--model-root', required=True)
parser.add_argument('--manifest')
parser.add_argument('--results', required=True)
parser.add_argument('--mode', choices=['run', 'audit', 'propose', 'semantic'], default='run')
parser.add_argument('--out')
parser.add_argument('--workers', type=int, default=4)
parser.add_argument('--wall-seconds', type=int, default=18000)
parser.add_argument('--limit', type=int)
parser.add_argument('--port', type=int, default=8000)
args = parser.parse_args()
config = json.loads(Path(args.models).read_text())[args.model]
snapshot = Path(args.model_root)/args.model/config['revision']
if not (snapshot/'config.json').exists():
    raise SystemExit(f'Model snapshot missing: {snapshot}; see docs/CLUSTER.md for existing-weight setup')
metadata = snapshot/'auditlab_snapshot.json'
if not metadata.exists() or json.loads(metadata.read_text())['revision'] != config['revision']:
    raise SystemExit('Snapshot provenance missing/mismatched. Verify existing weights as described in CLUSTER.md.')
artifacts = Path(args.results)/'runtime'/args.model
artifacts.mkdir(parents=True, exist_ok=True)
subprocess.run([sys.executable, 'scripts/collect_hardware.py', str(artifacts/'hardware.json')], check=True)
command = ['vllm', 'serve', str(snapshot), '--served-model-name', config['served_name'],
           '--host', '127.0.0.1', '--port', str(args.port),
           '--tensor-parallel-size', str(config['tensor_parallel_size']),
           '--dtype', config['dtype'], '--max-model-len', str(config['context_length']),
           '--max-num-seqs', str(max(8, args.workers*2)), '--gpu-memory-utilization', '0.85',
           '--generation-config', 'vllm', *config.get('serve_extra', [])]
(artifacts/'launch.json').write_text(json.dumps({'argv': command, 'model': config}, indent=2)+'\n')
log = (artifacts/'server.log').open('a')
server = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
client = None


def stop(signum=None, frame=None):
    if client is not None and client.poll() is None:
        client.terminate()
    if server.poll() is None:
        os.killpg(server.pid, signal.SIGTERM)


signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
try:
    endpoint = f'http://127.0.0.1:{args.port}'
    deadline = time.monotonic()+1800
    while time.monotonic()<deadline:
        if server.poll() is not None:
            raise RuntimeError(f'Server exited; inspect {artifacts / "server.log"}')
        try:
            with urllib.request.urlopen(endpoint+'/health', timeout=2) as response:
                if response.status == 200:
                    break
        except OSError:
            time.sleep(3)
    else:
        raise TimeoutError('Server did not become healthy within 30 minutes')
    subprocess.run([sys.executable, '-m', 'auditlab.cli', 'preflight', '--models', args.models,
                    '--model', args.model, '--endpoint', endpoint], check=True)
    cli = [sys.executable, '-m', 'auditlab.cli', args.mode, '--models', args.models,
           '--model', args.model, '--endpoint', endpoint]
    if args.mode == 'run':
        if not args.manifest:
            raise ValueError('--manifest is required for run')
        cli += ['--manifest', args.manifest, '--out', args.results, '--workers', str(args.workers),
                '--wall-seconds', str(args.wall_seconds)]
    elif args.mode == 'audit':
        cli += ['--results', args.results, '--out', args.out or str(Path(args.results)/'annotations')]
    elif args.mode == 'semantic':
        cli += ['--out', args.out or str(Path(args.results)/'semantic'/args.model)]
    else:
        cli += ['--out', args.out or str(Path(args.results)/'development_proposal.json')]
    if args.limit and args.mode != 'propose':
        cli += ['--limit', str(args.limit)]
    client = subprocess.Popen(cli)
    raise SystemExit(client.wait())
finally:
    stop()
    try:
        server.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(server.pid, signal.SIGKILL)
        server.wait()
    log.close()
