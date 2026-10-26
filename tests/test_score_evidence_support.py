"""Denominator and population checks on public synthetic development fixtures."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_execution_development import development_tasks
from score_evidence_support import aggregate, score_evidence_support
from test_evidence_support import case_for
from intentlab.core import canonical, initial_state
from intentlab.formal_data import evidence_catalog
from intentlab.programmatic_labels import generate_labels


class EvidenceBatchTests(unittest.TestCase):
    def setUp(self):
        tasks, refs = development_tasks()
        self.task = next(t for t in tasks if t['spec']['operation']['name'] == 'copy')
        self.ref = next(r for r in refs if r['task_id'] == self.task['id'])
        state = initial_state(self.task)
        state.apply([{'op': 'validate', 'ok': True}] + [
            {'op': 'write', 'path': p, 'value': deepcopy(v)} for p, v in self.ref['files'].items()])
        self.cases = [case_for(self.task, state, True, 'visible'),
                      case_for(self.task, state, False, 'hidden')]
        self.gold = {r['case_id']: r['findings'] for r in generate_labels(
            self.cases, [self.task], {self.task['id']: self.ref})}

    def prediction(self, case, unknown=False):
        return {'case_id': case['case_id'], 'text': json.dumps({'findings': [
            {'id': req['id'], 'status': 'unknown' if unknown else 'satisfied',
             'evidence': [] if unknown else sorted(evidence_catalog(case['public']))}
            for req in case['public']['requirements']]})}

    def score(self, predictions, **overrides):
        args = {'cases': self.cases, 'tasks': [self.task], 'references': [self.ref],
                'gold': self.gold, 'predictions': predictions}
        args.update(overrides)
        return score_evidence_support(**args)

    def test_missing_and_bad_formats_remain_in_all_denominators(self):
        result = self.score([{'case_id': self.cases[0]['case_id'], 'text': '{bad'}])
        self.assertEqual(result['missing_predictions'], 1)
        for mode in ('strict', 'normalized'):
            counts = result['summaries'][mode]['all']['counts']
            self.assertEqual(counts['items'], 8)
            self.assertEqual(counts['parse_failure_items'], 8)
            self.assertEqual(counts['missing_prediction_items'], 4)
            self.assertEqual(counts['gold_known'], 6)
            self.assertEqual(counts['gold_unknown'], 2)
            self.assertEqual(result['summaries'][mode]['all']['metrics'][
                'correct_and_supported_on_gold_known']['micro']['value'], 0)

    def test_abstention_cannot_inflate_supported_rate(self):
        result = self.score([self.prediction(c, True) for c in self.cases])
        summary = result['summaries']['normalized']['all']
        self.assertEqual(summary['counts']['supported'], 0)
        self.assertEqual(summary['counts']['abstention_on_known'], 6)
        self.assertEqual(summary['metrics']['unknown_recall']['micro']['value'], 1)
        self.assertIsNone(summary['metrics']['support_precision_on_model_known']['micro']['value'])
        self.assertEqual(summary['metrics']['unknown_reference_validity']['micro']['value'], 1)
        self.assertEqual(summary['metrics']['known_judgment_coverage']['micro']['value'], 0)

    def test_strict_and_normalized_are_retained_without_mutation(self):
        pred = self.prediction(self.cases[0])
        findings = json.loads(pred['text'])['findings']
        pred['text'] = json.dumps({f['id']: {k: v for k, v in f.items() if k != 'id'} for f in findings})
        before = canonical([self.cases, self.gold, pred])
        result = self.score([pred])
        self.assertEqual(result['summaries']['strict']['all']['counts']['parsed'], 0)
        self.assertEqual(result['summaries']['normalized']['all']['counts']['supported'], 4)
        self.assertEqual(canonical([self.cases, self.gold, pred]), before)
        self.assertEqual(canonical(self.score([pred])), canonical(result))

    def test_invalid_reference_and_contradiction_are_distinct(self):
        pred = self.prediction(self.cases[0])
        parsed = json.loads(pred['text'])
        parsed['findings'][0]['evidence'] = ['event:9999']
        parsed['findings'][1]['status'] = 'violated'
        pred['text'] = json.dumps(parsed)
        result = self.score([pred])
        counts = result['summaries']['strict']['all']['counts']
        self.assertEqual(counts['invalid_reference_items'], 1)
        self.assertEqual(counts['verdict_contradicted'], 1)
        self.assertEqual(counts['supported'], 2)

    def test_exact_population_and_binding_fail_closed(self):
        pred = self.prediction(self.cases[0])
        for predictions in ([pred, pred], [dict(pred, case_id='unknown')]):
            with self.assertRaises(ValueError):
                self.score(predictions)
        for overrides in ({'gold': {}}, {'references': []}, {'tasks': []}, {'cases': []}):
            with self.assertRaises(ValueError):
                self.score([], **overrides)
        forged = deepcopy(self.cases)
        forged[0]['public']['inputs']['input/data.json'][0]['amount'] += 1
        with self.assertRaises(ValueError):
            self.score([], cases=forged)

    def test_views_are_not_independent_tasks_and_null_denominators_stay_null(self):
        rows = [{'case_id': str(i), 'source_task_id': 'a' if i < 3 else 'b',
                 'counts': {'items': 4, 'correct_status': 4 if i < 3 else 0}}
                for i in range(4)]
        summary = aggregate(rows)
        metric = summary['metrics']['status_accuracy']
        self.assertEqual(metric['micro']['value'], .75)
        self.assertEqual(metric['task_equal_mean'], .5)
        self.assertEqual(metric['eligible_source_tasks'], 2)
        self.assertIsNone(summary['metrics']['unknown_recall']['task_equal_mean'])
        self.assertIsNone(summary['metrics']['unknown_recall']['micro']['value'])


if __name__ == '__main__':
    unittest.main()
