"""Additive concurrent transport; task stimuli and request bodies are unchanged.

Each live request reserves its full worst-case cost under the shared flock.
Other pending IDs are permitted. Unknown/error states stop new spending unless
an operator explicitly books the entire reservation as a missing-response cost
ceiling. Neither pending nor settled-missing IDs are ever retried. Existing pending records must be
reconciled before restarting after a crash: 'pending' means in-flight work, not
permission to replay a possibly billed request.

Request bodies and identities still mirror the frozen serial client. Transport
changes are concurrent reservations, a 600-second default timeout, and explicit
fully funded missing-response settlements. Settlement does not establish the
provider's actual charge and never recovers or retries the missing observation.
"""
import json
import math
import re
import time
import urllib.error
import urllib.request

from .client import Client, BudgetError, ClientError, canonical, dump, redact, sha, stamp


def budget_allows_new_requests(ledger):
    """Validate allowed states and accounting for explicit missing settlements.

    A settlement is accepted only when its full original reservation is booked
    as cost and the shared charged total covers all completed/settled entries.
    This helper never edits a ledger or settles a request automatically.
    """
    def amount(value):
        return type(value) in (int, float) and math.isfinite(value) and value >= 0

    charged = ledger.get('charged_usd')
    if not amount(charged):
        return False
    accounted = 0.0
    for entry in ledger.get('requests', {}).values():
        status = entry.get('status')
        if status == 'pending':
            continue
        if status not in ('complete', 'settled_missing'):
            return False
        cost = entry.get('cost_usd')
        if not amount(cost):
            return False
        accounted += cost
        if status == 'settled_missing':
            ceiling, reserved = entry.get('accounted_ceiling_usd'), entry.get('reserved_usd')
            if not amount(ceiling) or not amount(reserved):
                return False
            if not cost == ceiling == reserved:
                return False
    return charged + 1e-12 >= accounted


class ConcurrentClient(Client):
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
            if not budget_allows_new_requests(ledger):
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
            with urllib.request.urlopen(request, timeout=self.config.get('timeout_seconds', 600)) as response:
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
