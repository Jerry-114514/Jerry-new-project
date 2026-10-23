from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from build_execution_development import development_tasks
from intentlab.contracts import transform, validate_operation
from intentlab.core import canonical
from intentlab.spec_reference import reference_files


class AdditionalOperationTests(unittest.TestCase):
    def compare(self, rows, operation, expected):
        original = deepcopy(rows)
        validate_operation(operation)
        actual = transform(rows, operation)
        self.assertEqual(canonical(actual), canonical(expected))
        task = deepcopy(development_tasks()[0][0])
        task['inputs'] = {'input/data.json': rows}
        task['spec']['required_fields'] = []
        task['spec']['operation'] = operation
        independent = reference_files(task)[task['output_path']]
        self.assertEqual(canonical(independent), canonical(expected))
        self.assertEqual(rows, original)

    def test_exact_calendar_dates_include_low_year_and_leap_day(self):
        self.compare([{'d':'0042-01-02'}, {'d':'2024-02-29'}],
            {'name':'date_format','field':'d','input_format':'%Y-%m-%d','output_format':'%d.%m.%Y'},
            [{'d':'02.01.0042'}, {'d':'29.02.2024'}])
        for value in ('2023-02-29', '2024-2-01', '2024-02-01 '):
            with self.assertRaises(ValueError):
                transform([{'d':value}], {'name':'date_format','field':'d','input_format':'%Y-%m-%d','output_format':'%Y%m%d'})

    def test_stable_unique_preserves_types_signed_zero_and_first_record(self):
        values = [True, 1, '1', None, {'a':1}, [1, False], 0.0, -0.0, True, {'a':1}, [1, False]]
        rows = [{'i':i,'key':value} for i,value in enumerate(values)]
        self.compare(rows, {'name':'stable_unique','field':'key'}, rows[:8])

    def test_conditional_sum_has_case_sensitive_groups_and_first_qualifying_order(self):
        rows = [{'g':'B','v':-1}, {'g':'a','v':2}, {'g':'B','v':3}, {'g':'a','v':0}, {'g':'A','v':4}]
        op = {'name':'conditional_group_sum','group_field':'g','value_field':'v','minimum':0}
        self.compare(rows, op, [{'group':'a','total':2}, {'group':'B','total':3}, {'group':'A','total':4}])
        for value in (True, 1.5, 2**31):
            with self.assertRaises(ValueError):
                transform([{'g':'a','v':value}], op)
