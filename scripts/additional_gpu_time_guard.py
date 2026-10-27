"""Separate AutoDL duration guard; never edits the original cost guard.

Enforces an authorized time ceiling on an already running instance; installing
it does not authorize any new model work. A successful shutdown command is not
proof billing stopped; the coordinator must verify the provider/instance state.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


MAX_SECONDS=30*3600
ADMISSION_RESERVE=2*3600
SHUTDOWN_RESERVE=3600
MODULES={'intentlab.neural','intentlab.matrix','intentlab.matrix_worker',
         'intentlab.controller_plan','intentlab.diagnostic_protocol',
         'intentlab.frozen_execution','intentlab.frozen_ablation','intentlab.frozen_statistics'}


def sha(raw):return hashlib.sha256(raw).hexdigest()


def start_ticks(pid):
    try:return Path('/proc',str(pid),'stat').read_text().rsplit(')',1)[1].split()[19]
    except (OSError,IndexError,ValueError):return None


def original_snapshot(root,expected_sha,now_unix,now_monotonic,boot_id,identity=start_ticks):
    root=Path(root);raw=(root/'config.json').read_bytes()
    if sha(raw)!=expected_sha:raise ValueError('Original cost configuration changed')
    c=json.loads(raw);s=json.loads((root/'status.json').read_text())
    if (c['price_yuan_per_hour'],c['budget_yuan'],c['shutdown_reserve_yuan'])!=('2.88','500','10'):
        raise ValueError('Expected the unchanged original 500-yuan budget and 10-yuan reserve')
    if c['boot_id']!=boot_id or s['config_sha256']!=expected_sha:
        raise ValueError('Original cost guard boot/config binding mismatch')
    if s['status']!='monitoring' or not 0<=now_unix-s['unix']<=120:
        raise ValueError('Original cost guard heartbeat is not fresh and monitoring')
    if type(s['pid']) is not int or s['pid']<=0 or not isinstance(s.get('start_ticks'),str) \
            or not s['start_ticks'] or identity(s['pid'])!=s['start_ticks']:
        raise ValueError('Original cost guard process is not alive with the recorded identity')
    remaining=c['stop_monotonic']-now_monotonic
    if not math.isfinite(remaining) or remaining<=0:raise ValueError('Original cost deadline exhausted')
    return c,remaining


def make_window(now_unix,now_monotonic,boot_id,original_remaining,start_unix=None):
    if any(type(v) not in (int,float) or not math.isfinite(v) for v in (now_unix,now_monotonic,original_remaining)):
        raise ValueError('Finite clock and remaining-budget values required')
    anchor=now_unix if start_unix is None else start_unix
    if type(anchor) not in (int,float) or not math.isfinite(anchor) or anchor<=0 or anchor>now_unix:
        raise ValueError('A fixed finite start anchor no later than now is required')
    elapsed_before_install=now_unix-anchor
    seconds=min(MAX_SECONDS,elapsed_before_install+original_remaining)
    if now_unix<=0 or now_monotonic<elapsed_before_install or seconds-elapsed_before_install<=ADMISSION_RESERVE:
        raise ValueError('Insufficient operating window after reserves')
    return {'schema_version':1,'start_unix':anchor,'start_monotonic':now_monotonic-elapsed_before_install,
            'boot_id':boot_id,'window_seconds':seconds,'authorized_max_seconds':MAX_SECONDS,
            'installed_unix':now_unix,'elapsed_before_install_seconds':elapsed_before_install,
            'admission_reserve_seconds':ADMISSION_RESERVE,'shutdown_reserve_seconds':SHUTDOWN_RESERVE,
            'accounting':'Conservative continuous instance wall clock, including idle/loading/transfer; no pause or reset.'}


def decision(c,now_unix,now_monotonic,boot_id):
    if boot_id!=c['boot_id']:raise ValueError('Boot changed; the recorded duration window must not be restarted')
    if any(not math.isfinite(v) for v in (now_unix,now_monotonic)) or now_monotonic<c['start_monotonic']:
        raise ValueError('Invalid or regressed monotonic clock')
    elapsed=max(now_unix-c['start_unix'],now_monotonic-c['start_monotonic'])
    remaining=c['window_seconds']-elapsed
    return {'elapsed_seconds':elapsed,'remaining_seconds':remaining,
            'admission_open':remaining>c['admission_reserve_seconds'],
            'shutdown_due':remaining<=c['shutdown_reserve_seconds'],
            'hard_limit_reached':remaining<=0}


def atomic_status(root,value):
    temp=root/'status.tmp'
    with temp.open('w',encoding='utf-8',newline='\n') as f:
        json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    temp.replace(root/'status.json')


def read_config(root):
    raw=(Path(root)/'config.json').read_bytes()
    return json.loads(raw),sha(raw)


def admit(root,max_job_seconds,identity=start_ticks):
    c,config_sha=read_config(root);now=time.time();mono=time.monotonic()
    boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    original_snapshot(c['original_guard_root'],c['original_config_sha256'],now,mono,boot,identity)
    s=json.loads((Path(root)/'status.json').read_text())
    if s.get('status')!='monitoring' or s.get('config_sha256')!=config_sha or not 0<=now-s['unix']<=45 \
            or type(s.get('pid')) is not int or s['pid']<=0 or not isinstance(s.get('start_ticks'),str) \
            or not s['start_ticks'] or identity(s['pid'])!=s['start_ticks']:
        raise ValueError('Additional duration guard is not freshly live with the recorded configuration')
    if sha(Path(c['guard_script']).read_bytes())!=c['guard_script_sha256']:
        raise ValueError('Duration guard implementation changed')
    state=decision(c,now,mono,boot)
    if type(max_job_seconds) not in (int,float) or not math.isfinite(max_job_seconds) or max_job_seconds<=0:
        raise ValueError('A finite positive job duration bound is required')
    if not state['admission_open'] or max_job_seconds+30>=state['remaining_seconds']-SHUTDOWN_RESERVE:
        raise ValueError('Job cannot fit before the duration guard shutdown reserve')
    return {**state,'max_job_seconds':max_job_seconds,'config_sha256':config_sha,
            'admission_only':True,'warning':'Caller must enforce the job timeout; this check does not launch or time a job.'}


def owned_groups(c):
    groups=set()
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit():continue
        try:
            args=(proc/'cmdline').read_bytes().decode(errors='replace').split('\0')
            if not MODULES.intersection(args) or str((proc/'cwd').resolve()) not in c['owned_source_roots']:continue
            group=os.getpgid(int(proc.name))
            if group!=os.getpgrp():groups.add(group)
        except (OSError,ValueError):continue
    return groups


def stop_owned(c):
    groups=owned_groups(c)
    for group in groups:
        try:os.killpg(group,signal.SIGINT)
        except ProcessLookupError:pass
    time.sleep(30)
    # After the recorded grace period, do not leave a wedged worker consuming GPU.
    remaining=owned_groups(c)  # Revalidate ownership after grace; PGIDs can be reused.
    for group in remaining:
        try:os.killpg(group,signal.SIGKILL)
        except ProcessLookupError:pass
    return sorted(groups|remaining)


def watch(root):
    if sys.platform!='linux':raise ValueError('Remote watcher is Linux-only')
    import fcntl
    root=Path(root)
    with (root/'watch.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        c,config_sha=read_config(root);pid=os.getpid();ticks=start_ticks(pid)
        base={'pid':pid,'start_ticks':ticks,'config_sha256':config_sha,'instance_stopped_verified':False}
        while True:
            now,mono=time.time(),time.monotonic()
            try:
                if read_config(root)[1]!=config_sha or sha(Path(c['guard_script']).read_bytes())!=c['guard_script_sha256']:
                    raise ValueError('Duration configuration or implementation changed')
                boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
                original_snapshot(c['original_guard_root'],c['original_config_sha256'],now,mono,boot)
                state=decision(c,now,mono,boot)
                if state['shutdown_due']:raise ValueError('Duration shutdown reserve reached')
                atomic_status(root,{**base,**state,'status':'monitoring','unix':now})
            except (OSError,ValueError,KeyError,TypeError) as exc:
                atomic_status(root,{**base,'status':'stopping_owned_jobs','reason':str(exc),'unix':time.time()})
                groups=stop_owned(c);os.sync()
                for attempt in range(1,4):
                    atomic_status(root,{**base,'status':'issuing_instance_shutdown','attempt':attempt,'groups':groups,'unix':time.time()})
                    try:
                        rc=subprocess.run(['/usr/bin/shutdown'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30).returncode
                    except (OSError,subprocess.TimeoutExpired):rc=None
                    atomic_status(root,{**base,'status':'shutdown_unverified_requires_external_check',
                                        'attempt':attempt,'shutdown_exit_code':rc,'unix':time.time()})
                    time.sleep(60)  # Successful provider stop normally terminates this process.
                return 2  # Preserve failure; coordinator must request/perform external instance stop.
            time.sleep(15)


def install(root,original_root,expected_sha,start_unix):
    if sys.platform!='linux':raise ValueError('Remote installation is Linux-only')
    root,original_root=Path(root).resolve(),Path(original_root).resolve()
    if root.exists() or root.is_relative_to(original_root) or original_root.is_relative_to(root):
        raise ValueError('Use a fresh separate duration directory; never reset an existing window')
    now,mono=time.time(),time.monotonic();boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    old,remaining=original_snapshot(original_root,expected_sha,now,mono,boot)
    if any(root.is_relative_to(Path(p).resolve()) for p in old['owned_source_roots']):
        raise ValueError('Duration records must stay outside frozen scientific source')
    if not os.access('/usr/bin/shutdown',os.X_OK):raise ValueError('Official AutoDL shutdown command missing')
    c=make_window(now,mono,boot,remaining,start_unix)
    c.update(original_guard_root=str(original_root),original_config_sha256=expected_sha,
             owned_source_roots=old['owned_source_roots'],guard_script=str(Path(__file__).resolve()),
             guard_script_sha256=sha(Path(__file__).read_bytes()))
    root.mkdir(mode=0o700,parents=True,exist_ok=False)
    path=root/'config.json';path.write_text(json.dumps(c,indent=2)+'\n',encoding='utf-8');path.chmod(0o400)
    with (root/'watch.log').open('xb') as log:
        child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'watch','--root',str(root)],
                               stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    return {'pid':child.pid,'config_sha256':sha(path.read_bytes()),'window_seconds':c['window_seconds'],
            'status':'spawned_not_yet_verified','original_budget_modified':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('install','watch','admit'))
    p.add_argument('--root',type=Path,required=True);p.add_argument('--original-root',type=Path)
    p.add_argument('--original-config-sha256');p.add_argument('--max-job-seconds',type=float)
    p.add_argument('--start-unix',type=float);a=p.parse_args()
    if a.action=='install':
        if a.original_root is None or a.original_config_sha256 is None or a.start_unix is None:
            p.error('Original guard binding and a fixed start timestamp are required')
        print(json.dumps(install(a.root,a.original_root,a.original_config_sha256,a.start_unix)))
    elif a.action=='watch':raise SystemExit(watch(a.root))
    else:print(json.dumps(admit(a.root,a.max_job_seconds)))
