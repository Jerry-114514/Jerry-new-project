"""Approved diagnostic resource handoff; preserves frozen workers and inputs."""
import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import guarded_diagnostic_continuation as d
from limited_30h_diagnostics import load_lock,verify_files,verify_models,sha
from run_limited_30h_pipeline import archive_data,archive_unbacked_states


def validate_parent(p,parent,amendment):
    previous=amendment['previous_coordinator']
    if parent.get('pid')!=previous['pid'] or parent.get('start_ticks')!=previous['start_ticks']:
        raise ValueError('Previous coordinator identity differs')
    if parent.get('phase')!='diagnostic_generate' or parent.get('status')!='running':
        raise ValueError('Only the same running generation stage can be adopted')
    if parent['protocol_hash']!=p['lock_hash'] or amendment['protocol_hash']!=p['lock_hash']:
        raise ValueError('Original scientific lock changed')
    if set(parent['jobs'])!=set(p['jobs']) or len(parent['jobs'])!=6 or any(r['status']!='completed' for r in parent['jobs'].values()):
        raise ValueError('All six completed endpoints are required')
    if parent['active_stage_supervisor']!=amendment['adopted_stage'] or amendment['adopted_stage']['name']!='diagnostic-generate':
        raise ValueError('Original generation supervisor binding differs')


