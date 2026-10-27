import hashlib
import json
from pathlib import Path
import signal
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import additional_gpu_time_guard as guard


class DurationWindowTests(unittest.TestCase):
    def window(self,remaining=40*3600):return guard.make_window(1000000,1000,'boot',remaining)

    def test_original_cost_deadline_always_clips_the_new_thirty_hour_window(self):
        self.assertEqual(self.window()['window_seconds'],30*3600)
        self.assertEqual(self.window(3*3600)['window_seconds'],3*3600)
        with self.assertRaises(ValueError):self.window(2*3600)

    def test_delayed_installation_counts_prior_idle_time_and_keeps_same_deadline(self):
        a=guard.make_window(1000000+2*3600,1000+2*3600,'boot',40*3600,1000000)
        b=guard.make_window(1000000+5*3600,1000+5*3600,'boot',37*3600,1000000)
        self.assertEqual(a['start_unix'],b['start_unix'])
        self.assertEqual(a['start_monotonic'],b['start_monotonic'])
        self.assertEqual(a['window_seconds'],b['window_seconds'])
        self.assertEqual(guard.decision(a,1000000+5*3600,1000+5*3600,'boot')['remaining_seconds'],25*3600)

    def test_start_anchor_cannot_be_moved_into_the_future(self):
        with self.assertRaises(ValueError):guard.make_window(1000000,1000,'boot',40*3600,1000001)

    def test_admission_closes_at_twenty_eight_and_shutdown_starts_at_twenty_nine(self):
        c=self.window()
        at=lambda h:guard.decision(c,1000000+h*3600,1000+h*3600,'boot')
        self.assertTrue(at(27.9)['admission_open'])
        self.assertFalse(at(28)['admission_open'])
        self.assertFalse(at(28.9)['shutdown_due'])
        self.assertTrue(at(29)['shutdown_due'])
        self.assertTrue(at(30)['hard_limit_reached'])

    def test_clock_changes_do_not_extend_the_deadline(self):
        c=self.window()
        self.assertEqual(guard.decision(c,900000,1600,'boot')['elapsed_seconds'],600)
        self.assertTrue(guard.decision(c,1000000+31*3600,1600,'boot')['shutdown_due'])
        with self.assertRaises(ValueError):guard.decision(c,1000000,999,'boot')
        with self.assertRaises(ValueError):guard.decision(c,1000000,1000,'new-boot')

    def test_nonfinite_and_boolean_clock_values_are_rejected(self):
        for value in (float('nan'),float('inf'),True):
            with self.assertRaises(ValueError):guard.make_window(value,1000,'boot',40*3600)

    def test_worker_ownership_is_rechecked_before_force_stop(self):
        with patch.object(guard,'owned_groups',side_effect=[{9},{10}]), \
             patch.object(guard.time,'sleep'),patch.object(guard.os,'killpg',create=True) as kill, \
             patch.object(guard.signal,'SIGKILL',9,create=True):
            self.assertEqual(guard.stop_owned({}),[9,10])
            self.assertEqual(kill.call_args_list[0].args,(9,signal.SIGINT))
            self.assertEqual(kill.call_args_list[1].args,(10,signal.SIGKILL))


class GuardAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.old=self.root/'old';self.new=self.root/'new'
        self.old.mkdir();self.new.mkdir()
        self.original={'price_yuan_per_hour':'2.88','budget_yuan':'500','shutdown_reserve_yuan':'10',
                       'boot_id':'boot','stop_monotonic':1000+40*3600}
        self.raw=json.dumps(self.original).encode();(self.old/'config.json').write_bytes(self.raw)
        self.sha=hashlib.sha256(self.raw).hexdigest()
        self.status={'pid':111,'start_ticks':'old','unix':1000000,'status':'monitoring','config_sha256':self.sha}
        self.write_status()
        self.identity=lambda pid:{111:'old',222:'new'}.get(pid)

    def write_status(self):(self.old/'status.json').write_text(json.dumps(self.status))

    def test_original_guard_requires_fresh_live_process_and_unchanged_configuration(self):
        _,remaining=guard.original_snapshot(self.old,self.sha,1000000,1000,'boot',self.identity)
        self.assertEqual(remaining,40*3600)
        with self.assertRaises(ValueError):guard.original_snapshot(self.old,self.sha,1000121,1000,'boot',self.identity)
        with self.assertRaises(ValueError):guard.original_snapshot(self.old,self.sha,1000000,1000,'boot',lambda _:None)
        self.status['start_ticks']=None;self.write_status()
        with self.assertRaises(ValueError):guard.original_snapshot(self.old,self.sha,1000000,1000,'boot',lambda _:None)
        self.status['start_ticks']='old';self.write_status()
        (self.old/'config.json').write_bytes(self.raw+b' ')
        with self.assertRaises(ValueError):guard.original_snapshot(self.old,self.sha,1000000,1000,'boot',self.identity)

    def test_admission_requires_a_live_additional_guard_and_room_for_job(self):
        script=self.root/'guard.py';script.write_bytes(b'# fixture, never executed\n')
        c=guard.make_window(1000000,1000,'boot',40*3600)
        c.update(original_guard_root=str(self.old),original_config_sha256=self.sha,
                 guard_script=str(script),guard_script_sha256=guard.sha(script.read_bytes()))
        (self.new/'config.json').write_text(json.dumps(c))
        s={'status':'monitoring','config_sha256':guard.sha((self.new/'config.json').read_bytes()),
           'unix':1000000,'pid':222,'start_ticks':'new'}
        (self.new/'status.json').write_text(json.dumps(s))
        read=Path.read_text
        def text(path,*args,**kwargs):
            return 'boot' if str(path).replace('\\','/')=='/proc/sys/kernel/random/boot_id' else read(path,*args,**kwargs)
        with patch.object(guard.time,'time',return_value=1000000), \
             patch.object(guard.time,'monotonic',return_value=1000),patch.object(Path,'read_text',text):
            self.assertTrue(guard.admit(self.new,3600,self.identity)['admission_open'])
            with self.assertRaises(ValueError):guard.admit(self.new,30*3600,self.identity)
            with self.assertRaises(ValueError):guard.admit(self.new,3600,lambda p:'old' if p==111 else None)
            s['unix']-=46;(self.new/'status.json').write_text(json.dumps(s))
            with self.assertRaises(ValueError):guard.admit(self.new,3600,self.identity)


if __name__=='__main__':unittest.main()
