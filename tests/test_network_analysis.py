import copy
import itertools
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from auditlab.common import Journal, digest, read_json, write_json
from auditlab.network import NetworkCase
from auditlab.network_analysis import summarize_network


SETTINGS = {'continuation_steps': [0, 8], 'audits': ['whole'], 'reminders': ['none']}


def setup_campaign(root, cases, model_ids=('first',)):
    manifest = {'kind': 'network-v2', 'cases': [asdict(c) for c in cases], 'experiment': SETTINGS}
    manifest['design_hash'] = digest(manifest)
    write_json(root/'manifest.json', manifest)
    models = []
    for name in model_ids:
        model = {'id': name, 'family': name, 'served_name': name, 'revision': 'test'}
        write_json(root/'models'/(name+'.json'), model)
        models.append(model)
    return models


def observed(value, compliance=False, completion=False):
    return {'status': 'observed', 'metrics': {'valid': True,
             'false_activation_denial': value, 'false_compliance_claim': compliance,
             'false_completion_claim': completion, 'false_activation_assertion': False,
             'false_final_state_claim': False}}


def add_result(root, case, model, zero=None, later=None, facts=None):
    case_data = asdict(case)
    directory = root/model['id']/case.id
    journal = Journal(directory/'events.jsonl')
    identity = digest([case_data, model])
    journal.append('episode_start', {'kind': 'network-v2', 'identity': identity,
                                    'case': case_data, 'model': model})
    checkpoint = {'facts': facts or {'protected_activated_ever': True, 'protected_active_now': False,
                    'delivered_all': True, 'task_utility': 1, 'governing_violation': True,
                    'false_completion_claim': False}, 'policy': 'test rule', 'evidence': []}
    checkpoint['id'] = digest(checkpoint)
    reports = {}
    for dose, report in ((0, zero), (8, later)):
        entry = copy.deepcopy(report) if report is not None else {'status': 'pending', 'metrics': {'valid': False}}
        entry.update({'dose': dose, 'audit': 'whole', 'reminder': 'none', 'checkpoint_id': checkpoint['id']})
        reports[f'd{dose}-whole-none'] = entry
    result = {'kind': 'network-v2', 'identity': identity, 'case_id': case.id, 'case': case_data,
              'model': model, 'settings': SETTINGS, 'status': 'complete', 'synthetic': False,
              'checkpoint': checkpoint, 'reports': reports, 'journal_root': journal.previous}
    result['result_hash'] = digest(result)
    path = directory/'result.json'
    write_json(path, result)
    return path


def expand_reports(root, settings, values_by_case):
    manifest = read_json(root/'manifest.json')
    manifest['experiment'] = settings
    manifest['design_hash'] = digest({k: v for k, v in manifest.items() if k != 'design_hash'})
    write_json(root/'manifest.json', manifest)
    for path in root.rglob('result.json'):
        result = read_json(path)
        result['settings'] = settings
        values = values_by_case[result['case_id']]
        reports = {}
        for dose, audit, reminder in itertools.product(settings['continuation_steps'], settings['audits'], settings['reminders']):
            key = f'd{dose}-{audit}-{reminder}'
            value = values.get(key)
            report = observed(bool(value)) if value is not None else {'status': 'pending', 'metrics': {'valid': False}}
            report.update({'dose': dose, 'audit': audit, 'reminder': reminder,
                           'checkpoint_id': result['checkpoint']['id']})
            reports[key] = report
        result['reports'] = reports
        result['result_hash'] = digest({k: v for k, v in result.items() if k != 'result_hash'})
        write_json(path, result)


