"""Descriptive error decomposition; never changes the operational JSON gate.

The alternate JSON normalization is post-hoc and must not be presented as a
preregistered primary metric or as a stronger-prompt baseline experiment.
"""
import argparse
from collections import Counter
import json
from pathlib import Path

from intentlab.model_backend import json_response
from intentlab.report import save_json

IDS = {'R_INPUT', 'R_ORDER', 'R_RESULT', 'R_REPORT'}


def statuses(text):
    value = json_response(text)
    if 'findings' in value:
        rows = value['findings']
    elif IDS.issubset(value):
        if any(value[rid].get('id', rid) != rid for rid in IDS):
            raise ValueError('Conflicting requirement ID')
        rows = [dict(value[rid], id=rid) for rid in sorted(IDS)]
    else:
        raise ValueError('No supported requirement JSON layout')
    if not isinstance(rows, list) or len(rows) != 4:
        raise ValueError('Need four findings')
    result = {}
    for row in rows:
        rid, status = row['id'], row['status']
        if rid not in IDS or rid in result or status not in {'satisfied', 'violated', 'unknown'}:
            raise ValueError('Invalid requirement judgment')
        result[rid] = status
    return result


def analyze(path):
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    counts = Counter(samples=len(rows))
    errors = Counter()
    cases = []
    for row in rows:
        errors[row.get('error', 'valid')] += 1
        try:
            predicted = statuses(row['text'])
            counts['normalizable_samples'] += 1
        except (ValueError, TypeError, KeyError):
            predicted = {}
            counts['unparsable_samples'] += 1
        correct = 0
        for rid, target in row['gold'].items():
            expected = target['status']
            actual = predicted.get(rid)
            counts['gold_' + expected] += 1
            counts['correct_' + expected] += actual == expected
            correct += actual == expected
            if rid in {'R_INPUT', 'R_ORDER'} and expected in {'unknown', 'violated'}:
                counts['unsafe_hard_requirement_opportunities'] += 1
                counts['unsafe_hard_requirement_passes'] += actual == 'satisfied'
        counts['correct_statuses'] += correct
        counts['exact_samples'] += correct == 4
        cases.append({'task_id': row['task_id'], 'kind': row['kind'], 'events_visible': row['events_visible'],
                      'correct_statuses': correct, 'prediction': predicted,
                      'gold': {rid: r['status'] for rid, r in row['gold'].items()}})
    return {**dict(counts), 'task_groups': len({r['task_id'] for r in rows}),
            'status_error_rate': 1 - counts['correct_statuses'] / (len(rows) * 4),
            'strict_error_reasons': dict(errors), 'cases': cases,
            'warning': 'Post-hoc descriptive normalization of two JSON layouts. Evidence support is not scored here. Operational strict-gate metrics remain unchanged.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    if not (args.root / 'completed.json').exists():
        raise ValueError('Wait for the complete pilot before comparing models')
    summaries = {path.parent.name: analyze(path) for path in sorted(args.root.glob('*/diagnostic-records.jsonl'))}
    plan = json.loads((args.root / 'summary.json').read_text(encoding='utf-8'))
    if set(summaries) != {'base'} | {run['name'] for run in plan['runs']}:
        raise ValueError('Missing planned model evaluations')
    keys = lambda data: {(r['task_id'], r['kind'], r['events_visible']) for r in data['cases']}
    if any(keys(data) != keys(summaries['base']) for data in summaries.values()):
        raise ValueError('Model evaluations use different samples')
    save_json(args.root / 'error-decomposition.json', summaries)
    print(json.dumps({name: {k: v for k, v in data.items() if k != 'cases'} for name, data in summaries.items()}, indent=2))


if __name__ == '__main__':
    main()