def supervise(protocol,guard_tools,guard_root,amendment_path):
    if sys.platform!='linux':raise ValueError('Linux-only diagnostic continuation')
    sys.path.insert(0,str(guard_tools));import additional_gpu_time_guard as g
    p=load_lock(protocol);root=Path(p['root']);source=root/'source'
    a=json.loads(Path(amendment_path).read_text())
    c,config_sha=g.read_config(guard_root);limits=d.policy(a,c,time.time())
    if config_sha!=a['duration_guard_config_sha256']:raise ValueError('Original guard binding changed')
    if set(a['extension_files_sha256'])!={'guarded_diagnostic_continuation.py','run_limited_diagnostic_continuation.py'}:
        raise ValueError('Both prospective supervision implementations must be pinned')
    for name,expected in a['extension_files_sha256'].items():
        if sha(Path(__file__).parent/name)!=expected:raise ValueError('Diagnostic continuation implementation changed')
    parent=json.loads((source/'diagnostic-handoff-parent-state.json').read_text())
    validate_parent(p,parent,a)
    old=a['previous_coordinator'];stage=a['adopted_stage'];worker=a['adopted_worker']
    if d.checked_identity(old)!=('T',old['start_ticks']):raise ValueError('Previous coordinator must be paused')
    if not d.live(d.checked_identity(stage)) or not d.live(d.checked_identity(worker)):
        raise ValueError('Original generation invocation is no longer live; no restart')
    observed=json.loads((root/'supervision/diagnostic-generate/status.json').read_text())
    if observed.get('supervisor_pid')!=stage['pid'] or observed.get('child_pid')!=worker['pid'] or observed.get('child_start_ticks')!=worker['start_ticks'] or observed.get('status')!='running':
        raise ValueError('Running invocation receipt differs')
    if observed.get('max_seconds')!=25200:raise ValueError('Original seven-hour diagnostic bound differs')
    manifest=json.loads((root/'predictions/manifest.json').read_text())
    if manifest['status']!='running' or manifest['gold_loaded'] is not False or (root/'reveal.claim.json').exists():
        raise ValueError('Generation must remain unsealed and gold unopened at prospective handoff')
    verify_files(p,list(p['files_sha256']));verify_models(p)
    g.admit(guard_root,limits['generation_deadline_unix']-time.time()+30)
    claim=json.loads((root/'pipeline.claim.json').read_text())
    original_started=claim['started_unix'];started=(time.time(),time.monotonic())
    state=dict(parent);state.update(pid=os.getpid(),start_ticks=g.start_ticks(os.getpid()),
                                   diagnostic_resource_amendment=a['kind'],previous_diagnostic_coordinator=old)
    me={'pid':state['pid'],'start_ticks':state['start_ticks']}
    def snapshot():
        state['wall_seconds']=time.time()-original_started;state['heartbeat_unix']=time.time()
        d.save(root/'status.json',state)
    def interrupted(*_):raise KeyboardInterrupt('Diagnostic coordinator interrupted')
    signal.signal(signal.SIGTERM,interrupted)
    accepted=source/'diagnostic-handoff-accepted.json'
    watchdog_config=source/'diagnostic-watchdog-config.json'
    watchdog_receipt=source/'diagnostic-watchdog-status.json'
    d.save(watchdog_config,{'parent':me,'supervisor':stage,'worker':worker,
                           'deadline_unix':limits['generation_deadline_unix'],'receipt':str(watchdog_receipt),
                           'activation':str(accepted)})
    watchdog=None;paused=False
    try:
        with (source/'diagnostic-watchdog.log').open('xb') as log:
            watchdog=subprocess.Popen([sys.executable,str(Path(d.__file__)),'--watchdog',str(watchdog_config)],
                                      cwd=p['core_source'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        watchdog_ticks=g.start_ticks(watchdog.pid)
        deadline=time.monotonic()+10
        while not watchdog_receipt.exists():
            if watchdog.poll() is not None or time.monotonic()>=deadline:raise RuntimeError('Independent watchdog did not become ready')
            time.sleep(.05)
        ready=json.loads(watchdog_receipt.read_text())
        if ready.get('pid')!=watchdog.pid or ready.get('start_ticks')!=watchdog_ticks or ready.get('status')!='watching':
            raise ValueError('Independent watchdog identity not acknowledged')
        d.signal_bound(stage,signal.SIGSTOP);paused=True
        deadline=time.monotonic()+2
        while d.checked_identity(stage)!=('T',stage['start_ticks']):
            if time.monotonic()>=deadline:raise RuntimeError('Original supervisor pause not acknowledged')
            time.sleep(.01)
        if not d.live(d.checked_identity(worker)):raise RuntimeError('Generation ended during handoff; no restart')
        d.runtime_check(g,guard_root,config_sha,limits['generation_deadline_unix'],started)
        snapshot()
        d.save(accepted,{**me,'same_original_supervisor':stage,'same_original_worker':worker,
                         'watchdog':{'pid':watchdog.pid,'start_ticks':watchdog_ticks},
                         'models_restarted':False,'clock_reset':False,'unix':time.time()})
    except BaseException:
        if paused:d.signal_bound(stage,signal.SIGCONT)
        raise
    outcome='failed'
    try:
        def adopted_heartbeat():
            if watchdog.poll() is not None and d.live(d.checked_identity(worker)):
                raise RuntimeError('Independent generation watchdog exited while child remained live')
            snapshot()
        d.wait_adopted(g,guard_root,config_sha,stage,worker,limits['generation_deadline_unix'],
                       root/'supervision/diagnostic-generate/status.json',adopted_heartbeat)
        if watchdog is not None:watchdog.wait(timeout=10)
        state.update(phase='diagnostic_reveal',original_generation_real_exit_verified=True,
                     active_stage_supervisor={**me,'name':'diagnostic-reveal','inline_supervision':True});snapshot()
        command=[sys.executable,str(Path(p['tools_root'])/'scripts/limited_30h_diagnostics.py'),'reveal',
                 '--protocol',str(protocol),'--ack','{ACK}','--owned-module','intentlab.diagnostic_protocol']
        d.invoke(g,guard_root,config_sha,p['core_source'],root/'supervision/diagnostic-reveal',
                 limits['gpu_deadline_unix'],'intentlab.diagnostic_protocol',command,snapshot)
        state.update(phase='statistics',active_stage_supervisor={**me,'name':'statistics','inline_supervision':True});snapshot()
        command=[sys.executable,str(Path(p['tools_root'])/'scripts/limited_30h_diagnostics.py'),'stats',
                 '--protocol',str(protocol),'--ack','{ACK}','--owned-module','intentlab.frozen_statistics']
        d.invoke(g,guard_root,config_sha,p['core_source'],root/'supervision/statistics',
                 limits['cpu_deadline_unix'],'intentlab.frozen_statistics',command,snapshot,cpu_only=True)
        state['limited_experiment_completed']=True;outcome='completed'
    except BaseException as exc:
        state.update(error_type=type(exc).__name__,error=str(exc),limited_experiment_completed=False)
    state.update(status='finalizing',phase='private_archive',outcome=outcome);snapshot()
    d.save(root/'state-for-archive.json',state)
    try:
        if outcome!='completed':state['partial_state']=archive_unbacked_states(root)
        state['final_data']=archive_data(root)
        state.update(status='awaiting_offhost_backup',phase='backup_receipt');snapshot()
        expected={k:v['backup']['sha256'] for k,v in state['jobs'].items()}
        while time.time()<limits['backup_deadline_unix']:
            d.runtime_check(g,guard_root,config_sha,limits['backup_deadline_unix'])
            path=root/'offhost-backup-receipt.json'
            if path.exists():
                r=json.loads(path.read_text())
                if r.get('protocol_hash')!=p['lock_hash'] or r.get('model_archives_sha256')!=expected or r.get('final_data_sha256')!=state['final_data']['sha256'] or r.get('all_member_hashes_verified') is not True:
                    raise ValueError('Off-host receipt does not match immutable private archives')
                if state.get('partial_state') and r.get('partial_state_sha256')!=state['partial_state']['sha256']:
                    raise ValueError('Partial-state receipt differs')
                state.update(status=outcome,phase='shutdown_requested',off_host_backup_verified=True);snapshot()
                os.sync()
                rc=subprocess.run(['/usr/bin/shutdown'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=30).returncode
                state.update(shutdown_exit_code=rc,provider_stop_verified=False);snapshot()
                return 0 if outcome=='completed' else 1
            snapshot();time.sleep(5)
        raise TimeoutError('Off-host backup acknowledgement did not fit the unchanged shutdown window')
    except BaseException as exc:
        state.update(status='failed',phase='backup_or_shutdown_requires_attention',backup_error_type=type(exc).__name__,backup_error=str(exc));snapshot()
        return 1


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('protocol','guard-tools','guard-root','amendment'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--owned-module',choices=('intentlab.matrix',),required=True)
    args=parser.parse_args()
    raise SystemExit(supervise(args.protocol,args.guard_tools,args.guard_root,args.amendment))