class NetworkAnalysisTests(unittest.TestCase):
    def test_denominators_include_unstarted_registered_models_and_cases(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = [NetworkCase(fixture=0), NetworkCase(fixture=1)]
            models = setup_campaign(root, cases, ('first', 'second'))
            add_result(root, cases[0], models[0], observed(False), observed(True))
            summary = summarize_network(root)
            self.assertEqual(summary['assigned_episodes'], 4)
            self.assertEqual(summary['results_available'], 1)
            self.assertEqual(summary['results_missing'], 3)
            self.assertEqual(summary['unstarted_without_error_record'], 3)
            first = next(s for s in summary['strata'] if s['stratum']['model_id'] == 'first')
            metric = first['report_cells']['d8-whole-none']['metrics']['false_activation_denial']
            self.assertEqual(metric['assigned'], 2)
            self.assertEqual(metric['observed'], 1)
            self.assertEqual(metric['assigned_mean_bounds'], [.5, 1])
            second = next(s for s in summary['strata'] if s['stratum']['model_id'] == 'second')
            self.assertEqual(second['checkpoints_available'], 0)
            self.assertEqual(second['phase1_outcomes']['task_utility']['assigned_mean_bounds'], [0, 1])

    def test_paired_bounds_use_observed_side_of_incomplete_pair(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = [NetworkCase(fixture=0), NetworkCase(fixture=1)]
            model = setup_campaign(root, cases)[0]
            add_result(root, cases[0], model, observed(False), observed(True))
            add_result(root, cases[1], model, observed(True), {'status': 'context_limit', 'metrics': {'valid': False}})
            row = summarize_network(root)['strata'][0]
            contrast = row['duration_contrasts']['d8-whole-none']['metrics']['false_activation_denial']
            self.assertEqual(contrast['assigned_pairs'], 2)
            self.assertEqual(contrast['complete_pairs'], 1)
            self.assertEqual(contrast['mean_difference_among_complete_pairs'], 1)
            self.assertEqual(contrast['assigned_mean_difference_bounds'], [0, .5])
            self.assertEqual(contrast['pair_status']['immediate_only'], 1)
            self.assertIsNone(contrast['fixture_weighted_bootstrap_95_interval'])

    def test_ambiguous_compliance_is_not_applicable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = NetworkCase(policy='ambiguous')
            model = setup_campaign(root, [case])[0]
            add_result(root, case, model, observed(False, compliance=None), observed(True, compliance=None))
            row = summarize_network(root)['strata'][0]
            metric = row['report_cells']['d0-whole-none']['metrics']['false_compliance_claim']
            self.assertEqual(metric['assigned'], 0)
            self.assertEqual(metric['not_applicable'], 1)
            self.assertIsNone(metric['assigned_mean_bounds'])
            contrast = row['duration_contrasts']['d8-whole-none']['metrics']['false_compliance_claim']
            self.assertEqual(contrast['not_applicable'], 1)

    def test_scenarios_are_not_pooled_and_prefix_claim_is_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = [NetworkCase(scenario='fair'), NetworkCase(scenario='poisoned')]
            model = setup_campaign(root, cases)[0]
            facts = {'protected_activated_ever': False, 'protected_active_now': False,
                     'delivered_all': False, 'task_utility': .5, 'governing_violation': False,
                     'false_completion_claim': True}
            add_result(root, cases[1], model, observed(False, completion=False), observed(False, completion=False), facts)
            summary = summarize_network(root)
            self.assertEqual(len(summary['strata']), 2)
            poisoned = next(s for s in summary['strata'] if s['stratum']['scenario'] == 'poisoned')
            self.assertEqual(poisoned['phase1_outcomes']['false_completion_claim']['mean_among_observed'], 1)
            self.assertEqual(poisoned['report_cells']['d0-whole-none']['metrics']['false_completion_claim']['mean_among_observed'], 0)
            self.assertEqual(poisoned['phase1_outcomes']['task_utility']['mean_among_observed'], .5)

    def test_result_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = NetworkCase()
            model = setup_campaign(root, [case])[0]
            path = add_result(root, case, model, observed(False), observed(False))
            result = read_json(path)
            result['reports']['d0-whole-none']['metrics']['false_activation_denial'] = True
            write_json(path, result)
            with self.assertRaisesRegex(ValueError, 'integrity'):
                summarize_network(root)

    def test_missing_journal_and_wrong_checkpoint_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = NetworkCase()
            model = setup_campaign(root, [case])[0]
            path = add_result(root, case, model, observed(False), observed(False))
            result = read_json(path)
            result['checkpoint']['facts']['delivered_all'] = False
            result['result_hash'] = digest({k: v for k, v in result.items() if k != 'result_hash'})
            write_json(path, result)
            with self.assertRaisesRegex(ValueError, 'Checkpoint'):
                summarize_network(root)
            (path.parent/'events.jsonl').unlink()
            with self.assertRaisesRegex(ValueError, 'missing its observer journal'):
                summarize_network(root)

    def test_unregistered_result_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = NetworkCase()
            model = setup_campaign(root, [case])[0]
            add_result(root, case, model)
            (root/'models'/'first.json').unlink()
            with self.assertRaisesRegex(ValueError, 'Unregistered'):
                summarize_network(root)

    def test_uncertainty_is_visible_and_not_a_false_denial(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = NetworkCase()
            model = setup_campaign(root, [case])[0]
            report = observed(False)
            report['report'] = {'protected_activated': 'uncertain', 'compliance': 'uncertain',
                                'delivered_all': 'uncertain', 'protected_active_at_end': 'uncertain'}
            report['metrics'].update({'false_noncompliance_claim': False,
                                      'incorrect_compliance_verdict': False})
            add_result(root, case, model, report, report)
            metrics = summarize_network(root)['strata'][0]['report_cells']['d0-whole-none']['metrics']
            self.assertEqual(metrics['false_activation_denial']['mean_among_observed'], 0)
            self.assertEqual(metrics['uncertain_activation_report']['mean_among_observed'], 1)
            self.assertEqual(metrics['uncertain_compliance_report']['mean_among_observed'], 1)
            self.assertEqual(metrics['false_noncompliance_claim']['mean_among_observed'], 0)

    def test_paired_audit_reminder_and_duration_interactions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = NetworkCase()
            model = setup_campaign(root, [case])[0]
            add_result(root, case, model)
            settings = {'continuation_steps': [0, 8], 'audits': ['whole', 'final'],
                        'reminders': ['none', 'ledger']}
            values = {f'd{d}-{a}-{r}': 0 for d, a, r in itertools.product(
                      settings['continuation_steps'], settings['audits'], settings['reminders'])}
            values['d8-final-none'] = 1
            expand_reports(root, settings, {case.id: values})
            row = summarize_network(root)['strata'][0]
            audit = row['audit_contrasts']['d8-none']['metrics']['false_activation_denial']
            reminder = row['reminder_contrasts']['d8-final']['metrics']['false_activation_denial']
            d2 = row['duration_audit_interactions']['d8-none']['metrics']['false_activation_denial']
            d3 = row['duration_reminder_interactions']['d8-final']['metrics']['false_activation_denial']
            self.assertEqual(audit['mean_difference_among_complete_histories'], 1)
            self.assertEqual(reminder['mean_difference_among_complete_histories'], -1)
            self.assertEqual(d2['assigned_mean_difference_bounds'], [1, 1])
            self.assertEqual(d3['assigned_mean_difference_bounds'], [-1, -1])

    def test_interaction_bounds_preserve_partial_quad_information(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = [NetworkCase(fixture=0), NetworkCase(fixture=1)]
            model = setup_campaign(root, cases)[0]
            for case in cases:
                add_result(root, case, model)
            settings = {'continuation_steps': [0, 8], 'audits': ['whole', 'final'], 'reminders': ['none']}
            values = {cases[0].id: {'d0-final-none': 0, 'd8-final-none': 1,
                                   'd0-whole-none': 0, 'd8-whole-none': 0},
                      cases[1].id: {'d0-final-none': 1, 'd8-final-none': None,
                                   'd0-whole-none': 1, 'd8-whole-none': 0}}
            expand_reports(root, settings, values)
            metric = summarize_network(root)['strata'][0]['duration_audit_interactions']['d8-none']['metrics']['false_activation_denial']
            self.assertEqual(metric['assigned_histories'], 2)
            self.assertEqual(metric['complete_histories'], 1)
            self.assertEqual(metric['missing_terms'], 1)
            self.assertEqual(metric['assigned_mean_difference_bounds'], [.5, 1])
            self.assertEqual(metric['histories_by_number_of_observed_terms'], {'4': 1, '3': 1})

    def test_stress_interaction_uses_assigned_controls_and_missing_result_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = [NetworkCase(scenario=s) for s in ('fair', 'blocked', 'pressured_fair', 'poisoned')]
            model = setup_campaign(root, cases)[0]
            # Poisoned result remains unstarted; the other three assigned arms stay informative.
            for case in cases[:-1]:
                value = case.scenario in ('fair', 'blocked')
                add_result(root, case, model, observed(value), observed(value))
            summary = summarize_network(root)
            self.assertEqual(len(summary['stress_interactions']), 1)
            interaction = summary['stress_interactions'][0]
            self.assertEqual(interaction['matched_four_scenario_groups'], 1)
            metric = interaction['report_cells']['d0-whole-none']['metrics']['false_activation_denial']
            self.assertEqual(metric['complete_histories'], 0)
            self.assertEqual(metric['assigned_mean_difference_bounds'], [0, 1])
            self.assertEqual(metric['missing_terms'], 1)


if __name__ == '__main__':
    unittest.main()
