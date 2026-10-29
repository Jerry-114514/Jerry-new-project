"""User-approved resource continuation; frozen scientific inputs and workers are reused."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import time

from limited_30h_diagnostics import load_lock,verify_files,save,sha,verify_models

ORDER=[f'{k}-seed-{s}' for s in (0,1,2) for k in ('D','E')]


def archive_data(root):
    root=Path(root);index={}
    files=[]
    for folder in ('training','public','sealed','configs','analysis','predictions','scores','timings','supervision','source','jobs'):
        base=root/folder
        if not base.exists():continue
        for path in sorted(base.rglob('*')):
            if not path.is_file() or path.is_symlink():continue
            relative=path.relative_to(root)
            if folder=='jobs' and ('model' in relative.parts or 'download-cache' in relative.parts or path.name.startswith('latest.')):continue
            files.append(path)
    for name in ('protocol.lock.json','model-binding.json','resource-plan.json','state-for-archive.json'):
        if (root/name).is_file():files.append(root/name)
    for path in files:
        name=path.relative_to(root).as_posix()
        index[name]={'bytes':path.stat().st_size,'sha256':sha(path)}
    payload=json.dumps({'kind':'private_limited_followup_data','files':index},sort_keys=True).encode()
    temp=root/'final-data.partial.tar.gz'
    with tarfile.open(temp,'x:gz') as a:
        info=tarfile.TarInfo('backup-index.json');info.size=len(payload);a.addfile(info,io.BytesIO(payload))
        for path in files:a.add(path,arcname=path.relative_to(root).as_posix(),recursive=False)
    for path in files:
        if sha(path)!=index[path.relative_to(root).as_posix()]['sha256']:raise ValueError('Source changed while archiving')
    final=root/'final-data.tar.gz';temp.rename(final)
    return {'path':str(final),'bytes':final.stat().st_size,'sha256':sha(final),'members':len(index)+1}


def archive_unbacked_states(root):
    """Content preservation only; never certify an incomplete checkpoint."""
    root=Path(root);files=[]
    for name in ORDER:
        if (root/'backups'/name/'model.tar').is_file():continue
        job=root/'jobs'/name
        for path in sorted(job.rglob('*')) if job.exists() else ():
            if path.is_file() and not path.is_symlink() and (path.name.startswith('latest.') or 'model' in path.relative_to(job).parts):files.append(path)
    if not files:return None
    index={p.relative_to(root).as_posix():{'bytes':p.stat().st_size,'sha256':sha(p)} for p in files}
    payload=json.dumps({'kind':'unvalidated_partial_state','files':index},sort_keys=True).encode()
    target=root/'backups/partial-state.tar'
    with tarfile.open(target,'x:') as a:
        info=tarfile.TarInfo('backup-index.json');info.size=len(payload);a.addfile(info,io.BytesIO(payload))
        for path in files:a.add(path,arcname=path.relative_to(root).as_posix(),recursive=False)
    if any(sha(path)!=index[path.relative_to(root).as_posix()]['sha256'] for path in files):
        raise ValueError('Partial state changed during preservation')
    return {'path':str(target),'sha256':sha(target),'bytes':target.stat().st_size,'scope':'unvalidated_partial_state'}



def validate_resource_handoff(amendment,parent,claim,guard_config,stage_seconds):
    if amendment.get('kind')!='approved_training_resource_reallocation_v1' or amendment.get('user_approved') is not True:
        raise ValueError('Explicit approved resource amendment required')
    if (amendment['original_training_seconds'],amendment['amended_training_seconds'])!=(17*3600,18*3600):
        raise ValueError('Only the approved one-hour stage reallocation is allowed')
    if stage_seconds!={'training':61200,'diagnostics':25200,'backup':3600}:
        raise ValueError('Frozen stage budgets differ')
    if claim['started_unix']!=amendment['original_pipeline_started_unix'] or guard_config['start_unix']!=amendment['absolute_start_unix']:
        raise ValueError('Original clocks must not reset')
    if guard_config['authorized_max_seconds']!=108000 or guard_config['window_seconds']>108000:
        raise ValueError('Overall duration limit changed')
    deadline=claim['started_unix']+amendment['amended_training_seconds']
    stop=guard_config['start_unix']+guard_config['window_seconds']-guard_config['shutdown_reserve_seconds']
    if deadline+stage_seconds['diagnostics']+stage_seconds['backup']>stop:
        raise ValueError('Reallocation cannot reserve the original downstream phases before shutdown')
    expected={name:'completed' for name in ORDER[:4]}
    expected.update({'D-seed-2':'running','E-seed-2':'not_started'})
    if {name:row['status'] for name,row in parent['jobs'].items()}!=expected or parent['phase']!='training':
        raise ValueError('Handoff is restricted to the same fifth job before sixth dispatch')
    if parent['active_stage_supervisor']!=amendment['adopted_stage']:
        raise ValueError('Active supervised invocation identity differs')
    if parent['pid']!=amendment['previous_coordinator']['pid'] or parent['start_ticks']!=amendment['previous_coordinator']['start_ticks']:
        raise ValueError('Previous coordinator identity differs')
    if claim['protocol_hash']!=parent['protocol_hash'] or parent['protocol_hash']!=amendment['protocol_hash']:
        raise ValueError('Scientific lock differs')
    return deadline


def process_identity(pid):
    try:
        values=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
        return values[0],values[19]
    except FileNotFoundError:return None


def adopt_stage(root,stage,worker,snapshot):
    # This function never starts, signals, or changes acknowledgement files for a model.
    while True:
        observed=json.loads((Path(root)/'supervision'/stage['name']/'status.json').read_text())
        if observed.get('supervisor_pid')!=stage['pid'] or observed.get('child_pid')!=worker['pid'] or observed.get('child_start_ticks')!=worker['start_ticks']:
            raise ValueError('Adopted invocation binding changed')
        supervisor=process_identity(stage['pid']);child=process_identity(worker['pid'])
        for actual,expected in ((supervisor,stage['start_ticks']),(child,worker['start_ticks'])):
            if actual and actual[1]!=expected:raise ValueError('Adopted PID was reused')
        live=lambda x:x is not None and x[0] not in ('Z','X')
        if not live(supervisor) and not live(child):
            if observed['status']!='completed' or observed.get('worker_exit_code')!=0:
                raise RuntimeError('Adopted stage did not complete; no retry')
            return
        if not live(supervisor) and live(child):raise RuntimeError('Supervisor missing while child remains; no new work dispatched')
        snapshot();time.sleep(15)


def supervise(protocol,guard_tools,guard_root,amendment_path):
    p=load_lock(protocol);sys.path.insert(0,str(guard_tools))
    import additional_gpu_time_guard as g
    from intentlab.core import digest
    from intentlab.formal_data import read_jsonl
    from intentlab.checkpoint_selection import best_validation
    from intentlab.model_backup import inventory,create_model_backup,verify_model_backup
    root=Path(p['root'])
    amendment=json.loads(Path(amendment_path).read_text())
    parent=json.loads((root/'source/resource-handoff-parent-state.json').read_text())
    claim=json.loads((root/'pipeline.claim.json').read_text())
    config,config_sha=g.read_config(guard_root)
    training_deadline=validate_resource_handoff(amendment,parent,claim,config,p['stage_seconds'])
    if sha(Path(__file__))!=amendment['continuation_source_sha256']:raise ValueError('Continuation source changed')
    previous=amendment['previous_coordinator']
    if process_identity(previous['pid'])!=('T',previous['start_ticks']):raise ValueError('Old coordinator must be paused with matching identity')
    if parent['protocol_hash']!=p['lock_hash']:raise ValueError('Frozen scientific lock changed')
    g.admit(guard_root,60)
    verify_files(p,list(p['files_sha256']))
    started=time.monotonic()-(time.time()-claim['started_unix'])
    state=parent
    state.update(pid=os.getpid(),start_ticks=g.start_ticks(os.getpid()),status='running',
                 resource_amendment='approved_training_resource_reallocation_v1',
                 previous_coordinator=previous,training_deadline_unix=training_deadline)
    successor={'pid':state['pid'],'start_ticks':state['start_ticks'],'previous_coordinator':previous,
               'training_deadline_unix':training_deadline,'models_restarted':False,'clocks_reset':False,
               'continuation_source_sha256':amendment['continuation_source_sha256']}
    with (root/'source/resource-successor.claim.json').open('x') as f:json.dump(successor,f)
    def snapshot():
        state['wall_seconds']=time.monotonic()-started;state['heartbeat_unix']=time.time()
        temp=root/'status.tmp';save(temp,state);temp.replace(root/'status.json')
    def invoke(name,module,seconds,child):
        g.admit(guard_root,seconds)
        command=[sys.executable,str(Path(p['tools_root'])/'scripts/guarded_30h_invocation.py'),
                 '--guard-tools',str(guard_tools),'--guard-root',str(guard_root),'--cwd',p['core_source'],
                 '--out',str(root/'supervision'/name),'--max-seconds',str(seconds),
                 '--owned-module',module,'--']+child
        with (root/(name+'-supervisor.log')).open('xb') as log:
            proc=subprocess.Popen(command,cwd=p['core_source'],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
        state['active_stage_supervisor']={'pid':proc.pid,'start_ticks':g.start_ticks(proc.pid),'name':name}
        while proc.poll() is None:
            snapshot()
            try:proc.wait(timeout=15)
            except subprocess.TimeoutExpired:pass
        state['last_stage_exit_code']=proc.returncode;snapshot()
        if proc.returncode:raise RuntimeError('Stage failed, retained without automatic restart: '+name)
        observed=json.loads((root/'supervision'/name/'status.json').read_text())
        if observed['status']!='completed' or observed['worker_exit_code']!=0:raise ValueError('Stage completion receipt invalid')
    snapshot()
    save(root/'source/resource-handoff-accepted.json',successor)
    outcome='failed';backup_started=None
    try:
        for folder in ('jobs','timings','backups','supervision'):(root/folder).mkdir(exist_ok=True)
        verify_files(p,list(p['files_sha256']))  # Coordinator only; never passes gold to a model.
        train_rows=read_jsonl(root/'training/train.jsonl');validation=read_jsonl(root/'training/validation.jsonl')
        data_hash=digest({'train':train_rows,'validation':validation})
        if data_hash!=p['training_data_hash']:raise ValueError('Training data binding changed')
        model_jobs={};phase_started=time.monotonic();state['phase']='training';snapshot()
        for name in ORDER:
            verify_files(p,['training/train.jsonl','training/validation.jsonl','configs/'+name+'.json'])
            seconds=min(4*3600,training_deadline-time.time())
            if seconds<60:raise TimeoutError('Training phase exhausted before all six jobs')
            previous_status=state['jobs'][name]['status']
            job=p['jobs'][name]
            child=[sys.executable,str(Path(p['tools_root'])/'scripts/timed_neural_worker.py'),
                   '--source',p['core_source'],'--core-commit',p['core_commit'],'--ack','{ACK}',
                   '--timing-output',str(root/'timings'/(name+'.jsonl')),'--owned-module','intentlab.neural',
                   '--','--config',str(root/'configs'/(name+'.json')),'--out',job['out']]
            if previous_status=='completed':
                pass
            elif previous_status=='running' and name==amendment['adopted_stage']['name']:
                adopt_stage(root,amendment['adopted_stage'],amendment['adopted_worker'],snapshot)
                state['last_stage_exit_code']=0
            elif previous_status=='not_started':
                state['jobs'][name]['status']='running';snapshot()
                invoke(name,'intentlab.neural',seconds,child)
            else:raise ValueError('No duplicate dispatch or automatic retry is allowed')
            result=json.loads(Path(job['out'],'result.json').read_text())
            exposures=result['sample_exposures']
            if result['completed'] is not True or result['step']!=p['training']['steps'] or result['config']!=job['config'] \
                    or result.get('test_deferred') is not True or result['data_hash']!=data_hash \
                    or result['base_identity']!=p['base_identity'] or result['examples_seen']!=len(train_rows) \
                    or result['supervised_tokens']!=p['training_supervised_tokens'] \
                    or len(exposures)!=len(train_rows) or any(r['count']!=1 for r in exposures) \
                    or {r['case_id'] for r in exposures}!={r['case_id'] for r in train_rows} \
                    or len(result['history'])!=6 or result['selection']['step']!=best_validation(result['history'])['step']:
                raise ValueError('Training coverage/configuration/selection verification failed: '+name)
            files=inventory(Path(job['out']))
            row={'status':'completed','config':result['config'],'result_sha256':files['result.json']['sha256'],
                 'artifacts_sha256':{k:v['sha256'] for k,v in files.items() if k=='latest.pt' or k.startswith('model/')}}
            if previous_status=='completed':
                previous_backup=state['jobs'][name]['backup']
                verify_model_backup(root/'backups'/name/'model.tar',previous_backup['sha256'])
                with tarfile.open(root/'backups'/name/'model.tar') as handle:
                    index=json.load(handle.extractfile('backup-index.json'))
                if index['protocol_hash']!=p['lock_hash'] or index['matrix_job_hash']!=digest(row):
                    raise ValueError('Existing backup does not match the recomputed completed endpoint binding')
                backup=json.loads((root/'backups'/name/'manifest.json').read_text())
                if backup['verification']['archive_sha256']!=previous_backup['sha256']:raise ValueError('Existing backup manifest changed')
            else:backup=create_model_backup(job['out'],root/'backups'/name,row,p['lock_hash'])
            bound={'config':result['config'],'base_identity':result['base_identity'],'data_hash':data_hash,
                   'initial_trainable_sha256':result['initial_trainable_sha256'],
                   'selected_files_sha256':{k:v['sha256'] for k,v in files.items() if k.startswith('model/')},
                   'result_sha256':row['result_sha256']}
            model_jobs[name]=bound
            state['jobs'][name]={'status':'completed','step':result['step'],'examples_seen':result['examples_seen'],
                                'supervised_tokens':result['supervised_tokens'],'best_step':result['selection']['step'],
                                'backup':{'path':str(root/'backups'/name/'model.tar'),
                                          'sha256':backup['verification']['archive_sha256'],
                                          'bytes':(root/'backups'/name/'model.tar').stat().st_size}}
            snapshot()
        binding={'protocol_hash':p['lock_hash'],'jobs':model_jobs};binding['binding_hash']=digest(binding)
        save(root/'model-binding.json',binding);verify_models(p)
        state.update(model_binding_created=True,phase='diagnostic_generation');snapshot()
        phase_started=time.monotonic()
        for action in ('generate','reveal'):
            seconds=p['stage_seconds']['diagnostics']-(time.monotonic()-phase_started)
            if seconds<60:raise TimeoutError('Diagnostic budget exhausted')
            state['phase']='diagnostic_'+action;snapshot()
            child=[sys.executable,str(Path(p['tools_root'])/'scripts/limited_30h_diagnostics.py'),action,
                   '--protocol',str(protocol),'--ack','{ACK}','--owned-module','intentlab.diagnostic_protocol']
            invoke('diagnostic-'+action,'intentlab.diagnostic_protocol',seconds,child)
        backup_started=time.monotonic();state['phase']='statistics';snapshot()
        child=[sys.executable,str(Path(p['tools_root'])/'scripts/limited_30h_diagnostics.py'),'stats',
               '--protocol',str(protocol),'--ack','{ACK}','--owned-module','intentlab.frozen_statistics']
        invoke('statistics','intentlab.frozen_statistics',1800,child)
        state['limited_experiment_completed']=True;outcome='completed'
    except BaseException as exc:
        state.update(error_type=type(exc).__name__,error=str(exc),limited_experiment_completed=False)
        for row in state['jobs'].values():
            if row['status']=='running':row['status']='failed'
    state.update(status='finalizing',phase='private_archive',outcome=outcome);snapshot()
    if backup_started is None:backup_started=time.monotonic()
    # The immutable archive snapshot avoids hashing the coordinator heartbeat.
    save(root/'state-for-archive.json',state)
    try:
        if outcome!='completed':state['partial_state']=archive_unbacked_states(root)
        state['final_data']=archive_data(root)
        state.update(status='awaiting_offhost_backup',phase='backup_receipt');snapshot()
        deadline=backup_started+p['stage_seconds']['backup']
        while time.monotonic()<deadline:
            receipt=root/'offhost-backup-receipt.json'
            if receipt.exists():
                r=json.loads(receipt.read_text())
                expected={k:v['backup']['sha256'] for k,v in state['jobs'].items() if v.get('backup')}
                if r.get('protocol_hash')!=p['lock_hash'] or r.get('model_archives_sha256')!=expected \
                        or r.get('final_data_sha256')!=state['final_data']['sha256'] or r.get('all_member_hashes_verified') is not True:
                    raise ValueError('Off-host backup receipt does not match immutable archives')
                if state.get('partial_state') and r.get('partial_state_sha256')!=state['partial_state']['sha256']:
                    raise ValueError('Unvalidated partial-state preservation receipt missing')
                state.update(status=outcome,phase='shutdown_requested',off_host_backup_verified=True);snapshot()
                os.sync()
                rc=g.request_shutdown()['returncode']
                state.update(shutdown_exit_code=rc,provider_stop_verified=False);snapshot();return 0 if outcome=='completed' else 1
            snapshot();time.sleep(15)
        raise TimeoutError('Off-host backup receipt not received in reserved hour')
    except BaseException as exc:
        state.update(status='failed',phase='backup_or_shutdown_requires_attention',
                     backup_error_type=type(exc).__name__,backup_error=str(exc));snapshot();return 1


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--protocol',type=Path,required=True);p.add_argument('--guard-tools',type=Path,required=True)
    p.add_argument('--guard-root',type=Path,required=True);p.add_argument('--owned-module',choices=('intentlab.matrix',),required=True)
    p.add_argument('--amendment',type=Path,required=True)
    a=p.parse_args();raise SystemExit(supervise(a.protocol,a.guard_tools,a.guard_root,a.amendment))
