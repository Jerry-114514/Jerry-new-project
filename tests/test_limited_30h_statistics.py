from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from limited_30h_diagnostics import CONDITIONS,analyze,project


class LimitedStatisticsTests(unittest.TestCase):
    def data(self):
        cases=[{'case_id':f'case-{s}-{i}','source_task_id':f'source-{s}-{i}','split':s,'family':'family'} for s in ('test','ood') for i in range(4)]
        scores={k:{s:{'per_task_error_rate':{c['source_task_id']:.5 if k=='B' else .25 for c in cases if c['split']==s}} for s in ('test','ood')} for k in CONDITIONS}
        losses={k:[{**{n:c[n] for n in ('case_id','source_task_id','split')},'loss_sum':2 if k.startswith('D') else 3,'target_tokens':10} for c in cases] for k in CONDITIONS[3:]}
        return cases,scores,losses,{'bootstrap_seed':7,'bootstrap_samples':100,'permutation_samples':100}

    def test_fixed_three_seed_effects_and_separate_three_test_holm_family(self):
        r=analyze(*self.data())
        self.assertEqual(r['primary'],'RQ1/test');self.assertEqual(len(r['secondary_family']),3)
        self.assertEqual(r['comparisons']['RQ1/test']['right_minus_left'],-.25)
        self.assertAlmostEqual(r['comparisons']['CE/test']['right_minus_left'],.1)
        self.assertIsNone(r['comparisons']['RQ1/test']['holm_p_value'])

    def test_target_population_or_case_source_rebinding_is_rejected(self):
        cases,scores,losses,settings=self.data();wrong=deepcopy(losses)
        wrong['E-seed-0'][0]['target_tokens']=11
        with self.assertRaises(ValueError):analyze(cases,scores,wrong,settings)
        wrong=deepcopy(losses);wrong['D-seed-0'][0]['case_id'],wrong['D-seed-0'][1]['case_id']=wrong['D-seed-0'][1]['case_id'],wrong['D-seed-0'][0]['case_id']
        with self.assertRaises(ValueError):analyze(cases,scores,wrong,settings)

    def test_public_projection_removes_nested_source_and_case_records(self):
        self.assertEqual(project({'metrics':{'per_source_task':{'secret':1},'mean':.5},'records':[{'case_id':'secret'}]}),{'metrics':{'mean':.5}})


if __name__=='__main__':unittest.main()
