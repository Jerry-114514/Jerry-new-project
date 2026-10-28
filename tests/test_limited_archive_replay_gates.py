from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from replay_limited_followup_archive import CONDITIONS, check_seal, replay_preconditions


def digest(v):
    return hashlib.sha256(json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()


class GateTests(unittest.TestCase):
    def data(self):
        p={'scope':'approved_compute_limited_30h_followup','conditions':CONDITIONS}
        p['lock_hash']=digest(p)
        index={'files':{'predictions/A/predictions.jsonl':{'sha256':'one'},
                        'predictions/manifest.json':{'sha256':'manifest'}}}
        manifest={'status':'sealed','gold_loaded':False,'conditions':CONDITIONS,
                  'protocol_hash':p['lock_hash'],'files_sha256':{'A/predictions.jsonl':'one'}}
        manifest['seal_hash']=digest(manifest)
        return p,index,manifest

    def test_unsealed_archive_never_reaches_gold_decoding(self):
        p,index,m=self.data();m['status']='running'
        calls=[]
        class Source:
            def json(self,name):
                calls.append(name)
                if name.startswith('sealed/'):raise AssertionError('Gold read before seal')
                return {'backup-index.json':index,'state-for-archive.json':{'outcome':'completed','limited_experiment_completed':True},
                        'predictions/manifest.json':m}[name]
        with self.assertRaisesRegex(ValueError,'sealed'):replay_preconditions(Source(),p,digest)
        self.assertFalse(any(name.startswith('sealed/') for name in calls))

    def test_omitted_or_extra_prediction_file_is_rejected(self):
        p,index,m=self.data()
        for key in ('predictions/A/predictions.jsonl','predictions/B/predictions.jsonl'):
            wrong=deepcopy(index)
            if key in wrong['files']:del wrong['files'][key]
            else:wrong['files'][key]={'sha256':'extra'}
            with self.assertRaisesRegex(ValueError,'inventory'):check_seal(m,wrong,p,digest)

    def test_gold_flag_cannot_be_hidden_by_resealing_manifest(self):
        p,index,m=self.data();m['gold_loaded']=True
        m['seal_hash']=digest({k:v for k,v in m.items() if k!='seal_hash'})
        with self.assertRaisesRegex(ValueError,'gold'):check_seal(m,index,p,digest)

    def test_partial_run_cannot_be_certified_using_sealed_predictions(self):
        p,index,m=self.data()
        class Source:
            def json(self,name):
                return {'backup-index.json':index,'state-for-archive.json':{'outcome':'failed','limited_experiment_completed':False},
                        'predictions/manifest.json':m}[name]
        with self.assertRaisesRegex(ValueError,'partial'):replay_preconditions(Source(),p,digest)
