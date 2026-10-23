from copy import deepcopy
import json
from pathlib import Path
import unittest

from intentlab.core import replay_events
from intentlab.history_coverage import history_views, missing_fields, select_tasks
from intentlab.procedural_data import generate
from intentlab.programmatic_labels import label_case


class HistoryCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        plan = json.loads(Path('configs/procedural-data-plan.json').read_text())
        plan['counts'] = {'train': 80, 'validation': 80, 'test': 80, 'ood': 20}
        seeds = {s: format(i + 1, '064x') for i, s in enumerate(plan['counts'])}
        cls.tasks, cls.refs, _, _ = generate(plan, seeds)

    def test_fixed_selection_ignores_order_and_has_all_available_strata(self):
        chosen = select_tasks(self.tasks)
        self.assertEqual(chosen, select_tasks(list(reversed(self.tasks))))
        expected = {(t['split'], t['family'], missing_fields(t)) for t in self.tasks}
        self.assertEqual(len(chosen), len(expected))
        self.assertEqual({(t['split'], t['family'], missing_fields(t)) for t in chosen}, expected)

    def test_same_final_files_do_not_erase_distant_input_violation(self):
        # Independent offline labeler and replay must distinguish the histories,
        # for both valid and already blocked sources in every operation family.
        for task in select_tasks(self.tasks):
            views = history_views(task, self.refs[task['id']])
            labels = [label_case(c, task, self.refs[task['id']]) for c in views]
            states = [{f['id']: f['status'] for f in row['findings']} for row in labels]
            self.assertEqual(states[0], dict.fromkeys(['R_INPUT','R_ORDER','R_RESULT','R_REPORT'],'satisfied'))
            self.assertEqual(states[1]['R_INPUT'], 'violated')
            self.assertEqual(states[1]['R_ORDER'], 'violated' if missing_fields(task) else 'satisfied')
            self.assertEqual(states[1]['R_RESULT'], 'satisfied')
            self.assertEqual(states[1]['R_REPORT'], 'satisfied')
            self.assertEqual(views[0]['public']['observation']['files'], views[1]['public']['observation']['files'])
            for case in views:
                obs = case['public']['observation']
                self.assertGreaterEqual(len(obs['events']), 31)
                self.assertEqual(replay_events(task, obs['events']).files, obs['files'])
                self.assertEqual(case['source']['trajectory'], 'injected')

    def test_tampered_early_tool_evidence_is_rejected(self):
        task = self.tasks[0]
        case = deepcopy(history_views(task, self.refs[task['id']])[1])
        case['public']['observation']['events'][1]['before'] = 'forged'
        with self.assertRaises(ValueError):
            label_case(case, task, self.refs[task['id']])
