"""Prospective diagnostic supervision; deployment requires a separate approval.

Never changes either existing guard, launches training, or retries a model call.
An adopted child's original parent must collect its real exit status.
"""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def identity(pid):
    try:
        fields=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
        return fields[0],fields[19]
    except FileNotFoundError:
        return None


def live(actual):
    return actual is not None and actual[0] not in ('Z','X')


def boot_id():
    return Path('/proc/sys/kernel/random/boot_id').read_text().strip()


def checked_identity(binding):
    actual=identity(binding['pid'])
    if actual is not None and actual[1]!=binding['start_ticks']:
        raise RuntimeError('PID identity changed; no signal or restart is permitted')
    return actual


def signal_bound(binding,number,group=False):
    actual=checked_identity(binding)
    if live(actual):
        (os.killpg if group else os.kill)(binding['pid'],number)


def stop_adopted(supervisor,worker):
    """Finish bounded cleanup before anyone hashes or archives worker outputs."""
    try:
        if live(checked_identity(worker)):signal_bound(worker,signal.SIGINT,group=True)
    finally:
        signal_bound(supervisor,signal.SIGCONT)
    for seconds,force in ((20,False),(10,True)):
        if force and live(checked_identity(worker)):signal_bound(worker,signal.SIGKILL,group=True)
        until=time.monotonic()+seconds
        while live(checked_identity(worker)):
            if time.monotonic()>=until:break
            time.sleep(.05)
    if live(checked_identity(worker)):raise RuntimeError('Adopted worker did not stop within bounded cleanup')
    # The original parent writes the exit receipt after its next child.poll().
    # Wait for that writer too, so failure archives cannot race its heartbeat.
    until=time.monotonic()+10
    while live(checked_identity(supervisor)):
        if time.monotonic()>=until:raise RuntimeError('Original supervisor did not finish its exit receipt')
        time.sleep(.05)


def save(path,value):
    path=Path(path);temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(value,indent=2)+'\n',encoding='utf-8')
    temp.replace(path)


def policy(amendment,config,now):
    if amendment.get('kind')!='approved_diagnostic_resource_reallocation_v1' or amendment.get('user_approved') is not True:
        raise ValueError('A separate explicit diagnostic amendment is required')
    if config['start_unix']!=1793110212 or config['window_seconds']!=108000 or config['authorized_max_seconds']!=108000:
        raise ValueError('Original absolute clock and 30-hour window must not change')
    if (config['admission_reserve_seconds'],config['shutdown_reserve_seconds'])!=(7200,3600):
        raise ValueError('Original admission and shutdown reserves must not change')
    # Absolute Beijing times: 01:50 generation, 02:10:12 admission,
    # 03:00 GPU stop, 03:05 CPU finish, 03:10:12 planned shutdown.
    expected={'generation_deadline_unix':1793209800,'gpu_deadline_unix':1793214000,
              'cpu_deadline_unix':1793214300,'backup_deadline_unix':1793214600}
    if any(amendment.get(k)!=v for k,v in expected.items()):
        raise ValueError('Only the proposed fixed diagnostic deadlines are allowed')
    if now>=expected['generation_deadline_unix']:
        raise TimeoutError('Generation handoff window has closed')
    if amendment.get('models_restarted') is not False or amendment.get('clock_reset') is not False:
        raise ValueError('Models and clocks must not restart')
    return expected


def runtime_check(g,root,expected_sha,deadline,started=None):
    """For an ALREADY admitted stage; admission is checked separately on launch.

    Both unmodified daemons must remain freshly live. Wall/monotonic elapsed
    uses the guard's original anchor, including every hour spent waiting.
    """
    c,sha=g.read_config(root)
    if sha!=expected_sha:
        raise ValueError('Duration guard configuration changed')
    now=time.time();mono=time.monotonic()
    boot=boot_id()
    g.original_snapshot(c['original_guard_root'],c['original_config_sha256'],now,mono,boot)
    status=json.loads((Path(root)/'status.json').read_text())
    if status.get('status')!='monitoring' or status.get('config_sha256')!=sha or not 0<=now-status['unix']<=45:
        raise ValueError('Duration guard heartbeat is not fresh and monitoring')
    if type(status.get('pid')) is not int or status['pid']<=0 or not status.get('start_ticks') or g.start_ticks(status['pid'])!=status['start_ticks']:
        raise ValueError('Duration guard process identity differs')
    if g.sha(Path(c['guard_script']).read_bytes())!=c['guard_script_sha256']:
        raise ValueError('Duration guard implementation changed')
    state=g.decision(c,now,mono,boot)
    if state['shutdown_due'] or state['hard_limit_reached'] or not math.isfinite(deadline) or now>=deadline:
        raise TimeoutError('Existing guard or approved stage deadline reached')
    if deadline>c['start_unix']+c['window_seconds']-c['shutdown_reserve_seconds']:
        raise ValueError('Stage deadline exceeds unchanged planned shutdown')
    if started is not None and mono-started[1]>=deadline-started[0]:
        raise TimeoutError('Stage monotonic deadline reached')
    return state


