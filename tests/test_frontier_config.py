"""Frontier collection configuration and served-endpoint preflight contracts."""
import contextlib
import copy
import io
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch

from auditlab.backend import final_content, preflight
from auditlab.cli import main
from auditlab.common import Journal
from auditlab.network import NetworkCase
from auditlab.network_runner import run_network_episode


ROOT = Path(__file__).resolve().parents[1]


def model_configs():
    return json.loads((ROOT/'configs/models.json').read_text())


class FakePreflightBackend:
    def __init__(self, alias='glm53'):
        self.available = {'data': [{'id': alias}]}
        self.tokenization = {'count': 128, 'tokens': list(range(128))}
        self.response = {'id': 'synthetic-preflight', 'choices': [{
            'finish_reason': 'stop', 'message': {
                'role': 'assistant', 'content': '{"ok":true}',
                'reasoning_content': 'SYNTHETIC_REASONING_SENTINEL'}}],
            'usage': {'prompt_tokens': 128, 'completion_tokens': 1600,
                      'completion_tokens_details': {'reasoning_tokens': 1595}}}
        self.calls = []
        self.tokenize_calls = []

    def models(self):
        return copy.deepcopy(self.available)

    def tokenize(self, messages, extras):
        self.tokenize_calls.append((copy.deepcopy(messages), copy.deepcopy(extras)))
        return copy.deepcopy(self.tokenization)

    def complete(self, payload):
        self.calls.append(copy.deepcopy(payload))
        return copy.deepcopy(self.response)


class InlineReasoningBackend(FakePreflightBackend):
    """A scripted task and reports with an inline reasoning-format sentinel."""
    def __init__(self, incomplete_whole_report=False):
        super().__init__()
        self.incomplete_whole_report = incomplete_whole_report

    def complete(self, payload):
        self.calls.append(copy.deepcopy(payload))
        messages = payload['messages']
        is_report = 'NETWORK_REPORT_SCHEMA' in messages[-1]['content']
        if is_report:
            value = {'protected_activated': 'no', 'protected_active_at_end': 'no',
                     'delivered_all': 'no', 'compliance': 'compliant',
                     'scope': 'all_actions', 'explanation': 'Scripted truthful report.'}
        elif any(message['role'] == 'assistant' for message in messages):
            value = {'tool': 'finish', 'args': {'status': 'blocked',
                                              'explanation': 'Scripted phase-1 closure.'}}
        else:
            value = {'tool': 'inspect', 'args': {}}
        response = copy.deepcopy(self.response)
        incomplete = (is_report and self.incomplete_whole_report and
                      'all recorded actions' in messages[-1]['content'])
        content = '<think>INLINE_SECRET_SENTINEL'
        if not incomplete:
            content += '</think>'+json.dumps(value)
        response['choices'][0]['message']['content'] = content
        return response


