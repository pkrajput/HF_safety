"""Descriptive episode-clustered summaries; no intent labels or population-wide claims."""
import math
import random
from collections import defaultdict
from pathlib import Path

from .common import Journal, read_json


def wilson(successes, total):
    if total == 0:
        return None
    z = 1.959963984540054
    p = successes/total
    denominator = 1+z*z/total
    center = (p+z*z/(2*total))/denominator
    radius = z*math.sqrt(p*(1-p)/total+z*z/(4*total*total))/denominator
    return [max(0, center-radius), min(1, center+radius)]


def bootstrap_mean(values, seed=731, repeats=2000):
    if not values:
        return None
    rng = random.Random(seed)
    means = sorted(sum(rng.choices(values, k=len(values)))/len(values) for _ in range(repeats))
    return [means[int(.025*repeats)], means[int(.975*repeats)]]


def summarize(root):
    groups, paired = defaultdict(list), defaultdict(list)
    results = []
    synthetic = 0
    for path in sorted(Path(root).rglob('result.json')):
        result = read_json(path)
        Journal.verify(path.parent/'events.jsonl')
        if result.get('synthetic'):
            synthetic += 1
        results.append(result)
        case = result['case']
        # Keep all manipulated dimensions; do not pool across models or agent counts.
        key = (result['model']['id'], case['task'], case['policy'], case['agents'],
               case['output_budget'], case['effort'], case['solvability'], case['guardrail'],
               case['permission'], case['audit_timing'], case['audit'],
               case.get('input_language', 'ordinary'), case.get('output_language', 'ordinary'))
        groups[key].append(result)
        reports = result['reports']
        if 'whole' in reports and 'final' in reports:
            a, b = reports['whole']['metrics'], reports['final']['metrics']
            if a['valid'] and b['valid']:
                paired[key].append((case['fixture'], int(b['false_access_denial'])-int(a['false_access_denial'])))
    rows = []
    for key, items in groups.items():
        fixture_differences = defaultdict(list)
        for fixture, difference in paired[key]:
            fixture_differences[fixture].append(difference)
        # Repetitions of the same fixture stay in one bootstrap cluster.
        diffs = [sum(v)/len(v) for v in fixture_differences.values()]
        row = {'stratum': key, 'episodes': len(items),
               'direct_read_rate': sum(x['facts']['direct_restricted_read'] for x in items)/len(items),
               'numeric_success_rate': sum(x['facts']['numeric_success'] for x in items)/len(items),
               'censored_episodes': sum(x['stop_reason'] != 'submitted' for x in items),
               'paired_report_episodes': len(paired[key]), 'paired_fixture_clusters': len(diffs),
               'false_denial_difference_final_minus_whole': sum(diffs)/len(diffs) if diffs else None,
               'fixture_bootstrap_95_interval': bootstrap_mean(diffs), 'report_metrics': {}}
        for audit in ('whole', 'final', 'unmentioned'):
            reports = [x['reports'][audit]['metrics'] for x in items if audit in x['reports']]
            valid = [x for x in reports if x['valid']]
            false = sum(x['false_access_denial'] for x in valid)
            row['report_metrics'][audit] = {'attempted': len(reports), 'valid': len(valid),
                'invalid': len(reports)-len(valid), 'false_access_denials': false,
                'rate_among_valid': false/len(valid) if valid else None,
                'rate_bounds_including_missing': [false/len(reports),
                    (false+len(reports)-len(valid))/len(reports)] if reports else None,
                'wilson_95_interval_among_valid': wilson(false, len(valid))}
        rows.append(row)
    return {'result_count': len(results), 'synthetic_results': synthetic,
            'infrastructure_errors': len(list(Path(root).rglob('error.json'))),
            'note': 'Descriptive strata only. No LLM-population inference. Invalid reports and '
                    'budget censoring are not classified as honest. Statistical intervals do '
                    'not correct discovery selection or multiple testing.', 'strata': rows}
