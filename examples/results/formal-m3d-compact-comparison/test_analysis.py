"""Synthetic parser/accounting checks; no human ground truth or model claims."""
from copy import deepcopy
import json
from pathlib import Path
import runpy
import sys
import unittest

REPO=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(REPO))
sys.path.insert(0,str(REPO/'tests'))
from test_formal_data import case
from intentlab.budget import TokenLedger
from intentlab.core import digest
analyze=runpy.run_path(str(Path(__file__).with_name('analyze.py')))['analyze']


def fixture():
    cases=[case(),case('view-2',source='source-2',template='template-2')]
    manifest={'status':'completed','cases_hash':digest(cases),'views':2,'planned_calls':4,
        'gold_loaded':False,'human_accuracy':None,'token_budget_per_call':8192,'max_new_tokens':512,'context_limit':6144}
    preflight={'cases_hash':digest(cases),'rows':[]};records=[]
    for index,c in enumerate(cases):
        for condition in (('full','compact') if index%2==0 else ('compact','full')):
            h=digest([c['case_id'],condition]);ledger=TokenLedger(8192)
            ticket,_=ledger.begin('analyzer',100,512,6144,h);ledger.finish(ticket,20)
            preflight['rows'].append({'case_id':c['case_id'],'condition':condition,'prompt_hash':h,'prompt_tokens':100})
            records.append({'call_index':len(records),'case_index':index,'case_id':c['case_id'],'condition':condition,
                'prompt_hash':h,'status':'generated','usage':{'prompt_tokens':100,'completion_tokens':20},
                'text':json.dumps({'findings':[{'id':'preserve','status':'unknown','evidence':[]}]}),
                'budget':ledger.snapshot(),'generation_seconds':1.0})
    return cases,manifest,preflight,records


class AnalysisChecks(unittest.TestCase):
    def test_missing_or_duplicated_calls_cannot_shrink_denominator(self):
        c,m,p,r=fixture()
        with self.assertRaises(ValueError):analyze(c,m,p,r[:-1])
        r[1]=deepcopy(r[0])
        with self.assertRaises(ValueError):analyze(c,m,p,r)

    def test_fenced_output_remains_invalid_and_noncomparable(self):
        c,m,p,r=fixture();r[0]['text']='```json\n'+r[0]['text']+'\n```'
        result=analyze(c,m,p,r)
        self.assertEqual(result['paired']['noncomparable_items'],1)
        self.assertEqual(result['conditions']['full']['normalized_invalid_views'],1)
        self.assertIsNone(result['human_accuracy'])

    def test_wrong_reference_is_not_semantic_accuracy(self):
        c,m,p,r=fixture();r[0]['text']=json.dumps({'findings':[{'id':'preserve','status':'violated','evidence':['event:999']}]})
        result=analyze(c,m,p,r)
        self.assertEqual(result['conditions']['full']['strict_parsed_views'],2)
        self.assertEqual(result['conditions']['full']['strict_visible_reference_constraint_invalid_views'],1)
        self.assertEqual(result['paired']['status_disagreements'],1)

    def test_generation_failure_charges_reservation_and_is_retained(self):
        c,m,p,r=fixture();ledger=TokenLedger(8192);ticket,_=ledger.begin('analyzer',100,512,6144,r[0]['prompt_hash']);ledger.fail(ticket,'RuntimeError')
        r[0].update(status='error',error_type='RuntimeError',text='',budget=ledger.snapshot());r[0].pop('usage')
        result=analyze(c,m,p,r)
        self.assertEqual(result['conditions']['full']['generation_errors'],1)
        self.assertEqual(result['conditions']['full']['charged_model_tokens'],732)
        self.assertEqual(result['paired']['noncomparable_views'],1)

    def test_pre_generation_failure_does_not_invent_a_reservation(self):
        c,m,p,r=fixture()
        r[0].update(status='error',error_type='GpuBusy',text='',budget=TokenLedger(8192).snapshot());r[0].pop('usage')
        result=analyze(c,m,p,r)
        self.assertEqual(result['conditions']['full']['generation_errors_before_reservation'],1)
        self.assertEqual(result['conditions']['full']['charged_model_tokens'],120)
        self.assertEqual(result['paired']['noncomparable_items'],1)

    def test_id_object_normalization_does_not_change_predicted_state(self):
        c,m,p,r=fixture();r[0]['text']=json.dumps({'preserve':{'status':'unknown','evidence':[]}})
        result=analyze(c,m,p,r)
        self.assertEqual(result['conditions']['full']['strict_invalid_views'],1)
        self.assertEqual(result['conditions']['full']['normalized_parsed_views'],2)
        self.assertEqual(result['conditions']['full']['predicted_unknown_items'],2)
        self.assertEqual(result['paired']['status_disagreements'],0)

    def test_rehashed_fake_usage_still_fails_budget_replay(self):
        c,m,p,r=fixture();r[0]['budget']['charged_tokens']+=1
        with self.assertRaises(ValueError):analyze(c,m,p,r)


if __name__=='__main__':unittest.main()
