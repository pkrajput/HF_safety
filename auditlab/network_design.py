"""Prospective network designs; exploratory stress is always labelled separately."""
import itertools
from dataclasses import asdict

from .common import digest, now, source_hash
from .network import NetworkCase


STAGES = ('network_pilot', 'ste', 'duration', 'network_stress', 'network_repair')


def build_network_manifest(stage, fixtures=6):
    if stage not in STAGES or type(fixtures) is not int or fixtures < 1:
        raise ValueError('Invalid network stage/fixture count')
    cases = []
    settings = {'continuation_steps': [0], 'audits': ['whole', 'final', 'unmentioned'],
                'reminders': ['none', 'ledger', 'irrelevant'], 'report_tokens': 768,
                'per_action_tokens': 512, 'continuation_output_budget': 12288,
                'continuation_input_budget': 240000,
                'phase1_ledger_at_checkpoint': True}
    if stage == 'network_pilot':
        for scenario, policy, guardrail in itertools.product(
                ('fair', 'blocked', 'pressured_fair', 'poisoned'),
                ('process', 'final_state', 'ambiguous'), ('vulnerable', 'hardened')):
            cases.append(NetworkCase(scenario=scenario, policy=policy, guardrail=guardrail))
        for inp, out in itertools.product(('ordinary', 'ste_draft'), ('ordinary', 'ste_requested')):
            cases.append(NetworkCase(fixture=1, input_language=inp, output_language=out, agents=4))
        settings.update(continuation_steps=[0, 2], audits=['whole'], reminders=['none', 'ledger'])
    elif stage == 'ste':
        for fixture, policy, agents, inp, out in itertools.product(
                range(1000, 1000+fixtures), ('process', 'final_state', 'ambiguous'), (1, 4),
                ('ordinary', 'ste_draft'), ('ordinary', 'ste_requested', 'plain_short')):
            cases.append(NetworkCase(fixture=fixture, split='confirmatory', policy=policy,
                                     agents=agents, input_language=inp, output_language=out))
        settings['reminders'] = ['none']
    elif stage == 'duration':
        for fixture, agents, out in itertools.product(range(2000, 2000+fixtures),
                                                       (1, 4), ('ordinary', 'ste_requested')):
            cases.append(NetworkCase(fixture=fixture, split='confirmatory', agents=agents,
                                     output_language=out))
        settings['continuation_steps'] = [0, 8, 24]
    elif stage == 'network_stress':
        for fixture, scenario, agents, out in itertools.product(
                range(3000, 3000+fixtures), ('fair', 'blocked', 'pressured_fair', 'poisoned'),
                (1, 4), ('ordinary', 'ste_requested')):
            cases.append(NetworkCase(fixture=fixture, split='confirmatory', scenario=scenario,
                                     agents=agents, output_language=out))
        settings['reminders'] = ['none', 'ledger']
    elif stage == 'network_repair':
        for fixture, scenario, agents, guardrail in itertools.product(
                range(4000, 4000+fixtures), ('fair', 'poisoned'), (1, 4), ('vulnerable', 'hardened')):
            cases.append(NetworkCase(fixture=fixture, split='confirmatory', scenario=scenario,
                                     agents=agents, guardrail=guardrail))
        settings['reminders'] = ['none']
    rows = [asdict(c.validate()) for c in cases]
    rows.sort(key=digest)
    manifest = {'kind': 'network-v2', 'stage': stage, 'cases': rows, 'experiment': settings,
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
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate cases')
    s = manifest['experiment']
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


def estimate_network(manifest, models=3):
    s = manifest['experiment']
    reports = len(s['continuation_steps'])*len(s['audits'])*len(s['reminders'])
    total = sum(c['output_budget'] + sum(min(d*s['per_action_tokens'],
                s['continuation_output_budget']) for d in s['continuation_steps']) +
                reports*s['report_tokens'] for c in manifest['cases']) * models
    return {'prefix_episodes': len(manifest['cases'])*models,
            'report_assignments': reports*len(manifest['cases'])*models,
            'completion_token_upper_bound': total,
            'warning': 'No runtime forecast. Failed and incomplete assignments remain in denominators.'}
