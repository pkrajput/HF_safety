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
from .backend import HTTPBackend, MockBackend, parse_object
from .common import Journal, digest, now, read_json, write_json
from .design import build_manifest, estimate, validate_manifest
from .runner import run_episode
from .semantic import run_probes
from .world import Case


def get_model(args):
    config = read_json(args.models)[args.model]
    if getattr(args, 'mock', False):
        config = {**config, 'served_name': 'mock', 'id': 'mock', 'family': 'mock', 'revision': 'mock'}
        return config, MockBackend()
    if not re.fullmatch('[a-f0-9]{40}', config['revision']):
        raise ValueError('Pin the model revision first with the pin command')
    return config, HTTPBackend(args.endpoint, config['served_name'])


def main():
    parser = argparse.ArgumentParser(description='Audit Scope Lab; see README.md and docs/PROTOCOL.md')
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('plan')
    p.add_argument('--stage', choices=['pilot', 'core', 'prospective', 'repair', 'compute', 'plain_control'], required=True)
    p.add_argument('--fixtures', type=int)
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
        manifest = build_manifest(args.stage, args.fixtures)
        write_json(args.out, manifest)
        print(json.dumps({'manifest': args.out, 'hash': manifest['design_hash'],
                          'episodes_per_model': len(manifest['cases'])}, indent=2))
    elif args.command == 'estimate':
        if args.measured_output_tps is not None and args.measured_output_tps <= 0:
            parser.error('throughput must be positive')
        print(json.dumps(estimate(read_json(args.manifest), args.model_count,
                                  args.measured_output_tps), indent=2))
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
        messages = [{'role': 'user', 'content': 'Return exactly the JSON object {"ok":true}.'}]
        count = backend.count(messages, config.get('request_extra', {}))
        response = backend.complete({**config.get('request_extra', {}),
                    'model': config['served_name'], 'messages': messages,
                    'temperature': 0, 'max_tokens': 64, 'stream': False})
        choice = response['choices'][0]
        if choice.get('finish_reason') != 'stop' or parse_object(choice['message']['content']) != {'ok': True}:
            raise ValueError('Preflight JSON check failed; inspect template and generation settings')
        if not isinstance(response.get('usage', {}).get('completion_tokens'), int):
            raise ValueError('Preflight usage accounting missing')
        print(json.dumps({'prompt_tokens_counted': count, 'response': response}, indent=2))
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
            parser.error('GLM is reserved for auditing; choose a target model')
        if args.workers < 1 or args.wall_seconds <= 0 or (args.limit is not None and args.limit < 1):
            parser.error('workers, wall-seconds and limit must be positive')
        manifest = read_json(args.manifest)
        validate_manifest(manifest)
        root = Path(args.out)
        root.mkdir(parents=True, exist_ok=True)
        manifest_copy = root/'manifest.json'
        if manifest_copy.exists() and read_json(manifest_copy)['design_hash'] != manifest['design_hash']:
            raise ValueError('Output directory already belongs to another manifest')
        write_json(manifest_copy, manifest)
        selected = manifest['cases'][:args.limit]
        deadline = time.monotonic()+args.wall_seconds
        started = time.monotonic()
        counts = {'complete': 0, 'paused': 0, 'error': 0, 'previous_error': 0}

        def work(row):
            dest = root/config['id']/Case(**row).id
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
                result = run_episode(row, config, backend, dest, deadline)
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
        write_json(args.out, summarize(args.results))
        print(f'Summary saved to {args.out}')
    elif args.command == 'verify':
        paths = list(Path(args.results).rglob('events.jsonl'))
        for path in paths:
            rows = Journal.verify(path)
            result_path = path.parent/'result.json'
            if result_path.exists() and read_json(result_path)['journal_root'] != rows[-1]['hash']:
                raise ValueError(f'Final journal root mismatch: {path}')
        print(f'Verified {len(paths)} observer journals.')
    elif args.command == 'replay-index':
        entries = []
        for path in sorted(Path(args.results).rglob('events.jsonl')):
            rows = Journal.verify(path)
            start = next(row['data'] for row in rows if row['kind'] == 'episode_start')
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
