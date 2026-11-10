import io
import json
import os
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from local_prime.client import BudgetError, ClientError, Client
from local_prime.concurrent_client import ConcurrentClient, budget_allows_new_requests


TOOL = {'name': 'finish', 'description': 'Finish.', 'parameters': {'type': 'object', 'properties': {}}}
MESSAGES = [{'role': 'system', 'content': 'Return one tool call.'}, {'role': 'user', 'content': 'Act.'}]
CONFIG = {'id': 'test', 'provider': 'openrouter', 'model': 'test/model', 'route_provider': 'example/fp8',
          'price_input_per_million': 1, 'price_output_per_million': 2,
          'max_output_tokens': 8192, 'cap_usd': 9}


def answer(cost=.001):
    return {'id': 'mock-id', 'choices': [{'finish_reason': 'tool_calls', 'message': {
        'role': 'assistant', 'content': None, 'tool_calls': [{'id': 'c1', 'type': 'function',
        'function': {'name': 'finish', 'arguments': '{}'}}]}}], 'usage': {'cost': cost}}


def http_response(data=None):
    return io.BytesIO(json.dumps(answer() if data is None else data).encode())


class ConcurrentClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {'OPENROUTER_API_KEY': 'mock-secret'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def client(self, **kwargs):
        return ConcurrentClient({**CONFIG, **kwargs}, self.root)

    def ledger(self):
        return json.loads((self.root/'budget.json').read_text())

