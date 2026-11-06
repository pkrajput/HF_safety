"""Collection counts describe fresh teams, not correlated reporting branches."""
import copy
import itertools
import unittest

from auditlab.common import digest
from auditlab.network import NetworkCase
from auditlab.network_design import (budget_profile_settings, build_network_manifest,
                                     estimate_network, network_counts,
                                     validate_network_manifest)


class NetworkDesignTests(unittest.TestCase):
    def test_default_design_preserves_mixed_team_counts(self):
        expected = {'ste': 216, 'duration': 24, 'network_stress': 96, 'network_repair': 48}
        for stage, total in expected.items():
            with self.subTest(stage=stage):
                manifest = build_network_manifest(stage)
                counts = network_counts(manifest)
                self.assertEqual(counts['prefix_episodes'], total)
                self.assertEqual(counts['swarm_episodes'], total//2)
                self.assertEqual(counts['solo_episodes'], total//2)
                self.assertEqual(counts['logical_agents'], total//2*5)
                validate_network_manifest(manifest)

    def test_frontier_campaign_has_384_fresh_swarms_per_target(self):
        expected = {'ste': (216, 648), 'duration': (24, 648),
                    'network_stress': (96, 576), 'network_repair': (48, 144)}
        total_teams = total_reports = total_agents = 0
        for stage, (teams, reports) in expected.items():
            with self.subTest(stage=stage):
                manifest = build_network_manifest(stage, fixtures=12, team_sizes=[4],
                                                  budget_profile='frontier')
                counts = network_counts(manifest)
                self.assertEqual(counts['swarm_episodes'], teams)
                self.assertEqual(counts['solo_episodes'], 0)
                self.assertEqual(counts['paired_report_assignments'], reports)
                self.assertEqual(counts['report_assignments'], reports)
                self.assertEqual(counts['logical_agents'], teams*4)
                scaled = estimate_network(manifest, models=3)
                for key, count in counts.items():
                    self.assertEqual(scaled[key], count*3)
                total_teams += counts['swarm_episodes']
                total_reports += counts['paired_report_assignments']
                total_agents += counts['logical_agents']
                validate_network_manifest(manifest)
        self.assertEqual((total_teams, total_reports, total_agents), (384, 2016, 1536))

    def test_solo_controls_are_separate_counts(self):
        counts = network_counts(build_network_manifest('duration', fixtures=12, team_sizes=[1]))
        self.assertEqual(counts['prefix_episodes'], 24)
        self.assertEqual(counts['solo_episodes'], 24)
        self.assertEqual(counts['swarm_episodes'], 0)
        self.assertEqual(counts['logical_agents'], 24)
        self.assertEqual(counts['paired_report_assignments'], 648)

    def test_repetitions_create_new_ids_without_changing_factor_balance(self):
        manifest = build_network_manifest('network_stress', fixtures=2, team_sizes=[4], repetitions=3)
        self.assertEqual(len(manifest['cases']), 48)
        ids = [NetworkCase(**case).id for case in manifest['cases']]
        self.assertEqual(len(set(ids)), 48)
        for repetition in range(3):
            cells = [case for case in manifest['cases'] if case['repetition'] == repetition]
            self.assertEqual(len(cells), 16)
            self.assertEqual({(case['fixture'], case['scenario'], case['output_language']) for case in cells},
                set(itertools.product((3000, 3001),
                    ('fair', 'blocked', 'pressured_fair', 'poisoned'), ('ordinary', 'ste_requested'))))
        validate_network_manifest(manifest)

    def test_pilot_keeps_all_controls_for_each_explicit_team_size(self):
        default = build_network_manifest('network_pilot')
        self.assertEqual(network_counts(default)['swarm_episodes'], 4)
        self.assertEqual(network_counts(default)['solo_episodes'], 24)
        expected_controls = set(itertools.product(
            ('fair', 'blocked', 'pressured_fair', 'poisoned'),
            ('process', 'final_state', 'ambiguous'), ('vulnerable', 'hardened')))
        for teams in ([1], [4], [1, 4]):
            with self.subTest(teams=teams):
                manifest = build_network_manifest('network_pilot', team_sizes=teams, repetitions=2)
                self.assertEqual(len(manifest['cases']), 28*len(teams)*2)
                for agents, repetition in itertools.product(teams, range(2)):
                    cells = [c for c in manifest['cases'] if c['agents'] == agents and
                             c['repetition'] == repetition]
                    controls = [c for c in cells if c['fixture'] == 0]
                    self.assertEqual({(c['scenario'], c['policy'], c['guardrail']) for c in controls},
                                     expected_controls)
                    languages = [c for c in cells if c['fixture'] == 1]
                    self.assertEqual({(c['input_language'], c['output_language']) for c in languages},
                        set(itertools.product(('ordinary', 'ste_draft'), ('ordinary', 'ste_requested'))))
                validate_network_manifest(manifest)

    def test_frontier_budget_profile_and_upper_bound(self):
        manifest = build_network_manifest('duration', fixtures=1, team_sizes=[4], budget_profile='frontier')
        settings = manifest['experiment']
        self.assertEqual(settings['budget_profile'], 'frontier')
        self.assertEqual(settings['per_action_tokens'], 8192)
        self.assertEqual(settings['report_tokens'], 8192)
        self.assertEqual(settings['continuation_output_budget'], 196608)
        self.assertEqual(settings['continuation_input_budget'], 2000000)
        for case in manifest['cases']:
            self.assertEqual(case['output_budget'], 131072)
            self.assertEqual(case['input_budget'], 2000000)
        # Two language arms, one immediate/8/24-opportunity continuation each,
        # and 27 independently requested reports per original team history.
        bound = 2*(131072 + 8*8192 + 24*8192 + 27*8192)
        self.assertEqual(estimate_network(manifest, models=1)['completion_token_upper_bound'], bound)
        changed = copy.deepcopy(manifest)
        changed['experiment']['continuation_output_budget'] = 8192
        self.assertEqual(estimate_network(changed, models=1)['completion_token_upper_bound'],
                         2*(131072 + 2*8192 + 27*8192))
        preset = budget_profile_settings('frontier')
        preset['per_action_tokens'] = 1
        self.assertEqual(budget_profile_settings('frontier')['per_action_tokens'], 8192)

    def test_invalid_collection_parameters_rejected(self):
        invalid = [dict(fixtures=0), dict(fixtures=True), dict(fixtures=1.5),
                   dict(repetitions=0), dict(repetitions=True), dict(repetitions=1.5),
                   dict(team_sizes=[]), dict(team_sizes=[4, 4]), dict(team_sizes=[2]),
                   dict(team_sizes=[True]), dict(team_sizes='4'), dict(team_sizes={4}),
                   dict(budget_profile='unknown'), dict(budget_profile=None)]
        for parameters in invalid:
            with self.subTest(parameters=parameters), self.assertRaises(ValueError):
                build_network_manifest('ste', **parameters)
        manifest = build_network_manifest('duration', fixtures=1)
        for models in (0, -1, True, 1.5, '3'):
            with self.subTest(models=models), self.assertRaises(ValueError):
                estimate_network(manifest, models=models)

    def test_manifest_metadata_and_case_duplicates_rejected(self):
        original = build_network_manifest('duration', fixtures=1)
        changes = [lambda m: m['cases'].append(copy.deepcopy(m['cases'][0])),
                   lambda m: m.update(cases=[]),
                   lambda m: m['design_parameters'].update(team_sizes=[4, 4]),
                   lambda m: m['design_parameters'].update(repetitions=0),
                   lambda m: m['design_parameters'].update(budget_profile='frontier')]
        for change in changes:
            manifest = copy.deepcopy(original)
            change(manifest)
            manifest['design_hash'] = digest({k: v for k, v in manifest.items() if k != 'design_hash'})
            with self.assertRaises(ValueError):
                validate_network_manifest(manifest)


if __name__ == '__main__':
    unittest.main()