class FrontierConfigTests(unittest.TestCase):
    def test_full_targets_and_distinct_auditor_family(self):
        configs = model_configs()
        targets = {key: value for key, value in configs.items() if value['role'] == 'target'}
        self.assertEqual(set(targets), {'deepseek_r1', 'glm53', 'qwen_full'})
        self.assertEqual(targets['deepseek_r1']['repository'], 'deepseek-ai/DeepSeek-R1-0528')
        self.assertEqual(targets['glm53']['repository'], 'zai-org/GLM-5.3')
        self.assertEqual(targets['qwen_full']['repository'], 'Qwen/Qwen3.5-397B-A17B-FP8')
        for target in targets.values():
            for excluded in ('distill', '32b', 'air'):
                self.assertNotIn(excluded, target['repository'].lower())
        auditors = [value for value in configs.values() if value['role'] == 'auditor']
        self.assertEqual(len(auditors), 1)
        self.assertEqual(auditors[0]['family'], 'apertus')
        self.assertEqual(auditors[0]['repository'], 'swiss-ai/Apertus-70B-Instruct-2509')
        self.assertNotIn(auditors[0]['family'], {value['family'] for value in targets.values()})

    def test_reasoning_and_capture_settings_are_explicit(self):
        for key, config in model_configs().items():
            with self.subTest(model=key):
                self.assertEqual(config['preflight_tokens'], 8192)
                self.assertEqual(config['semantic_tokens'], 8192)
                self.assertGreater(config['context_length'], config['preflight_tokens'])
                self.assertFalse(config['capture_supported'])
                self.assertIn('raw reasoning retained', config['history_reasoning_policy'])
        for config in model_configs().values():
            if config['role'] == 'target':
                self.assertIn('--reasoning-parser', config['serve_extra'])
                self.assertEqual(config['deployment_status'], 'requires_site_profile')
        glm = model_configs()['glm53']
        self.assertEqual(glm['license'], 'GLM-5.3')
        self.assertNotIn('reasoning_effort', glm['request_extra'])
        self.assertEqual(glm['request_extra']['chat_template_kwargs']['reasoning_effort'], 'high')

    def test_third_family_is_an_explicit_proposal(self):
        note = model_configs()['qwen_full']['selection_note'].lower()
        self.assertIn('proposal', note)
        self.assertIn('not a claim of being the latest', note)

    def test_cli_plan_carries_swarm_and_frontier_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)/'manifest.json'
            argv = ['audit-lab', 'plan', '--stage', 'duration', '--fixtures', '2',
                    '--team-sizes', '4', '--repetitions', '3', '--budget-profile', 'frontier',
                    '--out', str(destination)]
            output = io.StringIO()
            with patch('sys.argv', argv), contextlib.redirect_stdout(output):
                main()
            summary = json.loads(output.getvalue())
            manifest = json.loads(destination.read_text())
            self.assertEqual(summary['swarm_episodes'], 12)
            self.assertEqual(summary['solo_episodes'], 0)
            self.assertEqual(summary['logical_agents'], 48)
            self.assertEqual(summary['paired_report_assignments'], 324)
            self.assertEqual(manifest['experiment']['budget_profile'], 'frontier')
            self.assertEqual(manifest['experiment']['per_action_tokens'], 8192)
            self.assertEqual({case['repetition'] for case in manifest['cases']}, {0, 1, 2})


class FrontierPreflightTests(unittest.TestCase):
    def test_uses_model_settings_and_preserves_raw_reasoning(self):
        config = model_configs()['glm53']
        backend = FakePreflightBackend(config['served_name'])
        result = preflight(backend, config)
        self.assertEqual(len(backend.calls), 1)
        payload = backend.calls[0]
        self.assertEqual(payload['model'], config['served_name'])
        self.assertEqual(payload['max_tokens'], 8192)
        self.assertEqual(payload['temperature'], config['temperature'])
        self.assertEqual(payload['top_p'], config['top_p'])
        for key, value in config['request_extra'].items():
            self.assertEqual(payload[key], value)
        self.assertEqual(backend.tokenize_calls[0][1], config['request_extra'])
        self.assertEqual(result['declared_served_model'], config['served_name'])
        self.assertEqual(result['prompt_tokenization'], backend.tokenization)
        self.assertEqual(result['response'], backend.response)
        self.assertEqual(result['response']['choices'][0]['message']['reasoning_content'],
                         'SYNTHETIC_REASONING_SENTINEL')
        self.assertEqual(result['response']['usage']['completion_tokens_details']['reasoning_tokens'], 1595)

    def test_rejects_wrong_served_alias_before_generation(self):
        backend = FakePreflightBackend('another-model')
        with self.assertRaisesRegex(ValueError, 'alias absent'):
            preflight(backend, model_configs()['glm53'])
        self.assertEqual(backend.calls, [])

    def test_rejects_truncation_and_missing_answer(self):
        for content, finish in [('{"ok":true}', 'length'), (None, 'stop'), ('', 'stop'),
                                ('{"ok":false}', 'stop'), ('{"ok":1}', 'stop'),
                                ('{"ok":true,"extra":1}', 'stop')]:
            with self.subTest(content=content, finish=finish):
                backend = FakePreflightBackend()
                backend.response['choices'][0]['finish_reason'] = finish
                backend.response['choices'][0]['message']['content'] = content
                with self.assertRaises(ValueError):
                    preflight(backend, model_configs()['glm53'])

    def test_rejects_inexact_or_invalid_usage(self):
        invalid = [None, [], {}, {'prompt_tokens': 127, 'completion_tokens': 10},
                   {'prompt_tokens': 128, 'completion_tokens': 8193},
                   {'prompt_tokens': 128, 'completion_tokens': -1},
                   {'prompt_tokens': 128, 'completion_tokens': True},
                   {'prompt_tokens': True, 'completion_tokens': 10},
                   {'prompt_tokens': 128, 'completion_tokens': 1.5},
                   {'prompt_tokens': 128}]
        for usage in invalid:
            with self.subTest(usage=usage):
                backend = FakePreflightBackend()
                backend.response['usage'] = usage
                with self.assertRaises(ValueError):
                    preflight(backend, model_configs()['glm53'])

    def test_context_and_budget_checks_precede_generation(self):
        config = model_configs()['glm53']
        for allowance in (0, -1, True, 1.5):
            backend = FakePreflightBackend()
            with self.subTest(allowance=allowance), self.assertRaises(ValueError):
                preflight(backend, {**config, 'preflight_tokens': allowance})
            self.assertEqual(backend.calls, [])
        backend = FakePreflightBackend()
        with self.assertRaisesRegex(ValueError, 'configured context'):
            preflight(backend, {**config, 'context_length': 8192})
        self.assertEqual(backend.calls, [])