    def test_two_pending_requests_have_full_aggregate_reservations(self):
        clients = [self.client(id='one'), self.client(id='two')]
        entered = threading.Barrier(3)
        release = threading.Event()
        def http(*args, **kwargs):
            entered.wait(timeout=5)
            if not release.wait(timeout=5):
                raise RuntimeError('test release timeout')
            return http_response()
        with patch('urllib.request.urlopen', side_effect=http) as network, ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(c.call, MESSAGES, TOOL, 'r1') for c in clients]
            try:
                entered.wait(timeout=5)
                ledger = self.ledger()
                pending = list(ledger['requests'].values())
                self.assertEqual(len(pending), 2)
                self.assertEqual({v['status'] for v in pending}, {'pending'})
                self.assertAlmostEqual(ledger['reserved_usd'], sum(v['reserved_usd'] for v in pending))
                self.assertLessEqual(ledger['reserved_usd'], ledger['cap_usd'])
            finally:
                release.set()
            [future.result(timeout=5) for future in futures]
        self.assertEqual(network.call_count, 2)
        self.assertAlmostEqual(self.ledger()['charged_usd'], .002)
        self.assertAlmostEqual(self.ledger()['reserved_usd'], 0)

    def test_pending_reservation_blocks_over_budget_before_http(self):
        c = self.client(cap_usd=.04)  # One reservation fits; two do not.
        entered, release = threading.Event(), threading.Event()
        def http(*args, **kwargs):
            entered.set()
            if not release.wait(timeout=5):
                raise RuntimeError('test release timeout')
            return http_response()
        with patch('urllib.request.urlopen', side_effect=http) as network, ThreadPoolExecutor(1) as pool:
            first = pool.submit(c.call, MESSAGES, TOOL, 'first')
            try:
                self.assertTrue(entered.wait(timeout=5))
                with self.assertRaisesRegex(BudgetError, 'budget limit'):
                    c.call(MESSAGES, TOOL, 'second')
                self.assertEqual(network.call_count, 1)
            finally:
                release.set()
            first.result(timeout=5)

    def test_same_pending_id_never_duplicates_and_completed_id_uses_cache(self):
        c = self.client()
        entered, release = threading.Event(), threading.Event()
        def http(*args, **kwargs):
            entered.set()
            if not release.wait(timeout=5):
                raise RuntimeError('test release timeout')
            return http_response()
        with patch('urllib.request.urlopen', side_effect=http) as network, ThreadPoolExecutor(1) as pool:
            first = pool.submit(c.call, MESSAGES, TOOL, 'r1')
            try:
                self.assertTrue(entered.wait(timeout=5))
                with self.assertRaisesRegex(BudgetError, 'no automatic retry'):
                    c.call(MESSAGES, TOOL, 'r1')
            finally:
                release.set()
            result = first.result(timeout=5)
            self.assertEqual(c.call(MESSAGES, TOOL, 'r1'), result)
        self.assertEqual(network.call_count, 1)
        self.assertEqual(len(self.ledger()['requests']), 1)

    def test_unknown_cost_stops_new_requests_without_releasing_reservation(self):
        c = self.client()
        raw = answer();raw['usage'] = {}
        with patch('urllib.request.urlopen', return_value=http_response(raw)) as network:
            with self.assertRaisesRegex(BudgetError, 'cost accounting'):
                c.call(MESSAGES, TOOL, 'unknown')
            reserved = self.ledger()['reserved_usd']
            self.assertGreater(reserved, 0)
            with self.assertRaisesRegex(BudgetError, 'unresolved request'):
                c.call(MESSAGES, TOOL, 'new')
        self.assertEqual(network.call_count, 1)
        self.assertEqual(self.ledger()['reserved_usd'], reserved)

    def test_network_error_and_overspend_also_block_new_requests(self):
        for failure in ('error', 'overspend'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                c = ConcurrentClient(CONFIG, Path(tmp))
                stub = (patch('urllib.request.urlopen', side_effect=TimeoutError('mock-secret'))
                        if failure == 'error' else patch('urllib.request.urlopen', return_value=http_response(answer(1))))
                with stub as network:
                    with self.assertRaises((ClientError, BudgetError)):
                        c.call(MESSAGES, TOOL, 'r1')
                    with self.assertRaises(BudgetError):
                        c.call(MESSAGES, TOOL, 'r2')
                self.assertEqual(network.call_count, 1)
                self.assertNotIn('mock-secret', '\n'.join(p.read_text() for p in Path(tmp).rglob('*.json')))

    def make_missing(self, client, request_id='missing'):
        with patch('urllib.request.urlopen', side_effect=TimeoutError('simulated read timeout')):
            with self.assertRaises(ClientError):
                client.call(MESSAGES, TOOL, request_id)
        return self.ledger()

    def settle(self, ledger, ledger_id='test/missing'):
        entry = ledger['requests'][ledger_id]
        ceiling = entry['reserved_usd']
        ledger['reserved_usd'] -= ceiling
        ledger['charged_usd'] += ceiling
        entry.update(status='settled_missing', accounted_ceiling_usd=ceiling, cost_usd=ceiling)
        (self.root/'budget.json').write_text(json.dumps(ledger))
        return ceiling

    def test_fully_funded_settlement_allows_new_call_but_never_retries_old_id(self):
        c = self.client()
        ledger = self.make_missing(c)
        ceiling = self.settle(ledger)
        with patch('urllib.request.urlopen', return_value=http_response()) as network:
            with self.assertRaisesRegex(BudgetError, 'no automatic retry'):
                c.call(MESSAGES, TOOL, 'missing')
            c.call(MESSAGES, TOOL, 'new')
        self.assertEqual(network.call_count, 1)
        self.assertEqual(network.call_args.kwargs['timeout'], 600)
        self.assertAlmostEqual(self.ledger()['charged_usd'], ceiling + .001)
        self.assertEqual(self.ledger()['requests']['test/missing']['status'], 'settled_missing')

    def test_unfunded_or_partial_settlement_cannot_unlock_spending(self):
        c = self.client()
        ledger = self.make_missing(c)
        entry = ledger['requests']['test/missing']
        ceiling = entry['reserved_usd']
        entry.update(status='settled_missing', accounted_ceiling_usd=ceiling, cost_usd=ceiling)
        self.assertFalse(budget_allows_new_requests(ledger))
        ledger['charged_usd'] = ceiling
        self.assertTrue(budget_allows_new_requests(ledger))
        entry['accounted_ceiling_usd'] = ceiling / 2
        self.assertFalse(budget_allows_new_requests(ledger))
        entry['accounted_ceiling_usd'] = ceiling
        entry['cost_usd'] = ceiling / 2
        self.assertFalse(budget_allows_new_requests(ledger))
        entry['cost_usd'] = ceiling
        ledger['requests']['prior'] = {'status': 'complete', 'cost_usd': .01}
        self.assertFalse(budget_allows_new_requests(ledger))
        (self.root/'budget.json').write_text(json.dumps(ledger))
        with patch('urllib.request.urlopen') as network:
            with self.assertRaisesRegex(BudgetError, 'unresolved request'):
                c.call(MESSAGES, TOOL, 'new')
        network.assert_not_called()

    def test_settled_ceiling_still_consumes_total_budget(self):
        c = self.client(cap_usd=.04)
        ledger = self.make_missing(c)
        self.settle(ledger)
        with patch('urllib.request.urlopen') as network:
            with self.assertRaisesRegex(BudgetError, 'budget limit'):
                c.call(MESSAGES, TOOL, 'new')
        network.assert_not_called()

    def test_request_bodies_and_identities_match_serial_client(self):
        serial = Client(CONFIG, self.root/'serial')
        concurrent = ConcurrentClient(CONFIG, self.root/'concurrent')
        self.assertEqual(serial._body(MESSAGES, TOOL), concurrent._body(MESSAGES, TOOL))
        with patch('urllib.request.urlopen', side_effect=lambda *a, **kw:http_response()):
            first = serial.call(MESSAGES, TOOL, 'r1')
            second = concurrent.call(MESSAGES, TOOL, 'r1')
        self.assertEqual(first['request_identity'], second['request_identity'])


if __name__ == '__main__':
    unittest.main()
