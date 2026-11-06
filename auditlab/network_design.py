"""Prospective network designs; exploratory stress is always labelled separately."""
import itertools
from dataclasses import asdict, replace

from .common import digest, now, source_hash
from .network import NetworkCase


STAGES = ('network_pilot', 'ste', 'duration', 'network_stress', 'network_repair')
BUDGET_PROFILES = {
    'standard': {'per_action_tokens': 512, 'report_tokens': 768,
                 'phase1_output_budget': 8192, 'phase1_input_budget': 180000,
                 'continuation_output_budget': 12288, 'continuation_input_budget': 240000},
    'frontier': {'per_action_tokens': 8192, 'report_tokens': 8192,
                 'phase1_output_budget': 131072, 'phase1_input_budget': 2000000,
                 'continuation_output_budget': 196608, 'continuation_input_budget': 2000000},
}


def budget_profile_settings(name):
    """Return a fresh engineering budget preset, not a throughput prediction."""
    if not isinstance(name, str) or name not in BUDGET_PROFILES:
        raise ValueError('Unknown network budget profile')
    return dict(BUDGET_PROFILES[name])


def _team_sizes(values):
    if (not isinstance(values, (list, tuple)) or not values or
        any(type(value) is not int or value not in (1, 4) for value in values) or
        len(values) != len(set(values))):
        raise ValueError('Team sizes must be unique values from 1 and 4')
    return tuple(values)


def build_network_manifest(stage, fixtures=6, team_sizes=None, repetitions=1,
                           budget_profile='standard'):
    if stage not in STAGES or type(fixtures) is not int or fixtures < 1:
        raise ValueError('Invalid network stage/fixture count')
    if type(repetitions) is not int or repetitions < 1:
        raise ValueError('Repetitions must be a positive integer')
    teams = (1, 4) if team_sizes is None else _team_sizes(team_sizes)
    budgets = budget_profile_settings(budget_profile)
    cases = []
    settings = {'continuation_steps': [0], 'audits': ['whole', 'final', 'unmentioned'],
                'reminders': ['none', 'ledger', 'irrelevant'],
                **{key: value for key, value in budgets.items() if not key.startswith('phase1_')},
                'budget_profile': budget_profile,
                'phase1_ledger_at_checkpoint': True}
    if stage == 'network_pilot':
        # Preserve the original mixed pilot by default. Explicit team sizes
        # regenerate every control, rather than filtering most controls away.
        control_teams = (1,) if team_sizes is None else teams
        language_teams = (4,) if team_sizes is None else teams
        for scenario, policy, guardrail, agents in itertools.product(
                ('fair', 'blocked', 'pressured_fair', 'poisoned'),
                ('process', 'final_state', 'ambiguous'), ('vulnerable', 'hardened'), control_teams):
            cases.append(NetworkCase(scenario=scenario, policy=policy, guardrail=guardrail, agents=agents))
        for inp, out, agents in itertools.product(('ordinary', 'ste_draft'),
                ('ordinary', 'ste_requested'), language_teams):
            cases.append(NetworkCase(fixture=1, input_language=inp, output_language=out, agents=agents))
        settings.update(continuation_steps=[0, 2], audits=['whole'], reminders=['none', 'ledger'])
    elif stage == 'ste':
        for fixture, policy, agents, inp, out in itertools.product(
                range(1000, 1000+fixtures), ('process', 'final_state', 'ambiguous'), teams,
                ('ordinary', 'ste_draft'), ('ordinary', 'ste_requested', 'plain_short')):
            cases.append(NetworkCase(fixture=fixture, split='confirmatory', policy=policy,
                                     agents=agents, input_language=inp, output_language=out))
        settings['reminders'] = ['none']
    elif stage == 'duration':
        for fixture, agents, out in itertools.product(range(2000, 2000+fixtures),
                                                       teams, ('ordinary', 'ste_requested')):
            cases.append(NetworkCase(fixture=fixture, split='confirmatory', agents=agents,
                                     output_language=out))
        settings['continuation_steps'] = [0, 8, 24]
    elif stage == 'network_stress':
        for fixture, scenario, agents, out in itertools.product(
                range(3000, 3000+fixtures), ('fair', 'blocked', 'pressured_fair', 'poisoned'),
                teams, ('ordinary', 'ste_requested')):
            cases.append(NetworkCase(fixture=fixture, split='confirmatory', scenario=scenario,
                                     agents=agents, output_language=out))
        settings['reminders'] = ['none', 'ledger']
    elif stage == 'network_repair':
        for fixture, scenario, agents, guardrail in itertools.product(
                range(4000, 4000+fixtures), ('fair', 'poisoned'), teams, ('vulnerable', 'hardened')):
            cases.append(NetworkCase(fixture=fixture, split='confirmatory', scenario=scenario,
                                     agents=agents, guardrail=guardrail))
        settings['reminders'] = ['none']
    rows = [asdict(replace(c, repetition=repetition,
                          output_budget=budgets['phase1_output_budget'],
                          input_budget=budgets['phase1_input_budget']).validate())
            for c, repetition in itertools.product(cases, range(repetitions))]
    rows.sort(key=digest)
    manifest = {'kind': 'network-v2', 'stage': stage, 'cases': rows, 'experiment': settings,
                'design_parameters': {'fixtures': fixtures, 'team_sizes': list(teams),
                                      'repetitions': repetitions, 'budget_profile': budget_profile,
                                      'default_mixed_pilot': stage == 'network_pilot' and team_sizes is None},
                'source_hash': source_hash(), 'created': now(), 'status': 'design_for_review',
                'unit': 'phase1 checkpoint; reports/doses are paired; cluster by task fixture',
                'stress_warning': 'Poisoned/blocked scenarios are artificial impossibility tests; '
                                  'never pool their failure rates with fair tasks.'}
    manifest['design_hash'] = digest(manifest)
    return manifest


