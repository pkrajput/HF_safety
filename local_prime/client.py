"""Small native Gemini/OpenRouter client with persistent, shared spend reservations.

No provider credentials enter saved artifacts. Unknown-cost requests keep their
reservation and stop collection until an operator reconciles the ledger. Stored
responses are reused only for exactly identical requests; inference is never
retried automatically. Dollar limits use configured (preflight-verified) prices,
not a promise about a provider's final invoice.
"""
from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class ClientError(RuntimeError):
    pass


class BudgetError(ClientError):
    pass


def stamp():
    return datetime.now(timezone.utc).isoformat()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def sha(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + '\n')
    temporary.replace(path)


def load_keys(keysfile=None):
    """Read only named API-key values; do not execute an env file."""
    names = ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'OPENROUTER_API_KEY')
    values = {}
    path = Path(keysfile).expanduser() if keysfile else Path.home()/'.config/hf-safety/keys.env'
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line.startswith('export '):
                line = line[7:].strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, value = line.split('=', 1)
            key, value = key.strip(), value.strip()
            if key in names:
                if len(value) >= 2 and value[0] == value[-1] and value[0] in '\"\'':
                    value = value[1:-1]
                if value:
                    values[key] = value
    for name in names:
        if os.environ.get(name):
            values[name] = os.environ[name]
    return values


def redact(value, secrets=()):
    """Redact echoed credentials from errors/responses as well as known patterns."""
    if isinstance(value, dict):
        return {key: ('[REDACTED]' if key.lower() in
                      ('authorization', 'x-goog-api-key', 'api_key', 'apikey')
                      else redact(item, secrets)) for key, item in value.items()}
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, '[REDACTED]')
        return re.sub(r'(?:AIza[\w-]{20,}|sk-or-v1-[A-Za-z0-9_-]+)', '[REDACTED]', value)
    return value


def functions(tool_spec):
    specs = tool_spec if isinstance(tool_spec, list) else [tool_spec]
    if not specs:
        raise ValueError('At least one tool is required')
    result = []
    for spec in specs:
        fn = copy.deepcopy(spec.get('function', spec))
        if not fn.get('name') or not isinstance(fn.get('parameters', {}), dict):
            raise ValueError('Invalid tool specification')
        result.append({key: fn[key] for key in ('name', 'description', 'parameters') if key in fn})
    return result


def gemini_messages(messages):
    systems, contents = [], []
    tool_names, native_ids = {}, {}
    for message in messages:
        role = message['role']
        if role == 'system':
            systems.append(str(message.get('content') or ''))
            continue
        if role == 'assistant':
            for call in message.get('tool_calls') or []:
                tool_names[call['id']] = call['function']['name']
            if '_gemini_parts' in message:
                parts = copy.deepcopy(message['_gemini_parts'])
                for part in parts:
                    call = part.get('functionCall', {})
                    if call.get('id'):
                        native_ids[call['id']] = call['id']
            else:
                parts = []
                if message.get('content'):
                    parts.append({'text': message['content']})
                for call in message.get('tool_calls') or []:
                    arguments = call['function']['arguments']
                    if isinstance(arguments, str):
                        arguments = json.loads(arguments)
                    parts.append({'functionCall': {'name': call['function']['name'], 'args': arguments}})
            native_role = 'model'
        elif role == 'tool':
            content = message.get('content', '{}')
            try:
                content = json.loads(content) if isinstance(content, str) else content
            except json.JSONDecodeError:
                content = {'text': content}
            if not isinstance(content, dict):
                content = {'result': content}
            name = message.get('name') or tool_names.get(message.get('tool_call_id'))
            if not name:
                raise ValueError('Cannot match tool observation to a function name')
            function_response = {'name': name, 'response': content}
            if message.get('tool_call_id') in native_ids:
                function_response['id'] = native_ids[message['tool_call_id']]
            parts = [{'functionResponse': function_response}]
            native_role = 'user'
        elif role == 'user':
            parts = [{'text': str(message.get('content') or '')}]
            native_role = 'user'
        else:
            raise ValueError('Unsupported message role')
        if not parts:
            parts = [{'text': ''}]
        # Gemini permits several function responses in one user turn.
        if contents and contents[-1]['role'] == native_role:
            contents[-1]['parts'].extend(parts)
        else:
            contents.append({'role': native_role, 'parts': parts})
    return systems, contents


def openrouter_messages(messages):
    allowed = {'role', 'content', 'name', 'tool_calls', 'tool_call_id',
               'reasoning_details', 'reasoning', 'reasoning_content'}
    return [{key: copy.deepcopy(value) for key, value in message.items()
             if key in allowed} for message in messages]


