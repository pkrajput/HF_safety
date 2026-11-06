#!/usr/bin/env python3
"""One resident model, sequential study stages, bounded concurrent isolated teams."""
import argparse
from datetime import datetime, timezone
import json
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from auditlab.common import digest
from auditlab.serving import (check_obvious_memory_shortfall, managed_launch_command,
                             snapshot_path, stage_destinations, validate_external_record,
                             validate_snapshot)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models', default='configs/models.lock.json')
    parser.add_argument('--model', required=True)
    parser.add_argument('--model-root')
    parser.add_argument('--endpoint', help='Attach to an existing server; never launch or stop it')
    parser.add_argument('--deployment-record', help='Operator-verified installed deployment JSON')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--manifest')
    group.add_argument('--manifests', nargs='+', help='Run stages sequentially while this model stays resident')
    parser.add_argument('--results', required=True)
    parser.add_argument('--mode', choices=['run', 'audit', 'propose', 'semantic'], default='run')
    parser.add_argument('--out')
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--wall-seconds', type=int, default=18000,
                        help='Request-start allowance shared by all stages in this invocation')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    if args.workers < 1 or args.wall_seconds < 1 or (args.limit is not None and args.limit < 1):
        parser.error('workers, wall-seconds and limit must be positive')
    if args.mode != 'run' and (args.manifest or args.manifests):
        parser.error('Manifest arguments are only supported in run mode')
    args.models = str(Path(args.models).expanduser().resolve())
    args.results = str(Path(args.results).expanduser().resolve())
    if args.out:
        args.out = str(Path(args.out).expanduser().resolve())
    model_configs = json.loads(Path(args.models).read_text())
    config = model_configs[args.model]
    stages = (stage_destinations(args.manifest, args.manifests, args.results)
              if args.mode == 'run' else [(None, Path(args.results))])
    external = bool(args.endpoint)
    record = validate_external_record(config, args.deployment_record) if external else None
    provenance, memory_check, command = None, None, None
    if not external:
        snapshot = snapshot_path(config, args.model, args.model_root)
        # Refuse unresolved site profiles before inspecting or loading any snapshot.
        command = managed_launch_command(config, snapshot, args.workers, args.port)
        provenance = validate_snapshot(config, snapshot)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
    artifacts = Path(args.results)/'runtime'/args.model/stamp
    artifacts.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(ROOT/'scripts/collect_hardware.py'),
                    str(artifacts/'hardware.json')], check=True)
    hardware = json.loads((artifacts/'hardware.json').read_text())
    if not external:
        memory_check = check_obvious_memory_shortfall(config, snapshot, hardware)
    endpoint = args.endpoint.rstrip('/') if external else f'http://127.0.0.1:{args.port}'
    launch = {'argv': command, 'model': config, 'endpoint': endpoint, 'managed_server': not external,
              'stages': [{'manifest': str(manifest) if manifest else None, 'results': str(destination)}
                         for manifest, destination in stages],
              'workers': args.workers, 'wall_seconds': args.wall_seconds,
              'snapshot_provenance': provenance, 'memory_check': memory_check,
              'external_deployment_record': record,
              'hardware_scope': 'client machine only; server identity is operator-recorded' if external else 'managed server machine',
              'provenance_note': 'An operator deployment record is an assertion, not independent attestation of remote weights.'}
    (artifacts/'launch.json').write_text(json.dumps(launch, indent=2)+'\n')
    effective_models = args.models
    if record is not None:
        # Bind the recorded serving artifact/precision/offload to episode identity.
        model_configs[args.model] = {**config, 'deployment_record_sha256': digest(record)}
        effective_models = str(artifacts/'effective_models.json')
        Path(effective_models).write_text(json.dumps(model_configs, indent=2)+'\n')
    server, client, log = None, None, None

    def stop(signum=None, frame=None):
        if client is not None and client.poll() is None:
            client.terminate()
        if server is not None and server.poll() is None:
            os.killpg(server.pid, signal.SIGTERM)

    previous_handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        if not external:
            log = (artifacts/'server.log').open('a')
            server = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            deadline = time.monotonic()+1800
            while time.monotonic() < deadline:
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
        subprocess.run([sys.executable, '-m', 'auditlab.cli', 'preflight', '--models', effective_models,
                        '--model', args.model, '--endpoint', endpoint], cwd=ROOT, check=True)
        collection_deadline = time.monotonic()+args.wall_seconds
        completed = []
        for manifest, destination in stages:
            remaining = collection_deadline-time.monotonic()
            if remaining <= 0:
                raise RuntimeError('Campaign request-start allowance exhausted; remaining stages were not launched')
            cli = [sys.executable, '-m', 'auditlab.cli', args.mode, '--models', effective_models,
                   '--model', args.model, '--endpoint', endpoint]
            if args.mode == 'run':
                cli += ['--manifest', str(manifest), '--out', str(destination), '--workers', str(args.workers),
                        '--wall-seconds', str(remaining)]
            elif args.mode == 'audit':
                cli += ['--results', str(destination), '--out', args.out or str(destination/'annotations')]
            elif args.mode == 'semantic':
                cli += ['--out', args.out or str(destination/'semantic'/args.model)]
            else:
                cli += ['--out', args.out or str(destination/'development_proposal.json')]
            if args.limit is not None and args.mode != 'propose':
                cli += ['--limit', str(args.limit)]
            client = subprocess.Popen(cli, cwd=ROOT)
            returncode = client.wait()
            completed.append({'argv': cli, 'returncode': returncode})
            (artifacts/'stage_runs.json').write_text(json.dumps(completed, indent=2)+'\n')
            if returncode != 0:
                return returncode
        return 0
    finally:
        stop()
        if client is not None and client.poll() is None:
            try:
                client.wait(timeout=30)
            except subprocess.TimeoutExpired:
                client.kill()
                client.wait()
        if server is not None:
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                os.killpg(server.pid, signal.SIGKILL)
                server.wait()
        if log is not None:
            log.close()
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    raise SystemExit(main())