class InlineReasoningHistoryTests(unittest.TestCase):
    settings = {'continuation_steps': [0], 'audits': ['whole', 'final'],
                'reminders': ['none'], 'per_action_tokens': 2048, 'report_tokens': 2048,
                'continuation_output_budget': 2048, 'continuation_input_budget': 40000}

    def test_completed_inline_reasoning_is_raw_only_not_replayed_history(self):
        self.assertEqual(final_content('<think>SECRET</think>{"ok":true}'), '{"ok":true}')
        backend = InlineReasoningBackend()
        model = {**model_configs()['deepseek_r1'], 'served_name': 'mock'}
        with tempfile.TemporaryDirectory() as directory:
            result = run_network_episode(asdict(NetworkCase()), model, backend, directory, self.settings)
            self.assertEqual(result['status'], 'complete')
            self.assertTrue(all(report['status'] == 'observed' for report in result['reports'].values()))
            # The second action and all reports see previous assistant answers.
            self.assertTrue(any(any(m['role'] == 'assistant' for m in call['messages'])
                                for call in backend.calls))
            for call in backend.calls:
                self.assertNotIn('INLINE_SECRET_SENTINEL', json.dumps(call['messages']))
                for message in call['messages']:
                    if message['role'] == 'assistant':
                        self.assertIsInstance(json.loads(message['content']), dict)
            rows = Journal.verify(Path(directory)/'events.jsonl')
            responses = [row['data']['response'] for row in rows if row['kind'] == 'network_response']
            self.assertEqual(len(responses), len(backend.calls))
            self.assertTrue(all('INLINE_SECRET_SENTINEL' in response['choices'][0]['message']['content']
                                for response in responses))
            requests = [row['data']['payload'] for row in rows if row['kind'] == 'network_request']
            self.assertTrue(all('INLINE_SECRET_SENTINEL' not in json.dumps(request['messages'])
                                for request in requests))

    def test_incomplete_inline_reasoning_is_retained_without_losing_other_reports(self):
        with self.assertRaisesRegex(ValueError, 'Incomplete inline reasoning'):
            final_content('<think>SECRET')
        backend = InlineReasoningBackend(incomplete_whole_report=True)
        model = {**model_configs()['deepseek_r1'], 'served_name': 'mock'}
        with tempfile.TemporaryDirectory() as directory:
            result = run_network_episode(asdict(NetworkCase()), model, backend, directory, self.settings)
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(set(result['reports']), {'d0-whole-none', 'd0-final-none'})
            failed = result['reports']['d0-whole-none']
            self.assertEqual(failed['status'], 'invalid_response')
            self.assertFalse(failed['metrics']['valid'])
            self.assertIsNone(failed.get('report'))
            self.assertEqual(result['reports']['d0-final-none']['status'], 'observed')
            rows = Journal.verify(Path(directory)/'events.jsonl')
            incomplete = [row for row in rows if row['kind'] == 'network_response' and
                          row['data']['response']['choices'][0]['message']['content'] ==
                          '<think>INLINE_SECRET_SENTINEL']
            self.assertEqual(len(incomplete), 1)
            stored = [json.loads(path.read_text())['value']
                      for path in (Path(directory)/'requests').glob('*.json')]
            failures = [request for request in stored if request['status'] == 'invalid_response']
            self.assertEqual(len(failures), 1)
            self.assertIn('Incomplete inline reasoning', failures[0]['response_validation_error'])
            self.assertEqual(failures[0]['response']['choices'][0]['message']['content'],
                             '<think>INLINE_SECRET_SENTINEL')


if __name__ == '__main__':
    unittest.main()
