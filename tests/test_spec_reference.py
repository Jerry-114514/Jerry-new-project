from copy import deepcopy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from build_execution_development import development_tasks
from intentlab.spec_reference import reference_files, verify_references


class IndependentReferenceTests(unittest.TestCase):
    def test_all_eight_static_families_without_public_solver(self):
        tasks, rows = development_tasks()
        with patch('intentlab.contracts.transform', side_effect=AssertionError('Online solver read')):
            result = verify_references(tasks, {r['task_id']: r for r in rows})
        self.assertEqual(result['tasks'], 8)
        self.assertFalse(result['formal_proof'])

    def test_fraction_rounding_ties_negative_zero_and_exponents(self):
        tasks, _ = development_tasks()
        task = deepcopy(tasks[0])
        field = task['spec']['operation']['field']
        task['inputs'] = {'input/data.json': [{field: s} for s in ('2.675', '-2.675', '-0', '-0.0001', '1e-2')]}
        task['spec']['required_fields'] = [field]
        values = [r[field] for r in reference_files(task)[task['output_path']]]
        self.assertEqual(values, ['2.68', '-2.68', '-0.00', '-0.00', '0.01'])

    def test_ascii_projection_preserves_types_order_and_duplicates(self):
        tasks, _ = development_tasks()
        task = deepcopy(tasks[0])
        task['spec']['operation'] = {'name': 'ascii_filter_project', 'where_field': 'key', 'equals': 'a', 'fields': ['value']}
        task['spec']['required_fields'] = ['key', 'value']
        task['inputs'] = {'input/data.json': [{'key':'A','value':'001'}, {'key':'a','value':None}, {'key':'A','value':False}, {'key':'b','value':1}, {'key':'a','value':'001'}]}
        self.assertEqual(reference_files(task)[task['output_path']], [{'value':'001'}, {'value':None}, {'value':False}, {'value':'001'}])

    def test_reference_tampering_is_rejected(self):
        tasks, rows = development_tasks()
        references = {r['task_id']: deepcopy(r) for r in rows}
        references[tasks[0]['id']]['files'][tasks[0]['output_path']] = []
        with self.assertRaisesRegex(ValueError, 'disagreement'):
            verify_references(tasks, references)