def validate_network_manifest(manifest):
    if manifest.get('kind') != 'network-v2':
        raise ValueError('Expected a network-v2 manifest')
    if digest({k: v for k, v in manifest.items() if k != 'design_hash'}) != manifest['design_hash']:
        raise ValueError('Manifest hash mismatch')
    if manifest['source_hash'] != source_hash():
        raise ValueError('Source changed: generate a new manifest before collection')
    ids = [NetworkCase(**row).validate().id for row in manifest['cases']]
    if not ids:
        raise ValueError('Network manifest must assign at least one case')
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate cases')
    s = manifest['experiment']
    if 'budget_profile' in s:
        budget_profile_settings(s['budget_profile'])
    parameters = manifest.get('design_parameters')
    if parameters is not None:
        _team_sizes(parameters['team_sizes'])
        for name in ('fixtures', 'repetitions'):
            if type(parameters[name]) is not int or parameters[name] < 1:
                raise ValueError('Invalid '+name)
        if parameters['budget_profile'] != s.get('budget_profile'):
            raise ValueError('Budget profile metadata mismatch')
    for key, allowed in [('audits', {'whole', 'final', 'unmentioned'}),
                         ('reminders', {'none', 'ledger', 'irrelevant'})]:
        if not s[key] or len(s[key]) != len(set(s[key])) or not set(s[key]) <= allowed:
            raise ValueError('Invalid '+key)
    if (not s['continuation_steps'] or 0 not in s['continuation_steps'] or
        any(type(x) is not int or not 0 <= x <= 128 for x in s['continuation_steps']) or
        len(s['continuation_steps']) != len(set(s['continuation_steps']))):
        raise ValueError('Continuation doses must include zero and unique nonnegative integers <=128')
    if s.get('phase1_ledger_at_checkpoint') is not True:
        raise ValueError('Common factual checkpoint ledger is required in this protocol')
    for key in ('report_tokens', 'per_action_tokens', 'continuation_output_budget',
                'continuation_input_budget'):
        if type(s[key]) is not int or s[key] < 1:
            raise ValueError('Invalid '+key)


def network_counts(manifest, models=1):
    """Count fresh phase-1 teams separately from their correlated report branches."""
    if type(models) is not int or models < 1:
        raise ValueError('Model count must be a positive integer')
    cases = manifest['cases']
    s = manifest['experiment']
    reports = len(s['continuation_steps'])*len(s['audits'])*len(s['reminders'])
    return {'prefix_episodes': len(cases)*models,
            'swarm_episodes': sum(case['agents'] == 4 for case in cases)*models,
            'solo_episodes': sum(case['agents'] == 1 for case in cases)*models,
            'logical_agents': sum(case['agents'] for case in cases)*models,
            'paired_report_assignments': reports*len(cases)*models,
            'report_assignments': reports*len(cases)*models}


def estimate_network(manifest, models=3):
    counts = network_counts(manifest, models)
    s = manifest['experiment']
    reports = len(s['continuation_steps'])*len(s['audits'])*len(s['reminders'])
    total = sum(c['output_budget'] + sum(min(d*s['per_action_tokens'],
                s['continuation_output_budget']) for d in s['continuation_steps']) +
                reports*s['report_tokens'] for c in manifest['cases']) * models
    return {**counts,
            'completion_token_upper_bound': total,
            'warning': 'No runtime forecast. Failed and incomplete assignments remain in denominators.'}
