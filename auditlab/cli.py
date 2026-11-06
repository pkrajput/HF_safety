import argparse
import concurrent.futures
import json
import os
import re
import time
import urllib.request
from pathlib import Path

from .analysis import summarize
from .auditor import audit_reports, propose_development
from .backend import HTTPBackend, MockBackend, parse_object, preflight
from .common import Journal, digest, now, read_json, write_json
from .design import build_manifest, estimate, validate_manifest
from .runner import run_episode
from .semantic import run_probes
from .world import Case
from .network import NetworkCase
from .network_design import STAGES, build_network_manifest, validate_network_manifest, estimate_network
from .network_runner import run_network_episode


def get_model(args):
    config = read_json(args.models)[args.model]
    if getattr(args, 'mock', False):
        config = {**config, 'served_name': 'mock', 'id': 'mock', 'family': 'mock', 'revision': 'mock'}
        return config, MockBackend()
    if not re.fullmatch('[a-f0-9]{40}', config['revision']):
        raise ValueError('Pin the model revision first with the pin command')
    return config, HTTPBackend(args.endpoint, config['served_name'],
                               timeout=config.get('request_timeout_seconds', 300))


def main():
    parser = argparse.ArgumentParser(description='Audit Scope Lab; see README.md and docs/PROTOCOL.md')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--stage', choices=[*STAGES, 'pilot', 'core', 'prospective', 'repair', 'compute', 'plain_control'], required=True)
    p.add_argument('--fixtures', type=int)
    p.add_argument('--team-sizes', type=int, nargs='+', choices=[1, 4])
    p.add_argument('--repetitions', type=int, default=1)
    p.add_argument('--budget-profile', choices=['standard', 'frontier'], default='standard')
    p.add_argument('--out', required=True)
    p = sub.add_parser('estimate')
    p.add_argument('--manifest', required=True)
    p.add_argument('--model-count', type=int, default=3)
    p.add_argument('--measured-output-tps', type=float)
    p = sub.add_parser('pin')
    p.add_argument('--models', default='configs/models.json')
    p.add_argument('--out', default='configs/models.lock.json')
    for cmd in ('run', 'audit', 'propose', 'semantic'):
        p = sub.add_parser(cmd)
        p.add_argument('--models', default='configs/models.lock.json')
        p.add_argument('--model', required=True)
        p.add_argument('--endpoint', default='http://127.0.0.1:8000')
        p.add_argument('--mock', action='store_true')
        p.add_argument('--out', required=True)
        if cmd == 'run':
            p.add_argument('--manifest', required=True)
            p.add_argument('--workers', type=int, default=2)
            p.add_argument('--limit', type=int)
            p.add_argument('--wall-seconds', type=float, default=21600)
        elif cmd == 'audit':
            p.add_argument('--results', required=True)
            p.add_argument('--limit', type=int, default=100)
        elif cmd == 'semantic':
            p.add_argument('--fixtures', type=int, default=3)
            p.add_argument('--limit', type=int)
    p = sub.add_parser('analyze')
    p.add_argument('--results', required=True)
    p.add_argument('--out', required=True)
    p = sub.add_parser('verify')
    p.add_argument('--results', required=True)
    p = sub.add_parser('replay-index')
    p.add_argument('--results', required=True)
    p.add_argument('--out', required=True)
    p = sub.add_parser('preflight')
    p.add_argument('--models', default='configs/models.lock.json')
    p.add_argument('--model', required=True)
    p.add_argument('--endpoint', default='http://127.0.0.1:8000')
    args = parser.parse_args()
    if args.command == 'plan':
        if args.fixtures is not None and args.fixtures < 1:
            parser.error('--fixtures must be positive')
        if args.stage not in STAGES and (args.team_sizes or args.repetitions != 1 or args.budget_profile != 'standard'):
            parser.error('Team sizes, repetitions and budget profiles apply to network stages only')
        manifest = (build_network_manifest(args.stage, args.fixtures or 6,
                    team_sizes=args.team_sizes, repetitions=args.repetitions, budget_profile=args.budget_profile)
                    if args.stage in STAGES else build_manifest(args.stage, args.fixtures))
        write_json(args.out, manifest)
        print(json.dumps({'manifest': args.out, 'hash': manifest['design_hash'],
                          'episodes_per_model': len(manifest['cases']),
                          **(estimate_network(manifest, models=1) if args.stage in STAGES else {})}, indent=2))
    elif args.command == 'estimate':
        if args.model_count < 1:
            parser.error('--model-count must be positive')
        if args.measured_output_tps is not None and args.measured_output_tps <= 0:
            parser.error('throughput must be positive')
        manifest = read_json(args.manifest)
        value = (estimate_network(manifest, args.model_count) if manifest.get('kind') == 'network-v2' else
                 estimate(manifest, args.model_count, args.measured_output_tps))
        print(json.dumps(value, indent=2))
    elif args.command == 'pin':
        models = read_json(args.models)
        for config in models.values():
            url = 'https://huggingface.co/api/models/' + config['repository']
            with urllib.request.urlopen(url, timeout=30) as response:
                info = json.load(response)
            revision = info['sha']
            if not re.fullmatch('[a-f0-9]{40}', revision):
                raise ValueError('Invalid repository revision')
            config['revision'] = revision
            config['pinned_at'] = now()
        write_json(args.out, models)
        print(f'Pinned {len(models)} model repositories in {args.out}; no weights downloaded.')
    elif args.command == 'preflight':
        config, backend = get_model(args)
        print(json.dumps(preflight(backend, config), indent=2))
    elif args.command in ('run', 'audit', 'propose', 'semantic'):
        config, backend = get_model(args)
        if args.command == 'semantic':
            print(json.dumps({'probes_written': run_probes(backend, config, args.out, args.fixtures, args.limit)}))
            return
        if args.command in ('audit', 'propose') and config['role'] != 'auditor':
            parser.error('Use a model assigned to the auditor role')
        if args.command == 'audit':
            print(json.dumps({'annotations_written': audit_reports(args.results, backend, config,
                                                                    args.out, args.limit)}))
            return
        if args.command == 'propose':
            propose_development(backend, config, args.out)
            print('Development proposal saved; no experiment was modified.')
            return
        if config['role'] != 'target':
            parser.error('This model is reserved for auditing; choose a target model')
        if args.workers < 1 or args.wall_seconds <= 0 or (args.limit is not None and args.limit < 1):
            parser.error('workers, wall-seconds and limit must be positive')
        manifest = read_json(args.manifest)
        network = manifest.get('kind') == 'network-v2'
        (validate_network_manifest if network else validate_manifest)(manifest)
        root = Path(args.out)
        root.mkdir(parents=True, exist_ok=True)
        manifest_copy = root/'manifest.json'
        if manifest_copy.exists() and read_json(manifest_copy)['design_hash'] != manifest['design_hash']:
            raise ValueError('Output directory already belongs to another manifest')
        write_json(manifest_copy, manifest)
        if network:
            model_path = root/'models'/(config['id']+'.json')
            if model_path.exists() and read_json(model_path) != config:
                raise ValueError('Model configuration changed within a collection')
            write_json(model_path, config)
        selected = manifest['cases'][:args.limit]
        deadline = time.monotonic()+args.wall_seconds
        started = time.monotonic()
        counts = {'complete': 0, 'paused': 0, 'error': 0, 'previous_error': 0}

        def work(row):
            dest = root/config['id']/(NetworkCase(**row).id if network else Case(**row).id)
            if (dest/'error.json').exists():
                return 'previous_error'
            # One process should own a campaign/model. Avoid duplicate writers across invocations.
            dest.mkdir(parents=True, exist_ok=True)
            claim = dest/'writer.lock'
            try:
                fd = os.open(claim, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                raise RuntimeError(f'Another writer or an interrupted process owns {dest}; inspect before removing writer.lock')
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            try:
                result = (run_network_episode(row, config, backend, dest, manifest['experiment'], deadline)
                          if network else run_episode(row, config, backend, dest, deadline))
                return 'complete' if result.get('status') == 'complete' else 'paused'
            except Exception as exc:
                write_json(dest/'error.json', {'time': now(), 'case': row, 'model': config,
                                              'type': type(exc).__name__, 'message': str(exc)})
                return 'error'
            finally:
                claim.unlink(missing_ok=True)

        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(work, row) for row in selected]
            for future in concurrent.futures.as_completed(futures):
                counts[future.result()] += 1
        print(json.dumps({'counts': counts, 'wall_seconds': time.monotonic()-started,
                          'synthetic': args.mock, 'output': str(root)}, indent=2))
        if counts['error'] or counts['previous_error']:
            raise SystemExit(2)
    elif args.command == 'analyze':
        manifest_path = Path(args.results)/'manifest.json'
        if manifest_path.exists() and read_json(manifest_path).get('kind') == 'network-v2':
            from .network_analysis import summarize_network
            summary = summarize_network(args.results)
        else:
            summary = summarize(args.results)
        write_json(args.out, summary)
        print(f'Summary saved to {args.out}')
    elif args.command == 'verify':
        paths = list(Path(args.results).rglob('events.jsonl'))
        for path in paths:
            rows = Journal.verify(path)
            result_path = path.parent/'result.json'
            if result_path.exists():
                result = read_json(result_path)
                if result.get('kind') == 'network-v2':
                    if result.get('result_hash') != digest({k:v for k,v in result.items() if k!='result_hash'}):
                        raise ValueError(f'Result hash mismatch: {path}')
                    from .network_runner import RequestStore
                    store = RequestStore(path.parent, None, {})
                    for artifact in list((path.parent/'requests').glob('*.json'))+list((path.parent/'units').glob('*.json')):
                        store.load(str(artifact.relative_to(path.parent)))
                    if (path.parent/'checkpoint.json').exists():
                        store.load('checkpoint.json')
                if result.get('status') == 'complete' and result['journal_root'] != rows[-1]['hash']:
                    raise ValueError(f'Final journal root mismatch: {path}')
        print(f'Verified {len(paths)} observer journals.')
    elif args.command == 'replay-index':
        entries = []
        for path in sorted(Path(args.results).rglob('events.jsonl')):
            rows = Journal.verify(path)
            start = next(row['data'] for row in rows if row['kind'] == 'episode_start')
            if start.get('kind') == 'network-v2':
                for row in rows:
                    if row['kind'] != 'network_request' or row['data']['metadata']['phase'] != 'reporting':
                        continue
                    request = row['data']
                    entries.append({'id': digest([start['identity'], request['key']]),
                                    'model': start['model'], 'case': start['case'],
                                    'branch': request['metadata']['branch'],
                                    'checkpoint_id': request['metadata']['checkpoint_id'],
                                    'request': request['payload'],
                                    'serving_token_ids': request['tokenization'].get('tokens'),
                                    'serving_token_count': request['tokenization']['count'],
                                    'source_journal': str(path.resolve())})
                continue
            pending = None
            for row in rows:
                if row['kind'] == 'request' and row['data']['phase'] == 'reporting':
                    pending = row['data']['payload']
                elif row['kind'] == 'report' and pending:
                    entries.append({'id': digest([start['identity'], row['data']['audit']]),
                                    'model': start['model'], 'case': start['case'],
                                    'audit': row['data']['audit'], 'request': pending,
                                    'report': row['data']['report'],
                                    'source_journal': str(path.resolve())})
                    pending = None
        write_json(args.out, entries)
        print(f'Saved {len(entries)} reporting contexts; these are replay inputs, not activations.')


if __name__ == '__main__':
    main()
