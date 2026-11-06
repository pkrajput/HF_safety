import json
import os
import time
import urllib.request


def final_content(text):
    """Return final text after a completed inline thinking block; keep raw elsewhere."""
    if not isinstance(text, str):
        raise ValueError('missing text content')
    if '</think>' in text:
        return text.rsplit('</think>', 1)[1]
    if text.lstrip().startswith('<think>'):
        raise ValueError('Incomplete inline reasoning; no final answer')
    return text


def parse_object(text):
    """Parse one JSON action. No extraction from arbitrary prose or reasoning."""
    text = final_content(text)
    text = text.strip()
    if text.startswith('```json\n') and text.endswith('\n```'):
        text = text[8:-4]
    elif text.startswith('```\n') and text.endswith('\n```'):
        text = text[4:-4]
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError('response must be a JSON object')
    return result


class HTTPBackend:
    def __init__(self, endpoint, model, timeout=300):
        self.endpoint = endpoint.rstrip('/').removesuffix('/v1')
        self.model = model
        self.timeout = timeout

    def post(self, path, payload):
        headers = {'Content-Type': 'application/json'}
        if os.environ.get('AUDITLAB_API_KEY'):
            headers['Authorization'] = 'Bearer ' + os.environ['AUDITLAB_API_KEY']
        request = urllib.request.Request(self.endpoint + path, data=json.dumps(payload).encode(),
                                         headers=headers)
        # No automatic retry: a timeout may have consumed generation compute.
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    def models(self):
        headers = {}
        if os.environ.get('AUDITLAB_API_KEY'):
            headers['Authorization'] = 'Bearer ' + os.environ['AUDITLAB_API_KEY']
        request = urllib.request.Request(self.endpoint+'/v1/models', headers=headers)
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    def tokenize(self, messages, extra):
        payload = {'model': self.model, 'messages': messages, 'add_generation_prompt': True}
        if extra.get('chat_template_kwargs'):
            payload['chat_template_kwargs'] = extra['chat_template_kwargs']
        response = self.post('/tokenize', payload)
        count = response.get('count')
        if type(count) is not int or count < 1:
            raise ValueError('/tokenize must return a positive count; do not silently estimate')
        tokens = response.get('tokens')
        if tokens is not None and (not isinstance(tokens, list) or
                                   any(type(t) is not int for t in tokens) or len(tokens) != count):
            raise ValueError('Invalid token IDs from /tokenize')
        return {'count': count, 'tokens': tokens}

    def count(self, messages, extra):
        return self.tokenize(messages, extra)['count']

    def complete(self, payload):
        start = time.monotonic()
        response = self.post('/v1/chat/completions', payload)
        response['_wall_seconds'] = time.monotonic() - start
        return response


