import io
import json
import os
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from local_prime.client import (Client, ClientError, BudgetError, gemini_messages,
                                openrouter_messages, load_keys)


TOOL = {'type': 'function', 'function': {'name': 'submit_report', 'description': 'Report.',
        'parameters': {'type': 'object', 'properties': {'accessed': {'type': 'string'}},
                       'required': ['accessed']}}}
MESSAGES = [{'role': 'system', 'content': 'Follow the task.'}, {'role': 'user', 'content': 'Report.'}]
CONFIG = {'id': 'example', 'provider': 'openrouter', 'model': 'test/model',
          'route_provider': 'example/fp8', 'price_input_per_million': 1,
          'price_output_per_million': 2, 'max_output_tokens': 8192, 'cap_usd': 9}


def response(cost=.001):
    return {'id': 'response-id', 'model': 'test/model',
            'choices': [{'finish_reason': 'tool_calls', 'message': {'role': 'assistant',
                'content': None, 'tool_calls': [{'id': 'call1', 'type': 'function',
                    'function': {'name': 'submit_report', 'arguments': '{"accessed":"no"}'}}]}}],
            'usage': {'prompt_tokens': 10, 'completion_tokens': 20, 'cost': cost}}


def fake_http(value):
    return io.BytesIO(json.dumps(value).encode())


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'OPENROUTER_API_KEY': 'test-secret-router',
                                         'GEMINI_API_KEY': 'test-secret-gemini'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def client(self, **overrides):
        return Client({**CONFIG, **overrides}, self.root)

    def test_native_gemini_signature_and_tool_observation_survive_roundtrip(self):
        parts = [{'functionCall': {'name': 'read_file', 'args': {'path': 'task.json'}},
                  'thoughtSignature': 'opaque-signature'}]
        messages = MESSAGES + [{'role': 'assistant', 'content': None, '_gemini_parts': parts,
            'tool_calls': [{'id': 'c1', 'type': 'function', 'function': {
                'name': 'read_file', 'arguments': '{"path":"task.json"}'}}]},
            {'role': 'tool', 'tool_call_id': 'c1', 'content': '{"N":"123"}'}]
        systems, contents = gemini_messages(messages)
        self.assertEqual(systems, ['Follow the task.'])
        self.assertEqual(contents[1]['parts'], parts)
        self.assertEqual(contents[2]['parts'][0], {'functionResponse': {
            'name': 'read_file', 'response': {'N': '123'}}})
        self.assertNotIn('_gemini_parts', openrouter_messages(messages)[2])

    def test_native_function_id_is_returned_when_provider_supplies_one(self):
        assistant = {'role': 'assistant', 'content': None,
            '_gemini_parts': [{'functionCall': {'id': 'native123', 'name': 'inspect', 'args': {}}}],
            'tool_calls': [{'id': 'native123', 'type': 'function',
                            'function': {'name': 'inspect', 'arguments': '{}'}}]}
        _, contents = gemini_messages(MESSAGES + [assistant,
            {'role': 'tool', 'tool_call_id': 'native123', 'content': '{}'}])
        self.assertEqual(contents[-1]['parts'][0]['functionResponse']['id'], 'native123')

    def test_pinned_route_no_fallback_and_explicit_report_function(self):
        c = self.client()
        _, headers, body = c._body(MESSAGES, TOOL)
        self.assertEqual(body['provider']['only'], ['example/fp8'])
        self.assertFalse(body['provider']['allow_fallbacks'])
        self.assertEqual(body['tool_choice']['function']['name'], 'submit_report')
        _, _, actions = c._body(MESSAGES, [TOOL, {'name': 'inspect', 'parameters': {'type': 'object'}}])
        self.assertEqual(actions['tool_choice'], 'required')
        self.assertNotIn('Authorization', body)
        self.assertIn('Authorization', headers)

    def test_actual_route_capabilities_choose_supported_tool_mode(self):
        c = self.client(tool_choice_support={'auto': True, 'required': False, 'function': False})
        self.assertEqual(c._body(MESSAGES, TOOL)[2]['tool_choice'], 'auto')
        c = self.client(tool_choice_support={'auto': True, 'required': False, 'function': True})
        tools = [TOOL, {'name': 'inspect', 'parameters': {'type': 'object'}}]
        self.assertEqual(c._body(MESSAGES, tools)[2]['tool_choice'], 'auto')
        self.assertEqual(c._body(MESSAGES, TOOL)[2]['tool_choice']['function']['name'], 'submit_report')
        self.assertNotIn('parallel_tool_calls', c._body(MESSAGES, tools)[2])

    def test_free_auth_check_does_not_create_budget_or_send_prompt(self):
        c = self.client()
        with patch('urllib.request.urlopen', return_value=fake_http({'data': {'limit_remaining': 2}})) as http:
            result = c.check_credentials()
        self.assertTrue(result['ok'])
        self.assertEqual(http.call_args.args[0].get_method(), 'GET')
        self.assertEqual(http.call_args.args[0].full_url, 'https://openrouter.ai/api/v1/auth/key')
        self.assertIsNone(http.call_args.args[0].data)
        self.assertFalse((self.root/'budget.json').exists())
        self.assertNotIn('test-secret-router', json.dumps(result))

    def test_complete_request_reuses_artifact_without_spending_again(self):
        c = self.client()
        with patch('urllib.request.urlopen', return_value=fake_http(response())) as http:
            first = c.call(MESSAGES, TOOL, 'r1')
            second = c.call(MESSAGES, TOOL, 'r1')
        self.assertEqual(http.call_count, 1)
        self.assertEqual(first, second)
        self.assertEqual(first['arguments'], {'accessed': 'no'})
        ledger = json.loads((self.root/'budget.json').read_text())
        self.assertAlmostEqual(ledger['charged_usd'], .001)
        self.assertEqual(ledger['reserved_usd'], 0)
        with self.assertRaisesRegex(ClientError, 'identity changed'):
            c.call(MESSAGES + [{'role': 'user', 'content': 'Different task.'}], TOOL, 'r1')

    def test_budget_limit_blocks_before_network(self):
        c = self.client(cap_usd=.00001)
        with patch('urllib.request.urlopen') as http:
            with self.assertRaises(BudgetError):
                c.call(MESSAGES, TOOL, 'r1')
        http.assert_not_called()

    def test_unknown_cost_preserves_reservation_and_blocks_new_request(self):
        c = self.client()
        data = response()
        del data['usage']['cost']
        with patch('urllib.request.urlopen', return_value=fake_http(data)) as http:
            with self.assertRaisesRegex(BudgetError, 'cost accounting'):
                c.call(MESSAGES, TOOL, 'r1')
            with self.assertRaisesRegex(BudgetError, 'unresolved request'):
                c.call(MESSAGES, TOOL, 'r2')
        self.assertEqual(http.call_count, 1)
        ledger = json.loads((self.root/'budget.json').read_text())
        self.assertGreater(ledger['reserved_usd'], 0)
        self.assertEqual(ledger['requests']['example/r1']['status'], 'unknown_cost_response')

    def test_error_artifact_redacts_credential_and_preserves_unknown_cost(self):
        c = self.client()
        error = urllib.error.HTTPError('https://openrouter.ai/api/v1/chat/completions', 503,
            'test-secret-router', {}, io.BytesIO(b'{"error":"test-secret-router"}'))
        with patch('urllib.request.urlopen', side_effect=error) as http:
            with self.assertRaises(ClientError):
                c.call(MESSAGES, TOOL, 'r1')
            with self.assertRaises(BudgetError):
                c.call(MESSAGES, TOOL, 'r1')
        self.assertEqual(http.call_count, 1)
        artifacts = '\n'.join(p.read_text() for p in self.root.rglob('*.json'))
        self.assertNotIn('test-secret-router', artifacts)
        self.assertIn('[REDACTED]', artifacts)
        self.assertGreater(json.loads((self.root/'budget.json').read_text())['reserved_usd'], 0)

    def test_multiple_models_share_same_budget(self):
        with patch('urllib.request.urlopen', return_value=fake_http(response())):
            self.client().call(MESSAGES, TOOL, 'r1')
        with self.assertRaisesRegex(BudgetError, 'cap changed'):
            self.client(id='second', cap_usd=10).call(MESSAGES, TOOL, 'r1')
        with patch('urllib.request.urlopen', return_value=fake_http(response())):
            self.client(id='second').call(MESSAGES, TOOL, 'r1')
        ledger = json.loads((self.root/'budget.json').read_text())
        self.assertAlmostEqual(ledger['charged_usd'], .002)
        self.assertEqual(len(ledger['requests']), 2)

    def test_gemini_bills_thoughts_and_preserves_raw_parts(self):
        c = self.client(provider='gemini', model='gemini-test')
        data = {'candidates': [{'finishReason': 'STOP', 'content': {'role': 'model', 'parts': [
            {'text': 'Summary.', 'thought': True}, {'functionCall': {'name': 'submit_report',
            'args': {'accessed': 'no'}}, 'thoughtSignature': 'signature'}]}}],
            'usageMetadata': {'promptTokenCount': 100, 'candidatesTokenCount': 20,
                              'thoughtsTokenCount': 80, 'totalTokenCount': 200}}
        with patch('urllib.request.urlopen', return_value=fake_http(data)):
            result = c.call(MESSAGES, TOOL, 'g1')
        self.assertAlmostEqual(result['cost_usd'], (100+2*100)/1e6)
        self.assertEqual(result['finish_reason'], 'stop')
        self.assertIsNone(result['assistant_message']['content'])
        self.assertEqual(result['assistant_message']['_gemini_parts'][1]['thoughtSignature'], 'signature')

    def test_artifact_tampering_rejected(self):
        c = self.client()
        with patch('urllib.request.urlopen', return_value=fake_http(response())):
            c.call(MESSAGES, TOOL, 'r1')
        path = self.root/'requests/example/r1/result.json'
        data = json.loads(path.read_text());data['arguments']['accessed'] = 'yes'
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ClientError, 'integrity mismatch'):
            c.call(MESSAGES, TOOL, 'r1')

    def test_provider_overcharge_stops_collection(self):
        c = self.client()
        with patch('urllib.request.urlopen', return_value=fake_http(response(1))):
            with self.assertRaisesRegex(BudgetError, 'exceeded'):
                c.call(MESSAGES, TOOL, 'r1')
        with self.assertRaises(BudgetError):
            c.call(MESSAGES, TOOL, 'r2')
        self.assertEqual(json.loads((self.root/'budget.json').read_text())['charged_usd'], 1)

    def test_env_file_is_data_not_shell(self):
        path = self.root/'keys.env'
        path.write_text('export GEMINI_API_KEY="file-gemini"\nOPENROUTER_API_KEY=\'file-router\'\nOTHER=$(touch surprise)\n')
        with patch.dict(os.environ, {}, clear=True):
            keys = load_keys(path)
        self.assertEqual(keys, {'GEMINI_API_KEY': 'file-gemini', 'OPENROUTER_API_KEY': 'file-router'})
        self.assertFalse((self.root/'surprise').exists())

    def test_multiple_tool_calls_are_not_silently_executed_as_one(self):
        c = self.client()
        data = response()
        data['choices'][0]['message']['tool_calls'] *= 2
        with patch('urllib.request.urlopen', return_value=fake_http(data)):
            result = c.call(MESSAGES, TOOL, 'r1')
        self.assertIsNone(result['tool_name'])
        self.assertIsNone(result['arguments'])


if __name__ == '__main__':
    unittest.main()

class GeminiNativeSchemaTests(unittest.TestCase):
    def test_native_schema_removes_unsupported_json_schema_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            config={'id':'gemini','provider':'gemini','model':'gemini-3.8-flash','price_input_per_million':.75,'price_output_per_million':3.75}
            client=Client(config,Path(directory))
            spec={'type':'function','function':{'name':'foo','parameters':{'type':'object','additionalProperties':False,'properties':{'n':{'type':'integer','minimum':1}},'required':['n']}}}
            _,_,body=client._body([{'role':'user','content':'foo'}],spec)
            schema=body['tools'][0]['functionDeclarations'][0]['parameters']
            self.assertNotIn('additionalProperties',schema)
            self.assertNotIn('minimum',schema['properties']['n'])
            self.assertEqual(schema['required'],['n'])
