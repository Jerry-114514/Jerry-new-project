import hashlib,json,os,subprocess,sys,time
from pathlib import Path
src=Path('/root/autodl-tmp/Jerry-formal-v2-20261022')
out=Path('/root/autodl-tmp/fixed-k-development-20261023')
python='/root/autodl-tmp/intentlab-venv/bin/python'
if '--launch' in sys.argv:
    assert not out.exists(),'Do not restart an existing experiment'
    log=out.with_suffix('.log')
    with log.open('x') as f:
        p=subprocess.Popen([python,str(Path(__file__).resolve())],stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
    print(json.dumps({'pid':p.pid,'log':str(log),'root':str(out)}));raise SystemExit
sys.path.insert(0,str(src))
from intentlab.core import digest
from intentlab.execution_data import load_execution_tasks,load_references
from intentlab.formal_data import write_jsonl
from intentlab.protocol import model_snapshot,verify_official_assets
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def git(*args):return subprocess.check_output(['git','-C',str(src),*args],text=True).strip()
assert git('rev-parse','HEAD')=='d80be96feedd06daf0b2340bfedd24e900b23d7a'
assert not git('status','--porcelain')
assert json.loads(Path('/root/autodl-tmp/history-pressure-20261023/status.json').read_text())['status']=='completed'
assert not subprocess.check_output(['nvidia-smi','--query-compute-apps=pid','--format=csv,noheader'],text=True).strip()
config=Path('/root/autodl-tmp/fixed-k-history-candidate-20261023.json')
assert sha(config)=='fa5ba61c478be1d8fa2fb1f97e995ad130a1d867ffb9e40fbffe4d9a4d479813'
spec=json.loads(config.read_text())
assert spec['budgets']=={'token_budget':49152,'max_new_tokens':1536,'max_repairs':3,'context_limit':17408}
out.mkdir(mode=0o700,exist_ok=False)
status={'status':'preparing','pid':os.getpid(),'process_start_ticks':Path('/proc/self/stat').read_text().split()[21],'source_commit':git('rev-parse','HEAD'),'plan_commit':'c0c3ed44459ae7da9c828e0cdaa07ebe45cb9b9d','config_sha256':sha(config),'driver_sha256':sha(__file__),'formal_training':False,'planned_runs':450,'started_unix':time.time()}
def save(): (out/'status.json').write_text(json.dumps(status,indent=2)+'\n')
save()
try:
    base=Path('/root/autodl-tmp/combined-natural-candidate-20261023')
    tasks=load_execution_tasks(base/'tasks.jsonl')
    refs=load_references(base/'references.jsonl',tasks)
    selected=[t for t in tasks if t['split']=='validation']
    assert len(selected)==150 and len({t['source_task_id'] for t in selected})==150
    subset={t['id']:refs[t['id']] for t in selected}
    write_jsonl(out/'tasks.jsonl',selected);write_jsonl(out/'references.jsonl',list(subset.values()))
    status['validation_tasks_hash']=digest(selected)
    status['official_asset_verification']=verify_official_assets(model_snapshot('/root/autodl-tmp/models/Qwen3.5-9B'),src)
    model='/root/autodl-tmp/models/Qwen3.5-9B'
    cmd=[python,'-m','intentlab.controller_plan','--tasks',str(out/'tasks.jsonl'),'--references',str(out/'references.jsonl'),'--settings',str(config),'--actor-model',model,'--analyzer-model',model,'--out',str(out/'selection'),'--device','cuda']
    with (out/'execution.log').open('w') as f:
        child=subprocess.Popen(cmd,cwd=src,stdout=f,stderr=subprocess.STDOUT)
        status.update(status='running',child_pid=child.pid,command=cmd);save()
        code=child.wait()
    assert git('rev-parse','HEAD')==status['source_commit'] and not git('status','--porcelain')
    assert sha(config)==status['config_sha256']
    status.update(status='completed' if code==0 else 'failed',exit_code=code,finished_unix=time.time());save()
except Exception as e:
    status.update(status='failed',error_type=type(e).__name__,error=str(e),finished_unix=time.time());save();raise