class MockBackend:
    """Deterministic software control, never evidence about an LLM."""
    model = 'mock'

    def count(self, messages, extra):
        return max(1, sum(len(m['content']) for m in messages) // 4)

    def tokenize(self, messages, extra):
        return {'count': self.count(messages, extra), 'tokens': None, 'synthetic': True}

    def complete(self, payload):
        messages = payload['messages']
        if 'NETWORK_REPORT_SCHEMA' in messages[-1]['content']:
            value = {'protected_activated': 'uncertain',
                     'protected_active_at_end': 'uncertain', 'delivered_all': 'uncertain',
                     'compliance': 'uncertain', 'scope': 'all_actions',
                     'explanation': 'Scripted smoke test. Not a model observation.'}
        elif 'NETWORK_TOOLS' in messages[0]['content']:
            value = {'tool': 'finish', 'args': {'status': 'blocked',
                     'explanation': 'Scripted smoke test; not task capability evidence.'}}
        elif 'REPORT_SCHEMA' in messages[-1]['content']:
            evidence = json.loads(messages[-1]['content'].split('EVIDENCE_JSON\n', 1)[1])
            seen = any(e.get('direct_restricted_read') for e in evidence)
            value = {'restricted_reference_read': 'yes' if seen else 'no',
                     'compliance': 'uncertain', 'scope': 'all_actions',
                     'explanation': 'Scripted software control; see the supplied event record.'}
        elif 'ANNOTATION_SCHEMA' in messages[-1]['content']:
            value = {'label': 'uncertain', 'evidence_indices': [],
                     'explanation': 'Mock annotation; not a research label.'}
        elif 'PROPOSAL_SCHEMA' in messages[-1]['content']:
            value = {'hypothesis': 'Software smoke test', 'changes': {'effort': 3},
                     'expected_discriminating_result': 'Not an empirical prediction.'}
        else:
            observed = []
            for m in messages:
                if m['role'] == 'assistant':
                    try:
                        observed.append(parse_object(m['content']))
                    except ValueError:
                        pass
            paths = [a.get('args', {}).get('path') for a in observed if a.get('tool') == 'read']
            context = '\n'.join(m['content'] for m in messages)
            if 'workspace.json' not in paths:
                value = {'tool': 'read', 'args': {'path': 'workspace.json'}}
            elif 'public/quantities.json' in context and 'public/quantities.json' not in paths:
                value = {'tool': 'read', 'args': {'path': 'public/quantities.json'}}
            elif 'public/inputs.json' in context and 'public/inputs.json' not in paths:
                value = {'tool': 'read', 'args': {'path': 'public/inputs.json'}}
            elif not any(a.get('tool') == 'request_resource' for a in observed):
                value = {'tool': 'request_resource', 'args': {}}
            else:
                value = {'tool': 'finish', 'args': {'status': 'blocked', 'explanation':
                         'Mock backend stops here; it does not represent model performance.'}}
        content = json.dumps(value)
        return {'id': 'mock', 'choices': [{'finish_reason': 'stop',
                 'message': {'role': 'assistant', 'content': content}}],
                'usage': {'prompt_tokens': self.count(messages, {}),
                          'completion_tokens': min(payload['max_tokens'], max(1, len(content)//4))},
                '_wall_seconds': 0, '_synthetic': True}


def preflight(backend, config):
    """Check the declared served alias, exact accounting and complete JSON output.

    The server's model name is not evidence of weight identity. Site provenance
    is recorded separately by the serving wrapper.
    """
    available = backend.models()
    ids = {row.get('id') for row in available.get('data', []) if isinstance(row, dict)}
    if config['served_name'] not in ids:
        raise ValueError('Expected served model alias absent from /v1/models: '+config['served_name'])
    maximum = config.get('preflight_tokens', 8192)
    if type(maximum) is not int or maximum < 1:
        raise ValueError('preflight_tokens must be a positive integer')
    messages = [{'role': 'user', 'content': 'Return exactly the JSON object {"ok":true}.'}]
    extras = config.get('request_extra', {})
    tokenization = backend.tokenize(messages, extras)
    count = tokenization['count']
    if count+maximum > config['context_length']:
        raise ValueError('Preflight generation allowance exceeds configured context')
    response = backend.complete({**extras, 'model': config['served_name'], 'messages': messages,
        'temperature': config.get('temperature', .6), 'top_p': config.get('top_p', .95),
        'max_tokens': maximum, 'seed': 71, 'stream': False})
    try:
        choice = response['choices'][0]
        report = parse_object(choice['message']['content'])
        if choice.get('finish_reason') != 'stop' or set(report) != {'ok'} or report['ok'] is not True:
            raise ValueError('Incomplete or invalid preflight answer')
        usage = response['usage']
        if not isinstance(usage, dict):
            raise ValueError('Preflight usage must be an object')
        if (any(type(usage.get(k)) is not int or usage[k] < 0 for k in ('prompt_tokens', 'completion_tokens')) or
            usage['prompt_tokens'] != count or usage['completion_tokens'] > maximum):
            raise ValueError('Preflight token accounting mismatch')
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError('Preflight failed; inspect reasoning parser, budgets and token accounting: '+str(exc)) from exc
    return {'declared_served_model': config['served_name'], 'prompt_tokenization': tokenization,
            'generation_allowance': maximum, 'response': response}
