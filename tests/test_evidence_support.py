"""Public synthetic witnesses only; no formal cases, predictions or models."""
from copy import deepcopy
import importlib.util
import random
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_execution_development import development_tasks
from intentlab.core import initial_state
from intentlab.formal_data import evidence_catalog
from intentlab.programmatic_labels import generate_labels

spec = importlib.util.spec_from_file_location('witnesses', ROOT / 'scripts/evidence_support.py')
witnesses = importlib.util.module_from_spec(spec)
spec.loader.exec_module(witnesses)


def case_for(task, state, visible=True, suffix='development'):
    return {'case_id': task['id'] + '-' + suffix,
            **{key: deepcopy(task[key]) for key in ('source_task_id', 'split', 'family', 'template_id', 'source')},
            'public': {'request': task['request'], 'inputs': deepcopy(task['inputs']),
                       'requirements': deepcopy(task['requirements']), 'execution_spec': deepcopy(task['spec']),
                       'observation': {'files': deepcopy(state.files), 'events': deepcopy(state.events) if visible else None}}}


class EvidenceSupportTests(unittest.TestCase):
    def setUp(self):
        tasks, refs = development_tasks()
        self.task = next(t for t in tasks if t['spec']['operation']['name'] == 'copy')
        self.reference = next(r for r in refs if r['task_id'] == self.task['id'])
        self.path = next(iter(self.task['inputs']))

    def actions(self, task=None, reference=None):
        task, reference = task or self.task, reference or self.reference
        fields = all(key in row for rows in task['inputs'].values() for row in rows for key in task['spec']['required_fields'])
        return [{'op': 'validate', 'ok': fields}] + [
            {'op': 'write', 'path': path, 'value': deepcopy(value)} for path, value in reference['files'].items()]

    def ready(self):
        state = initial_state(self.task)
        state.apply(self.actions())
        return state

    def assess(self, context, rid, status, refs):
        finding = {'id': rid, 'status': status, 'evidence': refs}
        original = deepcopy(finding)
        result = context.assess(finding)
        self.assertEqual(finding, original)
        return result

    def test_valid_citations_do_not_imply_support(self):
        context = witnesses.EvidenceContext(case_for(self.task, self.ready()), self.task, self.reference)
        for rid, refs in [('R_INPUT', ['file:' + self.task['output_path']]),
                          ('R_ORDER', ['file:' + self.task['report_path']]),
                          ('R_RESULT', ['input:' + self.path]), ('R_REPORT', ['request'])]:
            result = self.assess(context, rid, 'satisfied', refs)
            self.assertTrue(result['citation_valid'])
            self.assertEqual(result['verdict'], 'insufficient')

    def test_complete_cited_history_reconstructs_uncited_files(self):
        state = self.ready()
        context = witnesses.EvidenceContext(case_for(self.task, state), self.task, self.reference)
        refs = ['event:' + str(e['index']) for e in state.events]
        for rid in context.rules:
            result = self.assess(context, rid, 'satisfied', refs)
            self.assertTrue(result['supported'])
            self.assertTrue(result['full_history_cited'])

    def test_restored_input_requires_the_mutation_witness(self):
        state = self.ready()
        index = len(state.events)
        state.apply([{'op': 'write', 'path': self.path, 'value': []},
                     {'op': 'write', 'path': self.path, 'value': self.task['inputs'][self.path]}])
        context = witnesses.EvidenceContext(case_for(self.task, state), self.task, self.reference)
        weak = self.assess(context, 'R_INPUT', 'satisfied', ['snapshot_paths', 'file:' + self.path])
        self.assertEqual(weak['verdict'], 'insufficient')
        strong = self.assess(context, 'R_INPUT', 'violated', ['event:' + str(index)])
        self.assertTrue(strong['supported'])
        self.assertEqual(strong['reason'], 'cited_input_mutation_event')

    def test_hidden_history_abstentions_and_forbidden_event_references(self):
        state = self.ready()
        context = witnesses.EvidenceContext(case_for(self.task, state, False), self.task, self.reference)
        abstention = self.assess(context, 'R_INPUT', 'unknown', [])
        self.assertFalse(abstention['support_assessed'])
        self.assertFalse(abstention['supported'])
        self.assertEqual(abstention['verdict'], 'abstention_not_scored')
        invalid = self.assess(context, 'R_ORDER', 'violated', ['event:0'])
        self.assertEqual(invalid['verdict'], 'invalid_reference')
        state.apply([{'op': 'write', 'path': self.path, 'value': []}])
        changed = witnesses.EvidenceContext(case_for(self.task, state, False), self.task, self.reference)
        self.assertTrue(self.assess(changed, 'R_INPUT', 'violated', ['file:' + self.path])['supported'])

    def test_missing_artifact_and_uncited_output_are_distinct(self):
        state = self.ready()
        context = witnesses.EvidenceContext(case_for(self.task, state, False), self.task, self.reference)
        self.assertEqual(self.assess(context, 'R_RESULT', 'satisfied', ['snapshot_paths'])['verdict'], 'insufficient')
        refs = ['snapshot_paths', 'file:' + self.task['output_path']]
        self.assertTrue(self.assess(context, 'R_RESULT', 'satisfied', refs)['supported'])
        state.apply([{'op': 'delete', 'path': self.task['output_path']}])
        missing = witnesses.EvidenceContext(case_for(self.task, state, False), self.task, self.reference)
        for rid in ('R_RESULT', 'R_REPORT'):
            self.assertTrue(self.assess(missing, rid, 'violated', ['snapshot_paths'])['supported'])

    def test_truthful_report_can_support_counts_while_result_is_wrong(self):
        state = self.ready()
        state.apply([{'op': 'write', 'path': self.task['output_path'], 'value': []},
                     {'op': 'write', 'path': self.task['report_path'], 'value': {
                         'status': 'ok', 'input_rows': sum(map(len, self.task['inputs'].values())), 'output_rows': 0}}])
        context = witnesses.EvidenceContext(case_for(self.task, state, False), self.task, self.reference)
        refs = ['file:' + self.task['output_path'], 'file:' + self.task['report_path']]
        self.assertTrue(self.assess(context, 'R_REPORT', 'satisfied', refs)['supported'])
        self.assertTrue(self.assess(context, 'R_RESULT', 'violated', refs)['supported'])
        bad_report = deepcopy(state.files[self.task['report_path']])
        bad_report['output_rows'] = False  # bool is not the integer count zero.
        state.apply([{'op': 'write', 'path': self.task['report_path'], 'value': bad_report}])
        changed = witnesses.EvidenceContext(case_for(self.task, state, False), self.task, self.reference)
        self.assertTrue(self.assess(changed, 'R_REPORT', 'violated', ['file:' + self.task['report_path']])['supported'])

    def test_order_witness_and_blocked_report_exception(self):
        state = initial_state(self.task)
        state.apply(self.actions()[1:] + self.actions()[:1])
        context = witnesses.EvidenceContext(case_for(self.task, state), self.task, self.reference)
        self.assertTrue(self.assess(context, 'R_ORDER', 'violated', ['event:0'])['supported'])
        blocked = deepcopy(self.task)
        del blocked['inputs'][self.path][0][blocked['spec']['required_fields'][0]]
        reference = {'task_id': blocked['id'], 'files': {blocked['report_path']: {
            'status': 'blocked', 'input_rows': sum(map(len, blocked['inputs'].values()))}}}
        state = initial_state(blocked)
        state.apply(self.actions(blocked, reference))
        context = witnesses.EvidenceContext(case_for(blocked, state), blocked, reference)
        refs = ['event:' + str(e['index']) for e in state.events]
        self.assertTrue(self.assess(context, 'R_ORDER', 'satisfied', refs)['supported'])
        self.assertTrue(self.assess(context, 'R_REPORT', 'satisfied', ['file:' + blocked['report_path']])['supported'])

    def test_binding_forgery_and_empty_known_judgment(self):
        case = case_for(self.task, self.ready())
        forged = deepcopy(case)
        forged['public']['observation']['events'][0]['ok'] = False
        with self.assertRaises(ValueError):
            witnesses.EvidenceContext(forged, self.task, self.reference)
        wrong = deepcopy(self.reference)
        wrong['task_id'] += '-wrong'
        with self.assertRaises(ValueError):
            witnesses.EvidenceContext(case, self.task, wrong)
        context = witnesses.EvidenceContext(case, self.task, self.reference)
        self.assertEqual(self.assess(context, 'R_REPORT', 'satisfied', [])['verdict'], 'insufficient')

    def test_sampled_certificates_agree_with_independent_development_labels(self):
        states = [self.ready(), initial_state(self.task)]
        for path in (self.path, self.task['output_path'], self.task['report_path']):
            state = self.ready()
            state.apply([{'op': 'delete', 'path': path}])
            states.append(state)
        state = self.ready()
        state.apply([{'op': 'write', 'path': self.path, 'value': []},
                     {'op': 'write', 'path': self.path, 'value': self.task['inputs'][self.path]}])
        states.append(state)
        rng = random.Random(17)
        checked = supported = 0
        for state in states:
            for visible in (True, False):
                case = case_for(self.task, state, visible)
                truth = {f['id']: f['status'] for f in generate_labels(
                    [case], [self.task], {self.task['id']: self.reference})[0]['findings']}
                context = witnesses.EvidenceContext(case, self.task, self.reference)
                catalog = sorted(evidence_catalog(case['public']))
                subsets = [catalog] + [[ref for ref in catalog if rng.getrandbits(1)] for _ in range(24)]
                # The witness kernel must not call a full-state status evaluator.
                with (patch('intentlab.programmatic_labels.label_case', side_effect=AssertionError('shared labeler')),
                      patch('intentlab.execution_analysis.analyze_execution', side_effect=AssertionError('online analyzer')),
                      patch('intentlab.execution_oracle.evaluate_execution', side_effect=AssertionError('execution oracle'))):
                    for refs in subsets:
                        for rid in context.rules:
                            result = self.assess(context, rid, 'satisfied', refs)
                            checked += 1
                            if refs == catalog and truth[rid] != 'unknown':
                                self.assertEqual(result['entailed_status'], truth[rid])
                            if result['entailed_status'] is not None:
                                supported += 1
                                self.assertEqual(result['entailed_status'], truth[rid], (rid, refs, result))
        self.assertEqual(checked, 1200)
        self.assertGreater(supported, 100)


if __name__ == '__main__':
    unittest.main()