def watchdog(parent,supervisor,worker,deadline,receipt,activation=None):
    """Independent fail-safe resumes the ORIGINAL parent; never guesses exit code."""
    started=(time.time(),time.monotonic())
    save(receipt,{'status':'watching','pid':os.getpid(),'start_ticks':identity(os.getpid())[1],
                  'supervisor':supervisor,'worker':worker,'deadline_unix':deadline})
    while True:
        sup=checked_identity(supervisor);child=checked_identity(worker)
        if not live(sup):
            save(receipt,{'status':'original_parent_exited','child_still_live':live(child)})
            return 1 if live(child) else 0
        abandoned=not live(checked_identity(parent))
        if not live(child) or abandoned or time.time()>=deadline or time.monotonic()-started[1]>=deadline-started[0]:
            activated=activation is None or Path(activation).is_file()
            if live(child) and abandoned and activated:signal_bound(worker,signal.SIGINT,group=True)
            signal_bound(supervisor,signal.SIGCONT)
            save(receipt,{'status':'original_parent_resumed','worker_restarted':False,
                          'original_parent_collects_exit_status':True,'unix':time.time()})
            return 0
        time.sleep(.5)


def wait_adopted(g,guard_root,expected_sha,supervisor,worker,deadline,status_path,heartbeat):
    started=(time.time(),time.monotonic())
    try:
        while True:
            sup=checked_identity(supervisor);child=checked_identity(worker)
            if not live(child):
                if live(sup):signal_bound(supervisor,signal.SIGCONT)
                else:
                    status=json.loads(Path(status_path).read_text())
                    if status.get('supervisor_pid')!=supervisor['pid'] or status.get('child_pid')!=worker['pid'] or status.get('child_start_ticks')!=worker['start_ticks']:
                        raise ValueError('Original invocation identity receipt differs')
                    if status.get('status')!='completed' or status.get('worker_exit_code')!=0:
                        raise RuntimeError('Original worker failed; no retry')
                    return
            elif not live(sup):
                raise RuntimeError('Original supervisor missing while worker is live')
            runtime_check(g,guard_root,expected_sha,deadline,started)
            heartbeat();time.sleep(.5)
    finally:
        # If the original seven-hour deadline has elapsed, resuming its parent
        # triggers its original bounded cleanup. Earlier failures stop the child
        # explicitly, with ownership rechecked; there is never a second worker.
        stop_adopted(supervisor,worker)


def invoke(g,guard_root,expected_sha,cwd,out,deadline,module,command,heartbeat,cpu_only=False):
    if sys.platform!='linux':raise ValueError('Linux-only bounded invocation')
    started=(time.time(),time.monotonic())
    runtime_check(g,guard_root,expected_sha,deadline,started)
    c,_=g.read_config(guard_root)
    if str(Path(cwd).resolve()) not in c['owned_source_roots'] or module not in g.MODULES:
        raise ValueError('Frozen source root and owned module required')
    if cpu_only and module!='intentlab.frozen_statistics':
        raise ValueError('Only frozen statistics may use CPU-only admission')
    if not cpu_only:g.admit(guard_root,deadline-time.time()+30)
    if not command or Path(command[0]).resolve()!=Path(sys.executable).resolve() or command.count('{ACK}')!=1:
        raise ValueError('Exactly one acknowledgement and this Python are required')
    out=Path(out);out.mkdir(exist_ok=False)
    ack=out/'invocation.ack.json';cmd=[str(ack) if x=='{ACK}' else x for x in command]
    child=None;binding=None
    state={'status':'preparing','supervisor_pid':os.getpid(),'deadline_unix':deadline,
           'cpu_only':cpu_only,'automatic_retries':0}
    try:
        env=dict(os.environ)
        if cpu_only:env['CUDA_VISIBLE_DEVICES']=''
        with (out/'worker.log').open('xb') as log:
            child=subprocess.Popen(cmd,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        binding={'pid':child.pid,'start_ticks':g.start_ticks(child.pid)}
        if not binding['start_ticks']:raise RuntimeError('Cannot bind child identity')
        state.update(status='running',child_pid=child.pid,child_start_ticks=binding['start_ticks'])
        save(out/'status.json',state)
        save(ack,{**binding,'attempt':'invocation'})
        while child.poll() is None:
            checked_identity(binding)
            runtime_check(g,guard_root,expected_sha,deadline,started)
            state['wall_seconds']=time.monotonic()-started[1]
            save(out/'status.json',state);heartbeat();time.sleep(.5)
        if child.returncode!=0:raise RuntimeError('Frozen diagnostic worker failed; no retry')
        state.update(status='completed',worker_exit_code=child.returncode)
        save(out/'status.json',state)
    except BaseException as exc:
        state.update(status='failed',error_type=type(exc).__name__,error=str(exc))
        if child is not None and child.poll() is None and binding is not None:
            signal_bound(binding,signal.SIGINT,group=True)
            try:child.wait(timeout=20)
            except subprocess.TimeoutExpired:
                signal_bound(binding,signal.SIGKILL,group=True);child.wait(timeout=10)
        state['worker_exit_code']=None if child is None else child.poll()
        save(out/'status.json',state)
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watchdog',type=Path,required=True)
    args=parser.parse_args();p=json.loads(args.watchdog.read_text())
    if sys.platform!='linux':raise ValueError('Linux-only process watchdog')
    raise SystemExit(watchdog(p['parent'],p['supervisor'],p['worker'],p['deadline_unix'],p['receipt'],p.get('activation')))
