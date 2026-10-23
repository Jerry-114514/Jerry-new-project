import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from intentlab.matrix import paired_training_audit,validate_result
from intentlab.protocol import file_hash


class InitializationAuditTests(unittest.TestCase):
    def fixture(self,root,values):
        jobs=[]
        for schedule,initial in zip(('cosine','plateau'),values):
            config={'schedule':schedule,'seed':0,'steps':2,'batch_size':1,'accumulation':2}
            result={'config':config,'completed':True,'test_deferred':True,'examples_seen':4,
                'supervised_tokens':20,'train_tokens':40,'data_hash':'data','base_identity':'base',
                'sample_exposures':[{'count':4}]}
            if initial is not None:result['initial_trainable_sha256']=initial
            directory=root/schedule;directory.mkdir()
            path=directory/'result.json';path.write_text(json.dumps(result))
            jobs.append({'status':'completed','name':schedule,'config':config,
                'result_sha256':file_hash(path),'artifacts_sha256':{}})
        return jobs

    def test_actual_pair_identity_required_and_legacy_not_upgraded(self):
        with tempfile.TemporaryDirectory() as name,patch('intentlab.matrix.training_artifacts',return_value={}):
            root=Path(name);jobs=self.fixture(root,[None,None])
            legacy=paired_training_audit(jobs,root)
            self.assertNotIn('paired_initialization_equal',legacy[0])
            with self.assertRaisesRegex(ValueError,'observed initial'):
                paired_training_audit(jobs,root,require_initialization=True)
        with tempfile.TemporaryDirectory() as name,patch('intentlab.matrix.training_artifacts',return_value={}):
            root=Path(name);jobs=self.fixture(root,['a'*64,'a'*64])
            result=paired_training_audit(jobs,root,require_initialization=True)
            self.assertTrue(result[0]['paired_initialization_equal'])
        with tempfile.TemporaryDirectory() as name,patch('intentlab.matrix.training_artifacts',return_value={}):
            root=Path(name);jobs=self.fixture(root,['a'*64,'b'*64])
            with self.assertRaisesRegex(ValueError,'initial trainable tensors'):
                paired_training_audit(jobs,root,require_initialization=True)

    def test_malformed_hash_rejected_even_for_new_engineering_results(self):
        config={'steps':2,'batch_size':1,'accumulation':2}
        for value in [False,'A'*64,'bad',1]:
            result={'config':config,'completed':True,'test_deferred':True,'examples_seen':4,'supervised_tokens':20,'initial_trainable_sha256':value}
            with self.assertRaisesRegex(ValueError,'SHA256'):validate_result(result,config)
