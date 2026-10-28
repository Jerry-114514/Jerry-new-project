import copy
import json
from pathlib import Path
import signal
import os
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock,patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import guarded_diagnostic_continuation as d
import run_limited_diagnostic_continuation as coordinator


class DiagnosticSupervisionTests(unittest.TestCase):
    def setUp(self):
        if not hasattr(signal,'SIGCONT'):
            p=patch.object(signal,'SIGCONT',18,create=True);p.start();self.addCleanup(p.stop)

    def fixture(self):
        c={'start_unix':1793110212,'window_seconds':108000,'authorized_max_seconds':108000,
           'admission_reserve_seconds':7200,'shutdown_reserve_seconds':3600}
        a={'kind':'approved_diagnostic_resource_reallocation_v1','user_approved':True,
           'models_restarted':False,'clock_reset':False,'generation_deadline_unix':1793209800,
           'gpu_deadline_unix':1793214000,'cpu_deadline_unix':1793214300,'backup_deadline_unix':1793214600}
        return a,c

    def test_deadlines_and_original_clock_are_absolute(self):
        a,c=self.fixture();p=d.policy(a,c,1793202000)
        self.assertEqual(p['generation_deadline_unix']-c['start_unix'],99588)
        self.assertLess(p['backup_deadline_unix'],c['start_unix']+29*3600)

    def test_training_approval_cannot_authorize_diagnostic_handoff(self):
        a,c=self.fixture();a['kind']='approved_training_resource_reallocation_v1'
        with self.assertRaisesRegex(ValueError,'separate'):d.policy(a,c,1793202000)

    def test_generation_only_handoff_needs_all_six_endpoints_and_same_lock(self):
        jobs={f'{k}-seed-{s}':{'status':'completed'} for k in ('D','E') for s in range(3)}
        p={'jobs':jobs,'lock_hash':'lock'}
        a={'previous_coordinator':{'pid':10,'start_ticks':'tick'},'protocol_hash':'lock',
           'adopted_stage':{'pid':11,'start_ticks':'sup','name':'diagnostic-generate'}}
        parent={'pid':10,'start_ticks':'tick','phase':'diagnostic_generate','status':'running',
                'protocol_hash':'lock','jobs':jobs,'active_stage_supervisor':a['adopted_stage']}
        coordinator.validate_parent(p,parent,a)
        for change in ('missing_job','failed_job','already_revealed','changed_lock'):
            changed=copy.deepcopy(parent)
            if change=='missing_job':changed['jobs'].pop('E-seed-2')
            if change=='failed_job':changed['jobs']['E-seed-2']['status']='failed'
            if change=='already_revealed':changed['phase']='diagnostic_reveal'
            if change=='changed_lock':changed['protocol_hash']='other'
            with self.subTest(change=change),self.assertRaises(ValueError):coordinator.validate_parent(p,changed,a)

    def test_resets_extensions_restarts_and_late_deployment_rejected(self):
        for key,value in [('start_unix',1793110213),('window_seconds',108001),('admission_reserve_seconds',0)]:
            a,c=self.fixture();c[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError):d.policy(a,c,1793202000)
        a,c=self.fixture();a['generation_deadline_unix']+=1
        with self.assertRaises(ValueError):d.policy(a,c,1793202000)
        a,c=self.fixture();a['models_restarted']=True
        with self.assertRaises(ValueError):d.policy(a,c,1793202000)
        a,c=self.fixture()
        with self.assertRaises(TimeoutError):d.policy(a,c,a['generation_deadline_unix'])

    def test_pid_reuse_never_signalled(self):
        with patch.object(d,'identity',return_value=('S','new')),patch.object(d.os,'kill') as kill:
            with self.assertRaisesRegex(RuntimeError,'identity'):d.signal_bound({'pid':123,'start_ticks':'old'},signal.SIGCONT)
            kill.assert_not_called()

    def test_cleanup_waits_for_outputs_to_stop_before_archive(self):
        with patch.object(d,'checked_identity',side_effect=[('S','worker'),('Z','worker'),('Z','worker'),('Z','worker'),('Z','worker'),None]),patch.object(d,'signal_bound') as signals:
            d.stop_adopted({'pid':1},{'pid':2})
            self.assertEqual(signals.call_args_list[0].args,({'pid':2},signal.SIGINT))
            self.assertEqual(signals.call_args_list[1].args,({'pid':1},signal.SIGCONT))

    def test_new_gpu_stage_still_requires_original_admission(self):
        with tempfile.TemporaryDirectory() as folder:
            g=types.SimpleNamespace(read_config=lambda _:({'owned_source_roots':[str(Path(folder).resolve())]},'sha'),
                                    MODULES={'intentlab.diagnostic_protocol'},admit=Mock(side_effect=ValueError('Admission closed')))
            with patch.object(d.sys,'platform','linux'),patch.object(d,'runtime_check',return_value={}),patch.object(d.subprocess,'Popen') as spawn:
                with self.assertRaisesRegex(ValueError,'Admission closed'):
                    d.invoke(g,folder,'sha',folder,Path(folder)/'out',d.time.time()+60,
                             'intentlab.diagnostic_protocol',[sys.executable,'unused','{ACK}'],lambda:None)
                spawn.assert_not_called();self.assertFalse((Path(folder)/'out').exists())

    def test_zombie_is_finished_but_cannot_authorize_success(self):
        self.assertFalse(d.live(('Z','old')))
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'status.json'
            path.write_text(json.dumps({'supervisor_pid':1,'child_pid':2,'child_start_ticks':'worker',
                                        'status':'failed','worker_exit_code':7}))
            with patch.object(d,'checked_identity',return_value=None):
                with self.assertRaisesRegex(RuntimeError,'no retry'):
                    d.wait_adopted(None,None,None,{'pid':1},{'pid':2,'start_ticks':'worker'},1,path,lambda:None)

    def test_only_original_parent_exit_zero_certifies_adopted_stage(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'status.json'
            path.write_text(json.dumps({'supervisor_pid':1,'child_pid':2,'child_start_ticks':'worker',
                                        'status':'completed','worker_exit_code':0}))
            with patch.object(d,'checked_identity',return_value=None),patch.object(d.subprocess,'Popen') as spawn:
                d.wait_adopted(None,None,None,{'pid':1},{'pid':2,'start_ticks':'worker'},1,path,lambda:None)
                spawn.assert_not_called()

    def test_watchdog_resumes_original_parent_after_child_exits(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(d,'identity',return_value=('R','self')),patch.object(d,'checked_identity',side_effect=[('T','sup'),('Z','worker'),('S','parent')]),patch.object(d,'signal_bound') as signals:
            rc=d.watchdog({'pid':1},{'pid':2},{'pid':3},d.time.time()+10,Path(folder)/'receipt.json')
            self.assertEqual(rc,0)
            signals.assert_called_once_with({'pid':2},signal.SIGCONT)

    def runtime_fixture(self,folder):
        _,c=self.fixture();c.update(original_guard_root='old',original_config_sha256='old-sha',
                                    guard_script='script',guard_script_sha256='script-sha')
        Path(folder,'status.json').write_text(json.dumps({'status':'monitoring','config_sha256':'guard-sha',
                                                        'unix':100,'pid':99,'start_ticks':'ticks'}))
        g=types.SimpleNamespace(read_config=Mock(return_value=(c,'guard-sha')),original_snapshot=Mock(),
                                start_ticks=Mock(return_value='ticks'),sha=Mock(return_value='script-sha'),
                                decision=Mock(return_value={'admission_open':False,'shutdown_due':False,'hard_limit_reached':False}))
        return g

    def test_existing_stage_may_cross_admission_but_both_guards_are_checked(self):
        with tempfile.TemporaryDirectory() as folder:
            g=self.runtime_fixture(folder)
            with patch.object(d,'boot_id',return_value='boot'),patch.object(d.time,'time',return_value=100),patch.object(Path,'read_bytes',return_value=b'source'):
                result=d.runtime_check(g,folder,'guard-sha',200)
            self.assertFalse(result['admission_open']);g.original_snapshot.assert_called_once();g.decision.assert_called_once()

    def test_changed_guard_stale_heartbeat_cost_failure_and_shutdown_stop(self):
        for failure in ('config','heartbeat','identity','cost','shutdown','stage_deadline','monotonic'):
            with self.subTest(failure=failure),tempfile.TemporaryDirectory() as folder:
                g=self.runtime_fixture(folder);now=100;started=None;deadline=200
                if failure=='config':g.read_config.return_value=(g.read_config.return_value[0],'changed')
                if failure=='heartbeat':now=146
                if failure=='identity':g.start_ticks.return_value='reused'
                if failure=='cost':g.original_snapshot.side_effect=ValueError('Cost exhausted')
                if failure=='shutdown':g.decision.return_value['shutdown_due']=True
                if failure=='stage_deadline':deadline=100
                if failure=='monotonic':started=(0,0)
                with patch.object(d,'boot_id',return_value='boot'),patch.object(d.time,'time',return_value=now),patch.object(d.time,'monotonic',return_value=300),patch.object(Path,'read_bytes',return_value=b'source'):
                    with self.assertRaises((ValueError,TimeoutError)):d.runtime_check(g,folder,'guard-sha',deadline,started)


@unittest.skipUnless(sys.platform=='linux','Real process adoption is verified on Linux')
class NativeOriginalParentTests(unittest.TestCase):
    def invocation(self,exit_code):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);worker=root/'cpu.py'
            worker.write_text('''from pathlib import Path
import os,sys,time
assert os.environ['CUDA_VISIBLE_DEVICES']==''
while not Path(sys.argv[1]).exists():time.sleep(.005)
raise SystemExit(int(sys.argv[2]))
''')
            g=types.SimpleNamespace(read_config=lambda _:({'owned_source_roots':[str(root.resolve())]},'sha'),
                                    MODULES={'intentlab.frozen_statistics'},admit=Mock(side_effect=AssertionError('CPU statistics do not open a new GPU admission')),
                                    start_ticks=lambda pid:d.identity(pid)[1])
            with patch.object(d,'runtime_check',return_value={}):
                if exit_code:
                    with self.assertRaisesRegex(RuntimeError,'no retry'):
                        d.invoke(g,root,'sha',root,root/'out',d.time.time()+5,'intentlab.frozen_statistics',
                                 [sys.executable,str(worker),'{ACK}',str(exit_code)],lambda:None,cpu_only=True)
                else:d.invoke(g,root,'sha',root,root/'out',d.time.time()+5,'intentlab.frozen_statistics',
                              [sys.executable,str(worker),'{ACK}',str(exit_code)],lambda:None,cpu_only=True)
            status=json.loads((root/'out/status.json').read_text())
            self.assertEqual(status['worker_exit_code'],exit_code)
            self.assertEqual(status['status'],'failed' if exit_code else 'completed')
            self.assertEqual(status['automatic_retries'],0)

    def test_cpu_statistics_launch_disables_cuda_and_records_success(self):self.invocation(0)

    def test_cpu_statistics_failure_is_preserved_without_retry(self):self.invocation(7)

    def exercise(self,exit_code):
        """Run the unmodified original supervisor, using only a fake CPU guard.

        Accelerate its monotonic clock to test a missed subdeadline in seconds;
        the original child.poll-before-timeout ordering remains untouched.
        """
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);tools=root/'guard';tools.mkdir();out=root/'invocation'
            fake='''from pathlib import Path
MODULES={'intentlab.diagnostic_protocol'}
def read_config(root): return {'owned_source_roots':[str(Path(root).resolve())]},'fake'
def admit(*args):return {}
def start_ticks(pid):
 try:return Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19]
 except FileNotFoundError:return None
'''
            (tools/'additional_gpu_time_guard.py').write_text(fake)
            original=Path(sys.modules['run_limited_30h_pipeline'].__file__).parent/'guarded_30h_invocation.py'
            wrapper=root/'original-wrapper.py'
            wrapper.write_text('''import importlib.util,sys,time
spec=importlib.util.spec_from_file_location('original',sys.argv[1]);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
clock=time.monotonic;origin=clock();m.time.monotonic=lambda:origin+(clock()-origin)*100
raise SystemExit(m.run(sys.argv[2],sys.argv[3],sys.argv[3],sys.argv[4],61,'intentlab.diagnostic_protocol',
 [sys.executable,sys.argv[5],'{ACK}',sys.argv[6]]))
''')
            worker=root/'worker.py'
            worker.write_text('''from pathlib import Path
import sys,time
ack=Path(sys.argv[1])
while not ack.exists():time.sleep(.005)
time.sleep(.5)
raise SystemExit(int(sys.argv[2]))
''')
            proc=subprocess.Popen([sys.executable,str(wrapper),str(original),str(tools),str(root),str(out),str(worker),str(exit_code)])
            binding=None;stage={'pid':proc.pid,'start_ticks':d.identity(proc.pid)[1]}
            try:
                until=d.time.monotonic()+5
                while not (out/'invocation.ack.json').exists():
                    if proc.poll() is not None or d.time.monotonic()>until:self.fail('Original invocation failed to start')
                    d.time.sleep(.005)
                ack=json.loads((out/'invocation.ack.json').read_text());binding={'pid':ack['pid'],'start_ticks':ack['start_ticks']}
                d.signal_bound(stage,signal.SIGSTOP)
                while d.live(d.checked_identity(binding)):
                    if d.time.monotonic()>until:self.fail('CPU fixture did not finish')
                    d.time.sleep(.01)
                # The supervisor's original work deadline expired while paused.
                with patch.object(d,'runtime_check',return_value={}):
                    if exit_code:
                        with self.assertRaisesRegex(RuntimeError,'no retry'):
                            d.wait_adopted(None,None,None,stage,binding,d.time.time()+3,out/'status.json',lambda:None)
                    else:d.wait_adopted(None,None,None,stage,binding,d.time.time()+3,out/'status.json',lambda:None)
                proc.wait(timeout=3)
                receipt=json.loads((out/'status.json').read_text())
                self.assertEqual(receipt['worker_exit_code'],exit_code)
                self.assertEqual(receipt['child_pid'],binding['pid'])
                self.assertEqual(receipt['status'],'failed' if exit_code else 'completed')
            finally:
                if proc.poll() is None:
                    d.signal_bound(stage,signal.SIGCONT);proc.terminate()
                    try:proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:proc.kill();proc.wait(timeout=3)
                if binding and d.live(d.checked_identity(binding)):d.signal_bound(binding,signal.SIGKILL,group=True)

    def test_original_parent_collects_real_zero_after_expired_subdeadline(self):self.exercise(0)

    def test_original_parent_preserves_real_failure_after_expired_subdeadline(self):self.exercise(7)


if __name__=='__main__':unittest.main()
