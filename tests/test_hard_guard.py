import unittest

from intentlab.actors import ScriptedActor
from intentlab.analysis import analyze
from intentlab.core import initial_state, public_task
from intentlab.fixtures import build_tasks
from intentlab.hard_guard import repair_hard_guard
from intentlab.runner import run_task


class HardGuardTests(unittest.TestCase):
    def test_write_then_restore_is_rejected_even_when_snapshot_matches(self):
        task = public_task(build_tasks()[1])
        before = initial_state(task)
        candidate = before.clone()
        name = next(iter(task['inputs']))
        candidate.apply([{'op': 'validate', 'ok': True},
                         {'op': 'write', 'path': name, 'value': []},
                         {'op': 'write', 'path': name, 'value': task['inputs'][name]}])
        self.assertEqual(before.files, candidate.files)
        self.assertEqual(repair_hard_guard(task, before, candidate), (False, 'hard_guard_input_mutation'))

    def test_failed_tool_check_allows_report_but_blocks_data_write(self):
        task = public_task(build_tasks()[4])
        before = initial_state(task)
        report = before.clone()
        report.apply([{'op': 'validate', 'ok': True},
                      {'op': 'write', 'path': task['report_path'], 'value': {'status': 'blocked'}}])
        self.assertFalse(report.events[0]['ok'])
        self.assertTrue(repair_hard_guard(task, before, report)[0])
        bad = report.clone()
        bad.apply([{'op': 'write', 'path': task['output_path'], 'value': []}])
        self.assertFalse(repair_hard_guard(task, before, bad)[0])

    def test_model_false_pass_cannot_commit_input_regression(self):
        task = build_tasks()[1]
        def false_input_pass(public, state, visible):
            findings = analyze(public, state, visible)
            for finding in findings:
                if finding['id'] == 'R_INPUT':
                    finding['status'] = 'satisfied'
            return findings
        result = run_task(task, ScriptedActor(), analyzer=false_input_pass)
        self.assertTrue(result['metrics']['compliant_success'])
        self.assertGreater(result['cost']['hard_rejections'], 0)
        self.assertFalse(any(e.get('path') in task['inputs'] for e in result['final_state']['events']))

    def test_mutation_without_prior_validation_is_rejected(self):
        task = public_task(build_tasks()[1])
        before = initial_state(task)
        candidate = before.clone()
        candidate.apply([{'op': 'write', 'path': task['output_path'], 'value': []}])
        self.assertEqual(repair_hard_guard(task, before, candidate), (False, 'hard_guard_validation_order'))

    def test_ablation_exposes_false_pass_regression_without_changing_model_gate(self):
        task = build_tasks()[1]
        def false_input_pass(public, state, visible):
            findings = analyze(public, state, visible)
            for finding in findings:
                if finding['id'] == 'R_INPUT':
                    finding['status'] = 'satisfied'
            return findings
        guarded = run_task(task, ScriptedActor(), analyzer=false_input_pass)
        unguarded = run_task(task, ScriptedActor(), analyzer=false_input_pass, hard_guard=False)
        self.assertTrue(guarded['metrics']['compliant_success'])
        self.assertFalse(unguarded['metrics']['compliant_success'])
        self.assertFalse(unguarded['hard_guard_enabled'])
        self.assertEqual(unguarded['cost']['hard_rejections'], 0)
        self.assertTrue(any(e.get('path') in task['inputs'] for e in unguarded['final_state']['events']))


if __name__ == '__main__':
    unittest.main()
