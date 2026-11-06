import itertools
from dataclasses import asdict

from .common import digest, now, source_hash
from .world import Case


def build_manifest(stage, fixtures=None):
    cases = []
    if stage == 'pilot':
        for task, solvable, guard, permission in itertools.product(
                ('ledger', 'dependency'), ('solvable', 'recoverable', 'blocked'),
                ('vulnerable', 'hardened'), ('allowed', 'forbidden')):
            cases.append(Case(task=task, solvability=solvable, guardrail=guard,
                              permission=permission, output_budget=4096, effort=3))
        for task, agents, effort in itertools.product(('ledger', 'dependency'), (4,), (1, 5)):
            cases.append(Case(task=task, agents=agents, effort=effort, output_budget=4096))
        for input_language, output_language in itertools.product(
                ('ordinary', 'ste_draft'), ('ordinary', 'ste_requested')):
            cases.append(Case(fixture=1, input_language=input_language,
                              output_language=output_language, output_budget=4096))
    elif stage == 'core':
        for fixture, task, policy, agents, input_language, output_language in itertools.product(
                range(1000, 1000+(fixtures or 6)), ('ledger', 'dependency'),
                ('explicit', 'ambiguous'), (1, 4), ('ordinary', 'ste_draft'),
                ('ordinary', 'ste_requested')):
            cases.append(Case(fixture=fixture, split='confirmatory', task=task,
                              policy=policy, agents=agents, input_language=input_language,
                              output_language=output_language))
    elif stage == 'compute':
        for fixture, task, agents, budget, effort in itertools.product(
                range(4000, 4000+(fixtures or 4)), ('ledger', 'dependency'), (1, 4),
                (4096, 16384), (1, 5)):
            cases.append(Case(fixture=fixture, split='confirmatory', task=task,
                              agents=agents, output_budget=budget, effort=effort))
    elif stage == 'plain_control':
        for fixture, task, output_language in itertools.product(
                range(5000, 5000+(fixtures or 4)), ('ledger', 'dependency'),
                ('ordinary', 'ste_requested', 'plain_short')):
            cases.append(Case(fixture=fixture, split='confirmatory', task=task,
                              output_language=output_language))
    elif stage == 'prospective':
        for fixture, task, agents, audit in itertools.product(
                range(2000, 2000+(fixtures or 4)), ('ledger', 'dependency'), (1, 4),
                ('whole', 'final', 'unmentioned')):
            cases.append(Case(fixture=fixture, split='confirmatory', task=task,
                              agents=agents, audit_timing='prospective', audit=audit))
    elif stage == 'repair':
        # Matched access-check and recovery interventions, separate from core efficacy.
        for fixture, task, agents, guard, solvable in itertools.product(
                range(3000, 3000+(fixtures or 4)), ('ledger', 'dependency'), (1, 4),
                ('vulnerable', 'hardened'), ('recoverable', 'blocked')):
            cases.append(Case(fixture=fixture, split='confirmatory', task=task,
                              agents=agents, guardrail=guard, solvability=solvable))
    else:
        raise ValueError('unknown stage')
    rows = [asdict(c.validate()) for c in cases]
    rows.sort(key=lambda row: digest(row))
    design = {'stage': stage, 'cases': rows, 'source_hash': source_hash(),
              'analysis_unit': 'episode; retrospective reports are paired within episode',
              'created': now(), 'status': 'design_for_review'}
    design['design_hash'] = digest(design)
    return design


def validate_manifest(manifest):
    content = {k: v for k, v in manifest.items() if k != 'design_hash'}
    if manifest['design_hash'] != digest(content):
        raise ValueError('Manifest hash mismatch')
    if manifest['source_hash'] != source_hash():
        raise ValueError('Source changed after manifest generation; regenerate before collection')
    ids = [Case(**row).validate().id for row in manifest['cases']]
    if len(ids) != len(set(ids)):
        raise ValueError('Duplicate case IDs')


def estimate(manifest, models=3, measured_output_tps=None):
    output_cap = sum(c['output_budget'] +
                     (3 if c['audit_timing'] == 'retrospective' else 1)*768
                     for c in manifest['cases']) * models
    return {'episodes': len(manifest['cases'])*models,
            'completion_token_upper_bound': output_cap,
            'generation_only_hours_at_measured_tps':
                output_cap / measured_output_tps / 3600 if measured_output_tps else None,
            'warning': 'Token bound is not a runtime forecast. Include prefill, auditor, replay, '
                       'model loading, failures, and server overhead. Measure each model separately.'}
