import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform=='linux','Native process-group test uses Linux; no model/GPU is used')
class GuardedInvocationTests(unittest.TestCase):
    def test_acknowledged_child_runs_only_after_both_guards_admit(self):self.exercise('ok')
    def test_guard_failure_before_launch_never_starts_child(self):self.exercise('reject')
    def test_guard_loss_stops_an_already_running_child(self):self.exercise('lost')

    def exercise(self,mode):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);tools=root/'tools';tools.mkdir();out=root/'job'
            (tools/'additional_gpu_time_guard.py').write_text(
                'from pathlib import Path\nimport json\n'
                "MODULES={'intentlab.neural'}\n"
                f"BASE=Path({str(root)!r})\nMODE={mode!r}\n"
                "def read_config(root):return {'owned_source_roots':[str(BASE)]},'fixture'\n"
                "def start_ticks(pid):\n"
                " try:return Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19]\n"
                " except OSError:return None\n"
                "def admit(root,seconds):\n"
                " p=BASE/'calls';n=int(p.read_text())+1 if p.exists() else 1;p.write_text(str(n))\n"
                " if MODE=='reject' or (MODE=='lost' and n>=3):raise ValueError('fixture guard unavailable')\n"
                " return {'admission_open':True}\n")
            child=root/'child.py'
            child.write_text('import json,os,sys,time\nfrom pathlib import Path\n'
                'p=Path(sys.argv[1])\n'
                'while not p.exists():time.sleep(.01)\n'
                "assert json.loads(p.read_text())['pid']==os.getpid()\n"
                f"Path({str(root/'started')!r}).write_text('acknowledged')\n"
                +('time.sleep(60)\n' if mode=='lost' else ''))
            script=Path(__file__).resolve().parents[1]/'scripts/guarded_30h_invocation.py'
            cmd=[sys.executable,str(script),'--guard-tools',str(tools),'--guard-root',str(root),
                 '--cwd',str(root),'--out',str(out),'--max-seconds','90','--owned-module','intentlab.neural',
                 '--',sys.executable,str(child),'{ACK}']
            try:
                p=subprocess.run(cmd,capture_output=True,text=True,timeout=25)
                if mode=='reject':
                    self.assertNotEqual(p.returncode,0);self.assertFalse((root/'started').exists())
                else:
                    self.assertEqual((root/'started').read_text(),'acknowledged')
                    state=json.loads((out/'status.json').read_text())
                    self.assertEqual(state['status'],'completed' if mode=='ok' else 'failed')
                    self.assertEqual(p.returncode,0 if mode=='ok' else 1)
                    if mode=='lost':self.assertIsNotNone(state['worker_exit_code'])
            finally:
                if (out/'status.json').exists():
                    state=json.loads((out/'status.json').read_text());pid=state.get('child_pid')
                    if pid and Path('/proc',str(pid),'stat').exists():
                        ticks=Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19]
                        if ticks==state.get('child_start_ticks'):
                            try:os.killpg(pid,signal.SIGKILL)
                            except ProcessLookupError:pass


if __name__=='__main__':unittest.main()
