from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_execution_development import development_tasks
from intentlab.core import initial_state
from intentlab.formal_data import read_jsonl
from intentlab.programmatic_labels import export_programmatic, generate_labels


class ProgrammaticLabelTests(unittest.TestCase):
    def setUp(self):
        self.tasks, rows = development_tasks()
        self.references = {r['task_id']: r for r in rows}
        self.task = next(t for t in self.tasks if t['spec']['operation']['name'] == 'copy')
        self.reference = self.references[self.task['id']]

    def case(self, task, state, visible=True, suffix='one'):
        return {'case_id': task['id'] + '-' + suffix, **{key: task[key] for key in ('source_task_id', 'split', 'family', 'template_id', 'source')},
            'public': {'request': task['request'], 'inputs': deepcopy(task['inputs']), 'requirements': deepcopy(task['requirements']),
                'execution_spec': deepcopy(task['spec']), 'observation': {'files': deepcopy(state.files), 'events': deepcopy(state.events) if visible else None}}}

    def actions(self, task):
        fields_ok = all(k in row for rows in task['inputs'].values() for row in rows for k in task['spec']['required_fields'])
        return [{'op': 'validate', 'ok': fields_ok}] + [{'op': 'write', 'path': p, 'value': deepcopy(v)} for p, v in self.references[task['id']]['files'].items()]

    def statuses(self, task, state, visible=True):
        rows = generate_labels([self.case(task, state, visible)], [task], {task['id']: self.references[task['id']]})
        return {r['id']: r['status'] for r in rows[0]['findings']}

    def test_static_solution_without_online_solver_and_hidden_history(self):
        state = initial_state(self.task)
        state.apply(self.actions(self.task))
        with patch('intentlab.contracts.transform', side_effect=AssertionError('online transform read')), \
             patch('intentlab.execution_analysis.analyze_execution', side_effect=AssertionError('online labels read')), \
             patch('intentlab.execution_oracle.evaluate_execution', side_effect=AssertionError('shared oracle read')):
            self.assertEqual(set(self.statuses(self.task, state).values()), {'satisfied'})
            hidden = self.statuses(self.task, state, False)
        self.assertEqual(hidden['R_INPUT'], 'unknown')
        self.assertEqual(hidden['R_ORDER'], 'unknown')
        self.assertEqual(hidden['R_RESULT'], 'satisfied')

    def test_restoration_cannot_erase_visible_violation(self):
        state = initial_state(self.task)
        path = next(iter(self.task['inputs']))
        state.apply(self.actions(self.task) + [{'op': 'write', 'path': path, 'value': []}, {'op': 'write', 'path': path, 'value': self.task['inputs'][path]}])
        self.assertEqual(self.statuses(self.task, state)['R_INPUT'], 'violated')
        self.assertEqual(self.statuses(self.task, state, False)['R_INPUT'], 'unknown')
        state.apply([{'op': 'write', 'path': path, 'value': []}])
        self.assertEqual(self.statuses(self.task, state, False)['R_INPUT'], 'violated')

    def test_missing_artifact_and_report_truth_are_separate(self):
        state = initial_state(self.task)
        state.apply(self.actions(self.task))
        state.apply([{'op': 'write', 'path': self.task['output_path'], 'value': []}, {'op': 'write', 'path': self.task['report_path'], 'value': {'status': 'ok', 'input_rows': sum(map(len, self.task['inputs'].values())), 'output_rows': 0}}])
        statuses = self.statuses(self.task, state)
        self.assertEqual(statuses['R_RESULT'], 'violated')
        self.assertEqual(statuses['R_REPORT'], 'satisfied')
        state.apply([{'op': 'delete', 'path': self.task['output_path']}])
        self.assertEqual(self.statuses(self.task, state, False)['R_RESULT'], 'violated')

    def test_rejects_forged_history_and_binding_changes(self):
        state = initial_state(self.task)
        state.apply(self.actions(self.task))
        case = self.case(self.task, state)
        case['public']['observation']['events'][0]['ok'] = False
        with self.assertRaisesRegex(ValueError, 'Recorded event'):
            generate_labels([case], [self.task], {self.task['id']: self.reference})
        case = self.case(self.task, state)
        case['public']['request'] += ' altered'
        with self.assertRaisesRegex(ValueError, 'contract differs'):
            generate_labels([case], [self.task], {self.task['id']: self.reference})

    def test_report_count_types_and_program_generated_origin(self):
        task = deepcopy(self.task)
        task['source']['origin'] = 'program_generated'
        state = initial_state(task)
        state.apply(self.actions(task))
        report = deepcopy(state.files[task['report_path']])
        report['output_rows'] = str(report['output_rows'])
        state.apply([{'op': 'write', 'path': task['report_path'], 'value': report}])
        self.assertEqual(self.statuses(task, state)['R_REPORT'], 'violated')

    def test_all_eight_families_and_machine_export_without_human_fields(self):
        cases = []
        for task in self.tasks:
            state = initial_state(task)
            state.apply(self.actions(task))
            cases.append(self.case(task, state))
            self.assertEqual(set(self.statuses(task, state).values()), {'satisfied'})
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'export'
            manifest = export_programmatic(cases, self.tasks, self.references, out)
            self.assertEqual(manifest['human_reviews_completed'], 0)
            self.assertFalse(manifest['human_evaluation_claim'])
            self.assertFalse(manifest['protocol_frozen'])
            labels = read_jsonl(out / 'programmatic-labels.jsonl')
            self.assertTrue(all('human_verified' not in row and 'reviewer' not in row for row in labels))
            for split in ('test', 'ood'):
                self.assertFalse((out / (split + '.jsonl')).exists())
                if any(c['split'] == split for c in cases):
                    self.assertTrue((out / 'heldout' / split / 'gold.jsonl').is_file())


if __name__ == '__main__':
    unittest.main()
