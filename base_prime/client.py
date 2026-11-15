"""Journaled localhost vLLM completions. No resending uncertain generation calls."""
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from .common import now, read, sha, write


class CompletionClient:
    def __init__(self, root, endpoint, manifest, deadline):
        self.root = Path(root)
        self.endpoint = endpoint.rstrip('/')
        self.manifest = manifest
        self.deadline = deadline

    def request(self, path, body=None, timeout=120):
        headers = {'Content-Type': 'application/json'}
        if os.environ.get('VLLM_API_KEY'):
            headers['Authorization'] = 'Bearer ' + os.environ['VLLM_API_KEY']
        import json
        request = urllib.request.Request(self.endpoint + path, headers=headers,
                                         data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    def call(self, prompt, key, seed):
        m = self.manifest
        path = self.root / 'requests' / (key + '.json')
        identity = sha({'manifest': m['hash'], 'prompt': prompt, 'seed': seed})
        if path.exists():
            cached = read(path)
            if cached['identity'] != identity:
                raise RuntimeError('request_identity_changed')
            if cached['status'] != 'complete':
                raise RuntimeError('prior_request_unresolved_or_failed_no_retry')
            return cached
        remaining = self.deadline - time.monotonic()
        if remaining < 5:
            raise TimeoutError('wall_budget_reached_before_request')
        record = {'identity': identity, 'status': 'tokenizing', 'created': now(), 'prompt': prompt}
        write(path, record)
        try:
            tokens = self.request('/tokenize', {'model': m['model']['served_name'], 'prompt': prompt,
                                              'add_special_tokens': True}, timeout=min(60, remaining))
            record['tokenization'] = tokens
            count = tokens['count']
            if type(count) is not int or count != len(tokens['tokens']):
                raise ValueError('invalid_tokenization_response')
            if count + m['max_output_tokens'] > min(tokens['max_model_len'], m['model']['max_model_len']):
                raise ValueError('context_limit_no_truncation')
            body = {'model': m['model']['served_name'], 'prompt': tokens['tokens'],
                    'max_tokens': m['max_output_tokens'], 'temperature': m['temperature'],
                    'top_p': m['top_p'], 'seed': seed, 'stop': m['stop'], 'stream': False,
                    'n': 1, 'echo': False}
            record.update(status='pending_generation', body=body)
            write(path, record)  # Persist before crossing the generation boundary.
            remaining = self.deadline - time.monotonic()
            if remaining < 5:
                raise TimeoutError('wall_budget_reached_before_generation')
            raw = self.request('/v1/completions', body, timeout=min(300, remaining))
            record.update(raw=raw, received=now())
            write(path, record)  # Preserve even an invalid response before validating it.
            choices = raw['choices']
            if len(choices) != 1 or not isinstance(choices[0].get('text'), str):
                raise ValueError('invalid_completion_response')
            if raw.get('usage', {}).get('prompt_tokens') != count:
                raise ValueError('prompt_token_count_mismatch')
            record.update(status='complete', text=choices[0]['text'],
                          finish_reason=choices[0]['finish_reason'], usage=raw.get('usage'))
        except Exception as error:
            # Do not serialize request headers, environment, or exceptions containing URLs/tokens.
            record.update(status='failed_no_retry', error_type=type(error).__name__,
                          error_code=str(error) if isinstance(error, (ValueError, TimeoutError)) else 'transport_or_response_error',
                          ended=now())
            write(path, record)
            raise RuntimeError(record['error_code']) from None
        write(path, record)
        return record
