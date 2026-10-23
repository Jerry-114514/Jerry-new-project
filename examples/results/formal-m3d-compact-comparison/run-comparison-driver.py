"""Private development comparison of two prompt serializations, no gold input."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import runpy
import subprocess
import sys
import time

source=Path('/root/autodl-tmp/Jerry-formal-v2-20261022')
sys.path.insert(0,str(source))
from intentlab.core import canonical,digest
from intentlab.formal_data import read_jsonl,validate_cases,formal_prompt
from intentlab.model_backend import LocalBackend
from intentlab.prompts import prompt_ids
from intentlab.protocol import source_snapshot,model_snapshot,verify_official_assets

assert not subprocess.check_output(['git','-C',str(source),'status','--porcelain'])
assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD']).decode().strip()=='fa0cc94df39eb978e7b8609f5f8ee83b2e64eeb6'
root=Path('/root/autodl-tmp/compact-diagnostic-comparison-20261023')
root.mkdir(exist_ok=False)
adapted=Path('/root/autodl-tmp/wikisql-adapter-validation-20261023/source/runs/private-adaptation-v1')
natural=Path('/root/autodl-tmp/wikisql-natural-collection-20261023/private-export')
cases=read_jsonl(source/'examples/results/formal-m2b-source-triage/triage/coordinator-cases.jsonl')+read_jsonl(adapted/'cases.jsonl')+read_jsonl(natural/'first-two/intake/coordinator-cases.jsonl')+read_jsonl(natural/'remaining-ten/intake/coordinator-cases.jsonl')
validate_cases(cases)
assert len(cases)==104 and all(c['split'] in {'train','validation'} for c in cases)
compact=runpy.run_path(str(source/'examples/results/formal-m3c-context-coverage/compact-driver.py'))['compact_prompt']
cases_hash=digest(cases)
old=json.loads((source/'examples/results/formal-m3c-context-coverage/lengths-by-context.json').read_text())
assert cases_hash==old['2048']['cases_hash']
plan={'kind':'unreviewed_development_prompt_serialization_comparison','status':'prepared',
    'created_utc':datetime.now(timezone.utc).isoformat(),'source_commit':'fa0cc94df39eb978e7b8609f5f8ee83b2e64eeb6',
    'source_normalized_sha256':source_snapshot(source),'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'cases_hash':cases_hash,'views':104,'conditions':['full','compact'],'planned_calls':208,
    'order':'case order fixed to prior length audit; even index full then compact, odd compact then full',
    'context_limit':6144,'max_new_tokens':512,'token_budget_per_call':8192,'do_sample':False,
    'no_retry':True,'budget_reset_per_call':True,'model':'/root/autodl-tmp/models/Qwen3.5-9B',
    'gold_loaded':False,'human_accuracy':None,'formal_training_started':False,'formal_budget_approved':False,
    'metrics':['strict_schema_parse','predeclared_id_object_normalization','visible_reference_constraints','paired_prediction_disagreement','tokens','generation_seconds'],
    'warning':'Development interface/serialization check only. No labels, no semantic accuracy, no loss training, no formal comparison. Full raw outputs remain private.'}
def save():
    (root/'manifest.json').write_text(json.dumps(plan,indent=2)+'\n')
save()
backend=None
started=time.perf_counter()
try:
    backend=LocalBackend(plan['model'],'cuda',512,8192,context_limit=6144)
    assert backend.context==6144
    backend.torch.manual_seed(0)
    prompts={c['case_id']:{'full':formal_prompt(c['public']),'compact':compact(c['public'])} for c in cases}
    preflight=[{'case_id':c['case_id'],'condition':condition,'prompt_hash':digest(prompt),
        'prompt_tokens':len(prompt_ids(backend.tokenizer,prompt))} for c in cases for condition,prompt in prompts[c['case_id']].items()]
    assert all(r['prompt_tokens']+512<=6144 and r['prompt_tokens']+512<=8192 for r in preflight)
    (root/'preflight.json').write_text(json.dumps({'cases_hash':cases_hash,'rows':preflight},indent=2)+'\n')
    plan.update(status='running',loading_and_preflight_seconds=time.perf_counter()-started)
    save()
    with (root/'raw-calls.jsonl').open('x') as stream:
        count=0
        for index,case in enumerate(cases):
            order=('full','compact') if index%2==0 else ('compact','full')
            for condition in order:
                backend.reset()
                prompt=prompts[case['case_id']][condition]
                record={'call_index':count,'case_index':index,'case_id':case['case_id'],
                    'condition':condition,'prompt_hash':digest(prompt)}
                began=time.perf_counter()
                try:
                    result=backend.complete(prompt,role='analyzer')
                    record.update(status='generated',text=result['text'],usage=result['usage'])
                except (ValueError,RuntimeError,OSError,TimeoutError) as error:
                    record.update(status='error',text='',error_type=type(error).__name__,error=str(error))
                record.update(generation_seconds=time.perf_counter()-began,budget=backend.ledger.snapshot())
                stream.write(canonical(record)+'\n');stream.flush()
                count+=1
                if count%8==0:
                    print(json.dumps({'recorded_calls':count,'planned_calls':208}),flush=True)
    plan.update(status='completed',actual_calls=count,total_wall_seconds=time.perf_counter()-started,
        raw_calls_sha256=hashlib.sha256((root/'raw-calls.jsonl').read_bytes()).hexdigest())
    save()
finally:
    if backend is not None:backend.close()
snapshot=model_snapshot(plan['model'])
(root/'official-assets-after-run.json').write_text(json.dumps(verify_official_assets(snapshot,source),indent=2)+'\n')
print(json.dumps({'status':plan['status'],'calls':plan.get('actual_calls')}),flush=True)
