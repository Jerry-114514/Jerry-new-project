import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import run_limited_30h_resource_continuation as continuation


class ResourceContinuationTests(unittest.TestCase):
    def fixture(self):
        start=10000.;anchor=start-2*3600
        stage={'pid':11,'start_ticks':'100','name':'D-seed-2'}
        parent={'pid':10,'start_ticks':'90','protocol_hash':'science','phase':'training',
                'active_stage_supervisor':stage,'jobs':{n:{'status':'completed'} for n in continuation.ORDER[:4]}}
        parent['jobs'].update({'D-seed-2':{'status':'running'},'E-seed-2':{'status':'not_started'}})
        amendment={'kind':'approved_training_resource_reallocation_v1','user_approved':True,
                   'original_training_seconds':61200,'amended_training_seconds':64800,
                   'original_pipeline_started_unix':start,'absolute_start_unix':anchor,
                   'adopted_stage':stage,'previous_coordinator':{'pid':10,'start_ticks':'90'},'protocol_hash':'science'}
        claim={'started_unix':start,'protocol_hash':'science'}
        guard={'start_unix':anchor,'window_seconds':108000,'authorized_max_seconds':108000,'shutdown_reserve_seconds':3600}
        return amendment,parent,claim,guard,{'training':61200,'diagnostics':25200,'backup':3600}

    def test_absolute_deadline_uses_original_start_and_reserves_downstream(self):
        args=self.fixture()
        self.assertEqual(continuation.validate_resource_handoff(*args),10000+18*3600)

    def test_reset_clock_and_already_dispatched_sixth_are_rejected(self):
        args=self.fixture();args[0]['original_pipeline_started_unix']+=1
        with self.assertRaisesRegex(ValueError,'clocks'):continuation.validate_resource_handoff(*args)
        args=self.fixture();args[1]['jobs']['E-seed-2']['status']='running'
        with self.assertRaisesRegex(ValueError,'sixth'):continuation.validate_resource_handoff(*args)

    def test_downstream_window_cannot_overrun_original_guard(self):
        args=self.fixture();args[3]['window_seconds']=25*3600
        with self.assertRaisesRegex(ValueError,'reserve'):continuation.validate_resource_handoff(*args)

    def stage_file(self,folder,status,exit_code):
        root=Path(folder);out=root/'supervision/D-seed-2';out.mkdir(parents=True)
        (out/'status.json').write_text(json.dumps({'supervisor_pid':11,'child_pid':12,'child_start_ticks':'200',
                                                 'status':status,'worker_exit_code':exit_code}),encoding='utf-8')
        return root,{'pid':11,'start_ticks':'100','name':'D-seed-2'},{'pid':12,'start_ticks':'200'}

    def test_completed_adopted_invocation_is_reused_without_spawn(self):
        with tempfile.TemporaryDirectory() as d:
            args=self.stage_file(d,'completed',0)
            with patch.object(continuation,'process_identity',return_value=None),patch.object(continuation.subprocess,'Popen',side_effect=AssertionError('No spawning')):
                continuation.adopt_stage(*args,lambda:None)

    def test_failed_adopted_invocation_is_not_retried(self):
        with tempfile.TemporaryDirectory() as d:
            args=self.stage_file(d,'failed',1)
            with patch.object(continuation,'process_identity',return_value=None):
                with self.assertRaisesRegex(RuntimeError,'no retry'):continuation.adopt_stage(*args,lambda:None)

    def test_reused_supervisor_pid_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            args=self.stage_file(d,'running',None)
            with patch.object(continuation,'process_identity',side_effect=[('S','999'),None]):
                with self.assertRaisesRegex(ValueError,'reused'):continuation.adopt_stage(*args,lambda:None)