class Client:
    def __init__(self, config, outdir, keysfile=None):
        self.config = copy.deepcopy(config)
        self.outdir = Path(outdir)
        self.outdir.mkdir(parents=True, exist_ok=True)
        self.provider = self.config['provider']
        if self.provider not in ('gemini', 'openrouter'):
            raise ValueError('Unsupported provider')
        self.model = self.config['model']
        self.model_id = self.config.get('id', self.model.replace('/', '__'))
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', self.model_id):
            raise ValueError('Invalid artifact model ID')
        self.keys = load_keys(keysfile)
        self.key = (self.keys.get('GEMINI_API_KEY') or self.keys.get('GOOGLE_API_KEY')) if self.provider == 'gemini' else self.keys.get('OPENROUTER_API_KEY')
        self.cap = float(self.config.get('cap_usd', 9))
        self.max_output = int(self.config.get('max_output_tokens', 8192))
        self.input_price = float(self.config['price_input_per_million'])
        self.output_price = float(self.config['price_output_per_million'])
        if not all(math.isfinite(x) and x >= 0 for x in (self.input_price, self.output_price)):
            raise ValueError('Invalid prices')
        if not math.isfinite(self.cap) or self.cap <= 0 or not 1 <= self.max_output <= 65536:
            raise ValueError('Invalid budget or output limit')
        if self.provider == 'openrouter' and not self.config.get('route_provider'):
            raise ValueError('An explicit OpenRouter route_provider is required')

    def check_credentials(self):
        """Free metadata/authentication check; never sends a generation request."""
        result = {'provider': self.provider, 'model': self.model,
                  'free_metadata_request': True, 'checked': stamp()}
        if not self.key:
            return {**result, 'ok': False, 'error': 'missing_key'}
        if self.provider == 'gemini':
            url = 'https://generativelanguage.googleapis.com/v1beta/models/' + urllib.parse.quote(self.model, safe='-._')
            headers = {'x-goog-api-key': self.key}
        else:
            url = 'https://openrouter.ai/api/v1/auth/key'
            headers = {'Authorization': 'Bearer ' + self.key}
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
                data = json.load(response)
            if self.provider == 'gemini':
                methods = data.get('supportedGenerationMethods', [])
                result.update(ok='generateContent' in methods,
                              served_model=data.get('name'),
                              supported_generation_methods=methods)
            else:
                account = data.get('data')
                result.update(ok=isinstance(account, dict))
                if isinstance(account, dict):
                    result['credit_limit_remaining'] = account.get('limit_remaining')
                    result['is_free_tier'] = account.get('is_free_tier')
        except Exception as exc:
            result.update(ok=False, error=type(exc).__name__)
            if isinstance(exc, urllib.error.HTTPError):
                result['http_status'] = exc.code
        return result

    @contextmanager
    def _locked(self):
        with (self.outdir/'budget.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _ledger(self):
        path = self.outdir/'budget.json'
        if path.exists():
            ledger = json.loads(path.read_text())
            if ledger['cap_usd'] != self.cap:
                raise BudgetError('Shared budget cap changed; use an explicit new collection')
            return ledger
        return {'version': 1, 'cap_usd': self.cap, 'charged_usd': 0.0,
                'reserved_usd': 0.0, 'requests': {}, 'created': stamp()}

    def _body(self, messages, tool_spec):
        declarations = functions(tool_spec)
        if self.provider == 'gemini':
            # Native Gemini Schema is not full JSON Schema. Keep constraints
            # supported by the native protobuf; world validation remains strict.
            def native_schema(schema):
                allowed = {'type', 'description', 'enum', 'properties', 'required', 'items'}
                result = {k: copy.deepcopy(v) for k,v in schema.items() if k in allowed}
                if 'properties' in result:
                    result['properties'] = {k:native_schema(v) for k,v in result['properties'].items()}
                if 'items' in result:
                    result['items'] = native_schema(result['items'])
                return result
            declarations = [{**f, 'parameters': native_schema(f.get('parameters', {}))} for f in declarations]
            systems, contents = gemini_messages(messages)
            body = {'contents': contents,
                    'tools': [{'functionDeclarations': declarations}],
                    'toolConfig': {'functionCallingConfig': {'mode': 'ANY',
                        'allowedFunctionNames': [f['name'] for f in declarations]}},
                    'generationConfig': {'temperature': self.config.get('temperature', 1),
                        'maxOutputTokens': self.max_output,
                        'thinkingConfig': {'thinkingLevel': self.config.get('thinking_level', 'HIGH'),
                                           'includeThoughts': True}}}
            if systems:
                body['systemInstruction'] = {'parts': [{'text': '\n\n'.join(systems)}]}
            url = 'https://generativelanguage.googleapis.com/v1beta/models/' + urllib.parse.quote(self.model, safe='-._') + ':generateContent'
            headers = {'x-goog-api-key': self.key or '', 'Content-Type': 'application/json'}
        else:
            support = self.config.get('tool_choice_support', {})
            if len(declarations) == 1 and support.get('function', True):
                tool_choice = {'type': 'function', 'function': {'name': declarations[0]['name']}}
            elif len(declarations) > 1 and support.get('required', True):
                tool_choice = 'required'
            elif support.get('auto', True):
                tool_choice = 'auto'
            else:
                raise ValueError('Selected route cannot support the required tool interaction')
            body = {'model': self.model, 'messages': openrouter_messages(messages),
                    'tools': [{'type': 'function', 'function': fn} for fn in declarations],
                    'tool_choice': tool_choice,
                    'temperature': self.config.get('temperature', 1), 'max_tokens': self.max_output,
                    'reasoning': {'effort': self.config.get('reasoning_effort', 'high'), 'exclude': False},
                    'provider': {'only': [self.config['route_provider']], 'allow_fallbacks': False,
                                 'require_parameters': True,
                                 'max_price': {'prompt': self.input_price, 'completion': self.output_price}},
                    'usage': {'include': True}}
            url = 'https://openrouter.ai/api/v1/chat/completions'
            headers = {'Authorization': 'Bearer ' + (self.key or ''), 'Content-Type': 'application/json',
                       'X-OpenRouter-Title': 'HF Safety local prime pilot'}
        return url, headers, body

    def _normalise(self, raw, elapsed, request_id):
        if self.provider == 'gemini':
            candidate = (raw.get('candidates') or [{}])[0]
            parts = candidate.get('content', {}).get('parts', [])
            assistant = {'role': 'assistant', 'content': '\n'.join(
                p['text'] for p in parts if 'text' in p and not p.get('thought')) or None,
                '_gemini_parts': copy.deepcopy(parts)}
            calls = []
            for index, part in enumerate(parts):
                if 'functionCall' in part:
                    fn = part['functionCall']
                    calls.append({'id': fn.get('id') or f'{request_id}-{index}', 'type': 'function',
                                  'function': {'name': fn.get('name'), 'arguments': canonical(fn.get('args', {}))}})
            if calls:
                assistant['tool_calls'] = calls
            reason = candidate.get('finishReason', 'missing')
            finish = {'STOP': 'stop', 'MAX_TOKENS': 'length'}.get(reason, reason.lower())
            usage = raw.get('usageMetadata', {})
        else:
            choice = (raw.get('choices') or [{}])[0]
            assistant = copy.deepcopy(choice.get('message', {'role': 'assistant', 'content': None}))
            calls = assistant.get('tool_calls') or []
            finish = choice.get('finish_reason', 'missing')
            usage = raw.get('usage', {})
        name, args = None, None
        if len(calls) == 1:
            name = calls[0].get('function', {}).get('name')
            arguments = calls[0].get('function', {}).get('arguments')
            try:
                args = json.loads(arguments) if isinstance(arguments, str) else arguments
                if not isinstance(args, dict):
                    args = None
            except (TypeError, json.JSONDecodeError):
                args = None
        return {'raw': raw, 'assistant_message': assistant, 'tool_name': name, 'arguments': args,
                'finish_reason': finish, 'usage': usage, 'elapsed_seconds': elapsed}

    def _cost(self, raw):
        if self.provider == 'openrouter':
            usage = raw.get('usage') or {}
            cost = usage.get('cost')
            if type(cost) in (int, float) and math.isfinite(cost) and cost >= 0:
                return float(cost)
            return None
        usage = raw.get('usageMetadata') or {}
        prompt = usage.get('promptTokenCount')
        candidates = usage.get('candidatesTokenCount', 0)
        thoughts = usage.get('thoughtsTokenCount', 0)
        total = usage.get('totalTokenCount')
        if not (type(prompt) is int and prompt >= 0 and type(total) is int and total >= prompt):
            return None
        if not all(type(x) is int and x >= 0 for x in (candidates, thoughts)):
            return None
        # Count thoughts as paid output, and conservatively include any unexplained
        # generated token difference. Cached inputs are charged at the full price.
        generated = max(candidates + thoughts, total - prompt)
        return (prompt*self.input_price + generated*self.output_price)/1_000_000

    def call(self, messages, tool_spec, request_id):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+', request_id):
            raise ValueError('request_id must be a safe filename')
        url, headers, body = self._body(messages, tool_spec)
        encoded = canonical(body).encode()
        max_bytes = int(self.config.get('max_context_bytes', 250000))
        if len(encoded) > max_bytes:
            raise BudgetError('Request exceeds configured serialized-byte context limit')
        # UTF-8 bytes plus a fixed provider/template allowance is a conservative
        # token reservation, not a claim of exact model tokenization.
        prompt_bound = len(encoded) + 4096 + 128*len(messages)
        reserve = 1.15*(prompt_bound*self.input_price + self.max_output*self.output_price)/1_000_000
        identity = sha({'provider': self.provider, 'model': self.model, 'body': body,
                        'price_input': self.input_price, 'price_output': self.output_price})
        ledger_id = self.model_id + '/' + request_id
        folder = self.outdir/'requests'/self.model_id/request_id
        with self._locked():
            ledger = self._ledger()
            previous = ledger['requests'].get(ledger_id)
            if previous:
                if previous['identity'] != identity:
                    raise ClientError('Request identity changed; refusing to reuse an ID')
                if previous['status'] != 'complete':
                    raise BudgetError('Previous request has unknown or unfinished cost; no automatic retry')
                result_path = folder/'result.json'
                if not result_path.exists():
                    raise ClientError('Completed request is missing its result artifact')
                result = json.loads(result_path.read_text())
                if previous.get('result_sha256') != sha(result):
                    raise ClientError('Completed request result integrity mismatch')
                return result
            if any(item['status'] != 'complete' for item in ledger['requests'].values()):
                raise BudgetError('An unresolved request blocks new spending; reconcile it explicitly')
            if not self.key:
                raise ClientError('Missing ' + ('GEMINI_API_KEY or GOOGLE_API_KEY' if self.provider == 'gemini' else 'OPENROUTER_API_KEY'))
            if ledger['charged_usd'] + ledger['reserved_usd'] + reserve > self.cap:
                raise BudgetError('Shared API budget limit reached')
            ledger['requests'][ledger_id] = {'identity': identity, 'status': 'pending',
                'reserved_usd': reserve, 'prompt_token_reservation': prompt_bound,
                'created': stamp(), 'model': self.model, 'provider': self.provider}
            ledger['reserved_usd'] += reserve
            dump(self.outdir/'budget.json', ledger)
            dump(folder/'request.json', {'url': url, 'body': redact(body, self.keys.values()),
                'identity': identity, 'reservation_usd': reserve, 'created': stamp()})
        started = time.monotonic()
        try:
            request = urllib.request.Request(url, data=encoded, headers=headers)
            with urllib.request.urlopen(request, timeout=self.config.get('timeout_seconds', 180)) as response:
                raw = json.load(response)
            raw = redact(raw, self.keys.values())
            dump(folder/'response.json', raw)
        except Exception as exc:
            detail = {'error_type': type(exc).__name__, 'message': str(exc), 'time': stamp()}
            if isinstance(exc, urllib.error.HTTPError):
                detail['status'] = exc.code
                detail['body'] = exc.read().decode(errors='replace')[:50000]
            dump(folder/'error.json', redact(detail, self.keys.values()))
            with self._locked():
                ledger = self._ledger()
                ledger['requests'][ledger_id]['status'] = 'unknown_cost_error'
                dump(self.outdir/'budget.json', ledger)
            raise ClientError('API request failed; redacted artifact saved, reservation retained, no retry') from None
        elapsed = time.monotonic() - started
        cost = self._cost(raw)
        result = self._normalise(raw, elapsed, request_id)
        result['cost_usd'] = cost
        result['cost_kind'] = 'provider_reported' if self.provider == 'openrouter' else 'conservative_list_price_estimate'
        result['request_identity'] = identity
        dump(folder/'result.json', result)
        with self._locked():
            ledger = self._ledger()
            entry = ledger['requests'][ledger_id]
            entry.update(finished=stamp(), result_sha256=sha(result))
            if cost is None:
                entry['status'] = 'unknown_cost_response'
            else:
                ledger['reserved_usd'] = max(0., ledger['reserved_usd']-reserve)
                ledger['charged_usd'] += cost
                entry.update(status='complete', cost_usd=cost)
                if cost > reserve:
                    entry['status'] = 'reservation_exceeded'
                if 'error' in raw:
                    entry['status'] = 'provider_error_known_cost'
            dump(self.outdir/'budget.json', ledger)
        if cost is None:
            raise BudgetError('Response lacks usable cost accounting; reservation retained')
        if cost > reserve:
            raise BudgetError('Provider cost exceeded conservative reservation; collection stopped')
        if 'error' in raw:
            raise ClientError('Provider returned an error; response and known cost preserved')
        return result
