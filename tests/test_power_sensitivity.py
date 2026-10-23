import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('power_sensitivity',Path(__file__).resolve().parents[1]/'scripts/power_sensitivity.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PowerSensitivityTests(unittest.TestCase):
    def test_paired_normal_hand_calculation_and_no_approval(self):
        result=module.planning()
        row=next(r for r in result['normal_approximation_grid'] if r['source_groups']==200 and r['assumed_paired_task_sd']==0.2 and r['absolute_error_rate_effect']==0.05)
        # Signal-to-noise sqrt(200)*.05/.2 = 3.5355; two-sided z=1.96.
        self.assertAlmostEqual(row['normal_approx_power'],0.9424,places=3)
        self.assertEqual(row['normal_approx_sufficient_n'],126)
        self.assertFalse(result['formal_budget_approved'])
        self.assertFalse(result['data_files_read'])

    def test_conservative_bound_scaling_and_interpretation(self):
        result=module.planning()['distribution_free_sufficient_bound']
        effect=result['minimum_effect_at_n']
        self.assertAlmostEqual(effect['100']/effect['200'],2**0.5)
        self.assertTrue(0.31 < effect['200'] < 0.33)
        self.assertFalse(result['is_necessary_sample_size'])
        self.assertFalse(result['is_final_analysis_procedure'])

    def test_invalid_error_and_power_probabilities(self):
        for alpha,power in [(0,.8),(1,.8),(.05,.5),(.05,1)]:
            with self.assertRaises(ValueError):
                module.planning(alpha,power)
