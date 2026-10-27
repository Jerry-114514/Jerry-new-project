"""One acknowledged, bounded invocation under both existing AutoDL guards.

No retries or resume. The child must wait for the generated acknowledgement
before loading a model. Every command is an argument list, never shell text.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def run(guard_tools,guard_root,cwd,out,max_seconds,owned_module,command):
    if sys.platform!='linux':raise ValueError('Linux-only job supervisor')
    if max_seconds<=60:raise ValueError('Reserve at least 60 seconds for bounded cleanup')
    sys.path.insert(0,str(guard_tools))
    import additional_gpu_time_guard as g
    c,config_sha=g.read_config(guard_root)
    if str(Path(cwd).resolve()) not in c['owned_source_roots'] or owned_module not in g.MODULES:
        raise ValueError('Job must use a recorded scientific source and owned module')
    if not command or Path(command[0]).resolve()!=Path(sys.executable).resolve() or '{ACK}' not in command:
        raise ValueError('Use this Python and an acknowledged child; {ACK} is required')
    g.admit(guard_root,max_seconds)
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    ack=out/'invocation.ack.json';cmd=[str(ack) if a=='{ACK}' else a for a in command]
    started=time.monotonic();work_deadline=started+max_seconds-45
    state={'status':'preparing','supervisor_pid':os.getpid(),'owned_module':owned_module,
           'duration_config_sha256':config_sha,'max_seconds':max_seconds,
           'command_sha256':hashlib.sha256(json.dumps(cmd).encode()).hexdigest(),'automatic_retries':0}
    child=None
    def save():
        state['wall_seconds']=time.monotonic()-started
        temp=out/'status.tmp';temp.write_text(json.dumps(state,indent=2)+'\n');temp.replace(out/'status.json')
    def terminate():
        if child is None or child.poll() is not None:return
        if g.start_ticks(child.pid)!=state.get('child_start_ticks'):
            raise RuntimeError('Child identity changed; do not signal a reused PID')
        os.killpg(child.pid,signal.SIGINT)
        try:child.wait(timeout=20)
        except subprocess.TimeoutExpired:
            if g.start_ticks(child.pid)==state['child_start_ticks']:os.killpg(child.pid,signal.SIGKILL)
            child.wait(timeout=10)
    def interrupted(*_):raise KeyboardInterrupt('Supervisor interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    try:
        save()
        with (out/'worker.log').open('xb') as log:
            child=subprocess.Popen(cmd,cwd=cwd,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        ticks=g.start_ticks(child.pid)
        if not ticks:raise RuntimeError('Could not bind acknowledged child identity')
        state.update(status='running',child_pid=child.pid,child_start_ticks=ticks);save()
        tmp=out/'ack.tmp';tmp.write_text(json.dumps({'pid':child.pid,'start_ticks':ticks,'attempt':'invocation'})+'\n')
        tmp.replace(ack)
        while child.poll() is None:
            remaining=work_deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('Reserved stage wall time exhausted')
            g.admit(guard_root,max(1,remaining))
            save();time.sleep(min(5,remaining))
        state.update(status='completed' if child.returncode==0 else 'failed',worker_exit_code=child.returncode)
        save();return 0 if child.returncode==0 else 1
    except BaseException as exc:
        state.update(status='stopping',error_type=type(exc).__name__,error=str(exc));save()
        try:terminate()
        except BaseException as cleanup:
            state.update(cleanup_error_type=type(cleanup).__name__,cleanup_error=str(cleanup))
        state.update(status='failed',worker_exit_code=None if child is None else child.poll());save()
        return 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('guard-tools','guard-root','cwd','out'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--max-seconds',type=float,required=True);p.add_argument('--owned-module',required=True)
    p.add_argument('command',nargs=argparse.REMAINDER);a=p.parse_args()
    if not a.command or a.command[0]!='--':p.error('Separate child command with --')
    raise SystemExit(run(a.guard_tools,a.guard_root,a.cwd,a.out,a.max_seconds,a.owned_module,a.command[1:]))
