import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from render_limited_training_curves import STEPS, public_histories, validate


class LimitedCurveTests(unittest.TestCase):
    def history(self):
        return [{'step':step, 'validation':{'loss':.02, 'target_tokens':215880},
                 'lr_used':5e-5} for step in STEPS]

    def test_missing_runs_are_not_zero_curves_and_first_tie_selected(self):
        result = validate({'D-seed-0':self.history()})
        self.assertEqual(result['completed_histories'], 1)
        self.assertEqual(len(result['histories_not_provided']), 5)
        self.assertEqual(result['selected_by_validation']['D-seed-0']['step'], 209)
        self.assertFalse(result['missing_histories_imputed'])

    def test_plateau_learning_rates_can_differ_between_seeds(self):
        a, b = self.history(), self.history()
        b[-1]['lr_used'] = 1e-5
        self.assertEqual(validate({'E-seed-0':a, 'E-seed-1':b})['completed_histories'], 2)

    def test_raw_row_metadata_is_not_serialized_in_public_history(self):
        rows = self.history()
        rows[0]['case_id'] = 'private-example'
        rows[0]['validation']['records'] = [{'answer':'private-answer'}]
        row = public_histories({'D-seed-0':rows})['D-seed-0'][0]
        self.assertEqual(set(row), {'step', 'validation', 'lr_used'})
        self.assertEqual(set(row['validation']), {'loss', 'target_tokens'})

    def test_incomplete_or_invalid_measurements_are_rejected(self):
        original = self.history()
        for mutate in (lambda r:r.pop(), lambda r:r[0]['validation'].update(loss=float('nan')),
                       lambda r:r[0]['validation'].update(target_tokens=133026)):
            rows = copy.deepcopy(original); mutate(rows)
            with self.assertRaises(ValueError):
                validate({'D-seed-0':rows})
