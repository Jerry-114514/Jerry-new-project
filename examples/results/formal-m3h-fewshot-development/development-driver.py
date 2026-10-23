"""Development-only few-shot comparison; never open heldout files."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

SOURCE = Path('/root/autodl-tmp/Jerry-formal-v2-20261022')
DATA = Path('/root/autodl-tmp/procedural-candidates-v3-20261023/export')
ROOT = Path('/root/autodl-tmp/procedural-fewshot-development-20261023')
MODEL = Path('/root/autodl-tmp/models/Qwen3.5-9B')
sys.path.insert(0, str(SOURCE))
from intentlab.core import canonical, digest
from intentlab.formal_data import formal_prompt, validate_cases, validate_findings
from intentlab.formal_inference import diagnostic_prompt, reject_example_overlap
from intentlab.prompts import prompt_ids

def read(path):
    return json.loads(path.read_text(encoding='utf-8'))

def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True)+'\n', encoding='utf-8')

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]

def prepare():
    from transformers import AutoTokenizer
    assert subprocess.check_output(['git','-C',str(SOURCE),'rev-parse','HEAD'],text=True).strip() == 'b4a757afc7c01332734fb6e4c2f08f3f7fcceef9'
    assert not subprocess.check_output(['git','-C',str(SOURCE),'status','--porcelain'])
    expected = read(SOURCE/'examples/results/formal-m2j-procedural-candidates/private-file-sha256.json')
    ROOT.mkdir(mode=0o700, exist_ok=False)
    (ROOT/'driver.py').write_bytes(Path(__file__).read_bytes())
    save(ROOT/'status.json', {'phase':'preparation', 'status':'running', 'pid':os.getpid()})
    cases, gold, pairs = {}, {}, {}
    for split, count in [('train',2400),('validation',600)]:
        path = DATA/(split+'.jsonl')
        assert sha(path) == expected['export/'+path.name]
        pairs[split] = rows(path)
        assert len(pairs[split]) == count
        cases[split] = []
        gold[split] = {}
        for pair in pairs[split]:
            public = json.loads(pair['prompt'].split('\n',1)[1].rsplit('\nJSON:\n',1)[0])['public']
            assert formal_prompt(public) == pair['prompt']
            case = {'case_id':pair['case_id'], 'source_task_id':pair['task_id'], 'split':split,
                    'family':pair['family'], 'template_id':pair['template_id'], 'source':pair['source'], 'public':public}
            findings = json.loads(pair['completion'])['findings']
            validate_findings(findings, public)
            cases[split].append(case)
            gold[split][case['case_id']] = findings
        validate_cases(cases[split])
    # Selection is fixed before any model output: semantic profile, distinct
    # family and source, then SHA256(case_id), never example length or accuracy.
    profiles = [('complete',lambda c,s: s == {'satisfied'} and c['case_id'].endswith('-complete')),
                ('combined',lambda c,s: s == {'violated'} and c['case_id'].endswith('-combined-fault')),
                ('hidden',lambda c,s: 'unknown' in s and c['case_id'].endswith('-hidden-history')),
                ('single',lambda c,s: 'violated' in s and 'satisfied' in s and c['case_id'].endswith('-single-fault-v2'))]
    examples = []
    for profile, predicate in profiles:
        candidates = [c for c in cases['train'] if c['family'] not in {e['case']['family'] for e in examples}
                      and predicate(c,{f['status'] for f in gold['train'][c['case_id']]})]
        assert candidates, profile
        case = min(candidates,key=lambda c:hashlib.sha256(c['case_id'].encode()).hexdigest())
        examples.append({'case':case, 'findings':gold['train'][case['case_id']]})
    reject_example_overlap(cases['validation'],examples)
    tokenizer = AutoTokenizer.from_pretrained(MODEL,local_files_only=True,trust_remote_code=False)
    length_rows = []
    for name, subset in [('A',[]),('B3',examples[:3]),('B4',examples)]:
        values = []
        for case in cases['validation']:
            n = len(prompt_ids(tokenizer,diagnostic_prompt(case,subset)))
            values.append(n)
            length_rows.append({'condition':name,'case_id':case['case_id'],'prompt_tokens':n})
        values.sort()
        save(ROOT/(name+'-lengths.json'),{'count':len(values),'minimum':values[0],'maximum':values[-1],
             'p50':values[(len(values)-1)//2],'p95':values[(len(values)-1)*95//100],'sum':sum(values)})
    context = math.ceil((max(r['prompt_tokens'] for r in length_rows)+512)/1024)*1024
    assert context <= 24576, 'Review resource configuration before model calls'
    (ROOT/'validation-cases.jsonl').write_text(''.join(canonical(c)+'\n' for c in cases['validation']))
    save(ROOT/'validation-gold.json',gold['validation'])
    save(ROOT/'examples.json',examples)
    save(ROOT/'lengths.json',length_rows)
    plan = {'kind':'development_prompt_search_not_formal', 'source_commit':'b4a757afc7c01332734fb6e4c2f08f3f7fcceef9',
            'conditions':['A','B3','B4'],'validation_views':600,'validation_sources':150,
            'example_profiles':[x[0] for x in profiles], 'example_ids':[e['case']['case_id'] for e in examples],
            'selection_rule':'profile in declared order, distinct family, minimum SHA256(case_id); no length or model outcome selection',
            'B_selection_rule':'minimum task-aggregated normalized status error over all validation cases; tie: strict errors, then fewer examples',
            'context':context,'max_new_tokens':512,'token_budget':context,'sampling':'greedy',
            'heldout_files_read':False,'formal_fewshot_choice_frozen':False,
            'example_label_origin':'programmatic_encoded_specifications_only',
            'file_sha256':{name:sha(ROOT/name) for name in ['validation-cases.jsonl','validation-gold.json','examples.json','lengths.json','driver.py']},
            'pair_files_sha256':{s:sha(DATA/(s+'.jsonl')) for s in pairs},
            'lengths':{name:read(ROOT/(name+'-lengths.json')) for name in ['A','B3','B4']}}
    save(ROOT/'plan.json',plan)
    save(ROOT/'status.json',{'phase':'preparation','status':'completed','pid':os.getpid()})
    print(json.dumps(plan,indent=2),flush=True)

def infer():
    from intentlab.formal_data import read_jsonl
    from intentlab.formal_inference import run_diagnostics
    from intentlab.model_backend import LocalBackend
    plan = read(ROOT/'plan.json')
    # This process does not open validation gold or SFT completions.
    for name in ['validation-cases.jsonl','examples.json','driver.py']:
        assert sha(ROOT/name) == plan['file_sha256'][name]
    assert sha(Path(__file__)) == plan['file_sha256']['driver.py']
    assert not (ROOT/'inference-status.json').exists()
    cases = read_jsonl(ROOT/'validation-cases.jsonl')
    examples = read(ROOT/'examples.json')
    started=time.perf_counter()
    save(ROOT/'inference-status.json',{'status':'running','pid':os.getpid(),'plan_hash':digest(plan),'started_unix':time.time()})
    backend = None
    try:
        backend = LocalBackend(MODEL, device='cuda',max_new_tokens=512,token_budget=plan['token_budget'],context_limit=plan['context'])
        for condition,count in [('A',0),('B3',3),('B4',4)]:
            run_diagnostics(cases,backend,ROOT/condition,examples[:count],model_identity={'official_revision':'c202236235762e1c871ad0ccb60c8ee5ba337b9a','precision':'bf16','plan_hash':digest(plan)})
            print(json.dumps({'condition':condition,'status':'completed','seconds':time.perf_counter()-started}),flush=True)
        save(ROOT/'inference-status.json',{'status':'completed','pid':os.getpid(),'seconds':time.perf_counter()-started,'heldout_read':False})
    except BaseException as exc:
        save(ROOT/'inference-status.json',{'status':'failed','pid':os.getpid(),'error_type':type(exc).__name__,'error':str(exc),'seconds':time.perf_counter()-started})
        raise
    finally:
        if backend is not None:
            backend.close()

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['prepare','infer'])
    args=parser.parse_args()
    {'prepare':prepare,'infer':infer}[args.phase]()
