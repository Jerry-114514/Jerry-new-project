import copy
import importlib.util
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('resource_prompts', ROOT / 'scripts/audit_historical_resource_prompts.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def rows(split, family):
    names = ['train-a', 'train-b'] if split == 'train' else ['validation']
    return [{'task_id': ('hardware-probe-' if family == 'stress' else 'synthetic-supervised-logits-') + name,
             'prompt': ('Synthetic hardware stress input ' + name + '; no user task or requirement label.\n'
                        if family == 'stress' else 'Synthetic hardware input ' + name + '; no real task labels.\n') + ' x' * 8,
             'completion': '{"hardware_probe":"synthetic-no-task-label"}' if family == 'stress' else ' x' * 511}
            for name in names]


class HistoricalResourcePromptTests(unittest.TestCase):
    def test_duplicate_json_key_cannot_hide_other_content(self):
        with self.assertRaisesRegex(ValueError, 'Duplicate JSON key'):
            audit.decode_lines(b'{"prompt":"hidden input","prompt":" x"}\n')

    def test_both_complete_formats_and_splits(self):
        for split in ('train', 'validation'):
            for family in ('stress', 'supervised_logits'):
                result = audit.check_rows(rows(split, family), split, family)
                self.assertEqual(result['filler_repetitions'], [8] * result['rows'])
                self.assertTrue(result['complete_literal_format_matches'])

    def test_hidden_input_suffix_and_unicode_substitution_rejected(self):
        for text in (' x input/data.json [{"value":1}]', ' x\n', ' х', ' x\u200b', ''):
            values = rows('train', 'stress')
            prefix = values[0]['prompt'].split('\n', 1)[0] + '\n'
            values[0]['prompt'] = prefix + text
            with self.subTest(text=text), self.assertRaises(ValueError):
                audit.check_rows(values, 'train', 'stress')

    def test_extra_field_target_identity_and_population_rejected(self):
        original = rows('train', 'supervised_logits')
        for mode in ('extra', 'target', 'id', 'reorder', 'missing'):
            values = copy.deepcopy(original)
            if mode == 'extra':
                values[0]['inputs'] = {'input/data.json': [{'value': 1}]}
            if mode == 'target':
                values[0]['completion'] += ' x'
            if mode == 'id':
                values[0]['task_id'] = 'other-source'
            if mode == 'reorder':
                values.reverse()
            if mode == 'missing':
                values.pop()
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                audit.check_rows(values, 'train', 'supervised_logits')


if __name__ == '__main__':
    unittest.main()
