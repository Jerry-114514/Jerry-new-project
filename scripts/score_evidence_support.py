"""Supplementary offline citation assessment; no model calls or frozen score edits.

The caller must enforce experiment-completion and input-hash gates before using
formal records. This module deliberately has no ungated formal-data CLI.
"""
from collections import Counter, defaultdict
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence_support import EvidenceContext, VERSION
from intentlab.execution_data import validate_references, validate_tasks
from intentlab.formal_data import validate_cases, validate_findings
from intentlab.formal_eval import parse_prediction


METRICS = {
    'correct_and_supported_on_gold_known': ('correct_supported', 'gold_known'),
    'support_precision_on_model_known': ('supported', 'model_known'),
    'known_judgment_coverage': ('model_known', 'items'),
    'unknown_recall': ('correct_abstention', 'gold_unknown'),
    'abstention_on_gold_known': ('abstention_on_known', 'gold_known'),
    'unknown_reference_validity': ('valid_abstention_refs', 'model_unknown'),
    'status_accuracy': ('correct_status', 'items'),
    'parse_coverage': ('parsed', 'items'),
}


def fraction(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'value': numerator / denominator if denominator else None}


def aggregate(records):
    """Micro counts plus view means within source, then equally weighted sources."""
    counts = Counter()
    views = defaultdict(Counter)
    identities = {}
    for row in records:
        counts.update(row['counts'])
        views[row['case_id']].update(row['counts'])
        identities[row['case_id']] = row['source_task_id']
    metrics = {}
    for name, (numerator, denominator) in METRICS.items():
        groups = defaultdict(list)
        for cid, values in views.items():
            if values[denominator]:
                groups[identities[cid]].append(values[numerator] / values[denominator])
        means = {key: sum(values) / len(values) for key, values in sorted(groups.items())}
        metrics[name] = {'micro': fraction(counts[numerator], counts[denominator]),
                         'task_equal_mean': sum(means.values()) / len(means) if means else None,
                         'eligible_source_tasks': len(means),
                         'eligible_views': sum(map(len, groups.values())),
                         'per_source_task': means}
    return {'counts': dict(sorted(counts.items())), 'case_count': len(views),
            'source_task_count': len(set(identities.values())), 'metrics': metrics}


def score_evidence_support(cases, tasks, references, gold, predictions):
    """Assess one condition, retaining absent/malformed predictions in denominators.

    Inputs are decoded records; gold maps case IDs to findings. No labels are
    generated here. References cover exactly the supplied task population.
    """
    if not cases:
        raise ValueError('Nonempty assessment population required')
    validate_cases(cases)
    validate_tasks(tasks)
    refs = validate_references(references, tasks)
    by_source = {}
    for task in tasks:
        if task['source_task_id'] in by_source:
            raise ValueError('Ambiguous source task binding')
        by_source[task['source_task_id']] = task
    if set(by_source) != {row['source_task_id'] for row in cases}:
        raise ValueError('Tasks must cover exactly the case source population')
    by_case = {row['case_id']: row for row in cases}
    if not isinstance(gold, dict) or set(gold) != set(by_case):
        raise ValueError('Gold must cover exactly the assessment cases')
    indexed = {}
    for row in predictions:
        if not isinstance(row, dict) or set(row) != {'case_id', 'text'} \
                or row['case_id'] not in by_case or row['case_id'] in indexed:
            raise ValueError('Unknown, duplicate or malformed prediction record')
        indexed[row['case_id']] = row['text']
    records = []
    for cid, case in sorted(by_case.items()):
        task = by_source[case['source_task_id']]
        context = EvidenceContext(case, task, refs[task['id']])
        truth = validate_findings(gold[cid], case['public'])
        for mode, normalize in (('strict', False), ('normalized', True)):
            findings, error = {}, None
            try:
                findings = parse_prediction(indexed.get(cid), case['public']['requirements'], normalize)
            except (ValueError, TypeError, KeyError) as exc:
                error = type(exc).__name__
            for rid, target in sorted(truth.items()):
                predicted = findings.get(rid)
                assessment = context.assess(predicted) if predicted else None
                known = predicted is not None and predicted['status'] != 'unknown'
                abstention = predicted is not None and predicted['status'] == 'unknown'
                correct = predicted is not None and predicted['status'] == target['status']
                supported = assessment is not None and assessment['supported']
                gold_known = target['status'] != 'unknown'
                counts = {key: int(value) for key, value in {
                    'items': 1, 'gold_known': gold_known, 'gold_unknown': not gold_known,
                    'parsed': predicted is not None, 'parse_failure_items': predicted is None,
                    'missing_prediction_items': cid not in indexed,
                    'model_known': known, 'model_unknown': abstention,
                    'correct_status': correct, 'supported': supported,
                    'correct_supported': gold_known and correct and supported,
                    'correct_abstention': not gold_known and abstention,
                    'abstention_on_known': gold_known and abstention,
                    'valid_abstention_refs': abstention and assessment['citation_valid'],
                    'invalid_reference_items': assessment is not None and not assessment['citation_valid'],
                    'nonempty_reference_items': assessment is not None and assessment['citation_nonempty'],
                }.items()}
                if assessment is not None:
                    counts['verdict_' + assessment['verdict']] = 1
                records.append({'case_id': cid, 'source_task_id': case['source_task_id'],
                                'split': case['split'], 'rule': context.rules[rid],
                                'requirement_id': rid, 'mode': mode, 'gold_status': target['status'],
                                'parse_error': error, 'assessment': assessment, 'counts': counts})
    summaries = {}
    for mode in ('strict', 'normalized'):
        selected = [row for row in records if row['mode'] == mode]
        summaries[mode] = {'all': aggregate(selected),
                           'by_split': {split: aggregate([r for r in selected if r['split'] == split])
                                        for split in sorted({r['split'] for r in selected})},
                           'by_rule': {rule: aggregate([r for r in selected if r['rule'] == rule])
                                       for rule in sorted({r['rule'] for r in selected})},
                           'by_split_rule': {split: {
                               rule: aggregate([r for r in selected if r['split'] == split and r['rule'] == rule])
                               for rule in sorted({r['rule'] for r in selected if r['split'] == split})}
                               for split in sorted({r['split'] for r in selected})}}
    return {'version': VERSION, 'supplementary_exploratory': True,
            'frozen_scores_modified': False, 'confirmatory_p_values': False,
            'case_count': len(cases), 'prediction_count': len(indexed),
            'missing_predictions': len(cases) - len(indexed),
            'aggregation': 'view mean within source, then equal source means; null for empty eligible denominator',
            'summaries': summaries, 'records': records}
