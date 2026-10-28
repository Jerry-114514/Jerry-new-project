import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from render_limited_training_curves import RUNS,STEPS
from summarize_limited_training_runs import summarize


class LimitedTrainingSummaryTests(unittest.TestCase):
    def fixture(self):
        configs={name:{'schedule':'cosine' if name.startswith('D-') else 'plateau', 'seed':int(name[-1]),
                       'data':'SECRET_DATA_PATH'} for name in RUNS}
        p={'jobs':{name:{'config':v} for name,v in configs.items()},'selected_view_counts':{'train':2500},
           'base_identity':'SECRET_BASE','training_data_hash':'SECRET_DATA_HASH','training':{'steps':1250},
           'training_supervised_tokens':389407,'validation_supervised_tokens':215880}
        def run(name):
            rows=[]
            for step in STEPS:
                rows.append({'step':step,'validation':{'loss':.02,'target_tokens':215880},'lr_used':5e-5,
                             'scheduler':None if name.startswith('D-') else {'old_lr':5e-5,'new_lr':5e-5,'lr':5e-5,'reduced':False},
                             'private_metadata':'SECRET_METADATA'})
            return {'completed':True,'test_deferred':True,'config':configs[name], 'base_identity':p['base_identity'],
                    'data_hash':p['training_data_hash'],'initial_trainable_sha256':'SECRET_INIT_'+name[-1],
                    'step':1250,'examples_seen':2500,'supervised_tokens':389407,'history':rows,
                    'sample_exposures':[{'index':i,'case_id':f'SECRET_CASE_{i}','count':1} for i in range(2500)],
                    'selection':{'rule':'minimum_validation_loss_first_tie','step':209,'validation_loss':.02,'validation_target_tokens':215880},
                    'seconds_this_invocation':10.,'peak_allocated_bytes':100,'peak_reserved_bytes':200}
        return p,{n:run(n) for n in ('D-seed-0','E-seed-0','D-seed-1')}

    def test_unpaired_run_is_retained_without_inventing_a_pair_or_private_export(self):
        p,r=self.fixture(); summary,histories=summarize(r,p)
        self.assertEqual(summary['completed_runs'],3)
        self.assertEqual(summary['completed_paired_seeds'],[0])
        self.assertNotIn('SECRET',json.dumps([summary,histories]))

    def test_mismatched_pair_initialization_is_rejected(self):
        p,r=self.fixture();r['E-seed-0']['initial_trainable_sha256']='different'
        with self.assertRaisesRegex(ValueError,'initialization'):summarize(r,p)

    def test_config_exposure_and_selection_tampering_are_rejected(self):
        p,original=self.fixture()
        mutations=[lambda r:r['config'].update(seed=2),lambda r:r['sample_exposures'][0].update(count=2),
                   lambda r:r['selection'].update(step=418)]
        for mutation in mutations:
            with self.subTest(mutation=mutation):
                r=copy.deepcopy(original);mutation(r['D-seed-0'])
                with self.assertRaises(ValueError):summarize(r,p)

    def test_noncompleted_or_non_deferred_runs_are_rejected(self):
        p,original=self.fixture()
        for key in ('completed','test_deferred'):
            r=copy.deepcopy(original);r['D-seed-0'][key]=False
            with self.assertRaises(ValueError):summarize(r,p)

    def test_scheduler_flag_cannot_invent_a_reduction(self):
        p,r=self.fixture();r['E-seed-0']['history'][0]['scheduler']['reduced']=True
        with self.assertRaisesRegex(ValueError,'reduction flag'):summarize(r,p)

    def test_increased_feedback_learning_rate_is_rejected(self):
        p,r=self.fixture();event=r['E-seed-0']['history'][-1]['scheduler']
        event.update(new_lr=6e-5,lr=6e-5)
        with self.assertRaisesRegex(ValueError,'increased'):summarize(r,p)
