"""Locked, limited diagnostic follow-up; full M1-M8 acceptance stays separate."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys
import time

CONDITIONS=['A','B','C']+[f'{k}-seed-{s}' for k in ('D','E') for s in (0,1,2)]
COMPARISONS=['RQ1/test','RQ1/ood','CE/test','CE/ood']


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def load_lock(path):
    p=json.loads(Path(path).read_text());sys.path.insert(0,p['core_source'])
    from intentlab.core import digest
    if p['lock_hash']!=digest({k:v for k,v in p.items() if k!='lock_hash'}):raise ValueError('Protocol changed')
    if p['scope']!='approved_compute_limited_30h_followup' or p['conditions']!=CONDITIONS:
        raise ValueError('Wrong follow-up scope or condition registry')
    if p['statistics']['comparison_registry']!=COMPARISONS:raise ValueError('Comparison registry differs from implementation')
    if subprocess.check_output(['git','-C',p['core_source'],'rev-parse','HEAD'],text=True).strip()!=p['core_commit'] \
            or subprocess.check_output(['git','-C',p['core_source'],'status','--porcelain']):
        raise ValueError('Frozen core source changed')
    for name,expected in p['tool_files_sha256'].items():
        if sha(Path(p['tools_root'])/name)!=expected:raise ValueError('Frozen orchestration implementation changed')
    return p


def verify_files(p,names):
    for name in names:
        if sha(Path(p['root'])/name)!=p['files_sha256'][name]:raise ValueError('Frozen input changed: '+name)


def save(path,value):
    Path(path).write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')


def verify_models(p):
    from intentlab.core import digest
    root=Path(p['root']);b=json.loads((root/'model-binding.json').read_text())
    if b['protocol_hash']!=p['lock_hash'] or b['binding_hash']!=digest({k:v for k,v in b.items() if k!='binding_hash'}):
        raise ValueError('Model binding differs from training protocol')
    if set(b['jobs'])!=set(CONDITIONS[3:]):raise ValueError('Six selected model bindings required')
    for condition,row in b['jobs'].items():
        if row['config']!=p['jobs'][condition]['config'] or row['base_identity']!=p['base_identity']:
            raise ValueError('Unexpected training configuration/base')
        for name,expected in row['selected_files_sha256'].items():
            if sha(Path(p['jobs'][condition]['out'])/name)!=expected:raise ValueError('Selected export changed')
    for seed in (0,1,2):
        if b['jobs'][f'D-seed-{seed}']['initial_trainable_sha256']!=b['jobs'][f'E-seed-{seed}']['initial_trainable_sha256']:
            raise ValueError('Paired seeds differ in initialization')
    return b


def public_inputs(p):
    from intentlab.formal_data import read_jsonl,validate_cases
    names=['public/cases.jsonl','public/tasks.jsonl','public/examples.json']
    verify_files(p,names);root=Path(p['root'])
    cases=read_jsonl(root/names[0]);tasks=read_jsonl(root/names[1]);examples=json.loads((root/names[2]).read_text())
    validate_cases(cases)
    if Counter(c['split'] for c in cases)!=Counter(test=200,ood=100) or len({c['source_task_id'] for c in cases})!=300:
        raise ValueError('Exactly 300 unique heldout sources with the frozen split counts required')
    from intentlab.formal_inference import reject_example_overlap
    reject_example_overlap(cases,examples)
    return cases,tasks,examples


def backend_protocol(p):
    return {'scope':'formal','models':{'analyzer_base':{'path':p['base_model']}},
            'spec':{'training':{'device':'cuda'},'budgets':p['budgets']}}


def generate(p):
    from intentlab.core import digest
    from intentlab.formal_inference import run_diagnostics
    from intentlab.diagnostic_protocol import backend_for,rule_predictions,seal_files
    from intentlab.execution_protocol import contract_identity
    root=Path(p['root']);binding=verify_models(p);cases,tasks,examples=public_inputs(p)
    with (root/'generation.claim.json').open('x') as f:json.dump({'protocol_hash':p['lock_hash'],'time':time.time()},f)
    out=root/'predictions';out.mkdir(exist_ok=False)
    manifest={'status':'running','conditions':CONDITIONS,'protocol_hash':p['lock_hash'],
              'model_binding_hash':binding['binding_hash'],'gold_loaded':False}
    save(out/'manifest.json',manifest)
    indexed={contract_identity(t,{'request':t['request'],'inputs':t['inputs'],'requirements':t['requirements'],'execution_spec':t['spec']}):t for t in tasks}
    try:
        for condition in CONDITIONS:
            manifest['active_condition']=condition;save(out/'manifest.json',manifest)
            if condition=='C':rule_predictions(cases,indexed,out/condition);continue
            path=p['base_model'] if condition in ('A','B') else str(Path(p['jobs'][condition]['out'])/'model')
            backend=backend_for(backend_protocol(p),path)
            try:run_diagnostics(cases,backend,out/condition,examples if condition=='B' else (),
                                {'limited_condition':condition,'protocol_hash':p['lock_hash']})
            finally:backend.close()
        verify_models(p);public_inputs(p)
        manifest.update(status='sealed',files_sha256=seal_files(out))
        manifest['seal_hash']=digest(manifest);save(out/'manifest.json',manifest)
    except BaseException as exc:
        manifest.update(status='failed',error_type=type(exc).__name__,error=str(exc));save(out/'manifest.json',manifest);raise


def verify_predictions(p):
    from intentlab.core import digest
    from intentlab.diagnostic_protocol import seal_files
    from intentlab.formal_data import read_jsonl
    root=Path(p['root']);m=json.loads((root/'predictions/manifest.json').read_text());b=verify_models(p)
    if m['status']!='sealed' or m['conditions']!=CONDITIONS or m['gold_loaded'] is not False \
            or m['protocol_hash']!=p['lock_hash'] or m['model_binding_hash']!=b['binding_hash'] \
            or m['seal_hash']!=digest({k:v for k,v in m.items() if k!='seal_hash'}) \
            or seal_files(root/'predictions')!=m['files_sha256']:raise ValueError('Predictions not completely sealed')
    cases,tasks,examples=public_inputs(p);ids={c['case_id'] for c in cases}
    for condition in CONDITIONS:
        rows=read_jsonl(root/'predictions'/condition/'predictions.jsonl')
        if len(rows)!=300 or {r['case_id'] for r in rows}!=ids:raise ValueError('Incomplete/duplicated prediction population')
    return cases,tasks


def reveal(p):
    from intentlab.core import canonical
    from intentlab.formal_data import read_jsonl,validate_findings
    from intentlab.formal_eval import score_predictions
    from intentlab.diagnostic_protocol import heldout_loss
    cases,tasks=verify_predictions(p);root=Path(p['root'])
    with (root/'reveal.claim.json').open('x') as f:json.dump({'protocol_hash':p['lock_hash'],'time':time.time()},f)
    # This is the first decoded heldout gold access by an evaluation worker.
    verify_files(p,['sealed/gold.jsonl','sealed/references.jsonl'])
    gold_rows=read_jsonl(root/'sealed/gold.jsonl');by_case={c['case_id']:c for c in cases}
    if len(gold_rows)!=len(cases) or {r['case_id'] for r in gold_rows}!=set(by_case):raise ValueError('Gold population differs')
    gold={r['case_id']:validate_findings(r['findings'],by_case[r['case_id']]['public']) for r in gold_rows}
    out=root/'scores';out.mkdir(exist_ok=False)
    receipt={'status':'running','protocol_hash':p['lock_hash'],'gold_opened_after_prediction_seal':True};save(out/'manifest.json',receipt)
    try:
        scores={}
        for condition in CONDITIONS:
            pred=read_jsonl(root/'predictions'/condition/'predictions.jsonl');scores[condition]={}
            for split in ('test','ood'):
                subset=[c for c in cases if c['split']==split];ids={c['case_id'] for c in subset}
                g={c['case_id']:[gold[c['case_id']][r['id']] for r in c['public']['requirements']] for c in subset}
                scores[condition][split]=score_predictions(subset,g,[r for r in pred if r['case_id'] in ids])
        save(out/'scores.json',scores)
        for condition in CONDITIONS[3:]:
            receipt['active_loss_condition']=condition;save(out/'manifest.json',receipt)
            heldout_loss(backend_protocol(p),str(Path(p['jobs'][condition]['out'])/'model'),cases,gold,out/(condition+'-loss.jsonl'))
        verify_predictions(p);receipt.update(status='completed');save(out/'manifest.json',receipt)
    except BaseException as exc:
        receipt.update(status='failed',error_type=type(exc).__name__,error=str(exc));save(out/'manifest.json',receipt);raise


def analyze(cases,scores,losses,settings):
    from intentlab.research_statistics import paired_cluster_statistics,holm_adjust
    by_source={c['source_task_id']:c for c in cases}
    if len(by_source)!=len(cases):raise ValueError('Limited panel requires one view per source')
    loss_index={}
    expected={c['case_id'] for c in cases}
    by_case={c['case_id']:c for c in cases}
    if len(by_case)!=len(cases) or set(losses)!=set(CONDITIONS[3:]):raise ValueError('Unexpected case/loss registry')
    for condition in CONDITIONS:
        for split in ('test','ood'):
            ids={k for k,c in by_source.items() if c['split']==split}
            values=scores[condition][split]['per_task_error_rate']
            if set(values)!=ids or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1 for v in values.values()):
                raise ValueError('Diagnostic source population differs between conditions')
    population=None
    for condition in CONDITIONS[3:]:
        rows=losses[condition];idx={r['source_task_id']:r for r in rows}
        if len(idx)!=len(rows) or {r['case_id'] for r in rows}!=expected \
                or set(idx)!=set(by_source) or any(type(r['target_tokens']) is not int or r['target_tokens']<1 \
                or type(r['loss_sum']) not in (int,float) or not math.isfinite(r['loss_sum']) or r['loss_sum']<0 for r in rows):raise ValueError('Loss population invalid')
        if any(r['source_task_id']!=by_case[r['case_id']]['source_task_id'] or r['split']!=by_case[r['case_id']]['split'] for r in rows):
            raise ValueError('Loss case/source/split binding differs')
        tokens={k:r['target_tokens'] for k,r in idx.items()}
        if population is not None and tokens!=population:raise ValueError('Target token denominators differ between conditions')
        population=tokens;loss_index[condition]=idx
    results={}
    for split in ('test','ood'):
        ids=sorted(k for k,c in by_source.items() if c['split']==split)
        strata={k:by_source[k]['family'] for k in ids}
        kwargs=dict(seed=settings['bootstrap_seed'],bootstrap_samples=settings['bootstrap_samples'],
                    permutation_samples=settings['permutation_samples'],strata=strata)
        left={k:[scores['B'][split]['per_task_error_rate'][k]]*3 for k in ids}
        right={k:[scores[f'D-seed-{s}'][split]['per_task_error_rate'][k] for s in (0,1,2)] for k in ids}
        results['RQ1/'+split]=paired_cluster_statistics(left,right,**kwargs)
        left={k:[loss_index[f'D-seed-{s}'][k]['loss_sum'] for s in (0,1,2)] for k in ids}
        right={k:[loss_index[f'E-seed-{s}'][k]['loss_sum'] for s in (0,1,2)] for k in ids}
        results['CE/'+split]=paired_cluster_statistics(left,right,weights={k:population[k] for k in ids},**kwargs)
    adjusted=holm_adjust({k:results[k]['hypothesis_test']['p_value'] for k in COMPARISONS if k!='RQ1/test'})
    for key,row in results.items():
        row['primary']=key=='RQ1/test';row['holm_p_value']=None if row['primary'] else adjusted[key]
    return {'comparisons':results,'primary':'RQ1/test','secondary_family':list(adjusted),
            'warning':'Task-conditional fixed-seed inference; challenge distribution, shared-generator/neighbor risks and additional category quotas remain.'}


def project(value):
    if isinstance(value,dict):return {k:project(v) for k,v in value.items() if k not in {'records','per_task_error_rate','per_source_task','case_id','source_task_id'}}
    if isinstance(value,list):return [project(v) for v in value]
    return value


def stats(p):
    from intentlab.formal_data import read_jsonl
    from intentlab.formal_eval import score_predictions
    from score_evidence_support import score_evidence_support
    cases,tasks=verify_predictions(p);root=Path(p['root'])
    if json.loads((root/'scores/manifest.json').read_text())['status']!='completed':raise ValueError('Complete loss stage required')
    scores=json.loads((root/'scores/scores.json').read_text())
    losses={c:read_jsonl(root/'scores'/(c+'-loss.jsonl')) for c in CONDITIONS[3:]}
    result=analyze(cases,scores,losses,p['statistics']);out=root/'analysis';out.mkdir(exist_ok=False)
    save(out/'statistics.json',result)
    verify_files(p,['sealed/gold.jsonl','sealed/references.jsonl','sealed/panel-assignment.json'])
    raw_gold=read_jsonl(root/'sealed/gold.jsonl');gold={r['case_id']:r['findings'] for r in raw_gold}
    assignments=json.loads((root/'sealed/panel-assignment.json').read_text())
    if set(assignments)!={c['case_id'] for c in cases}:raise ValueError('Panel scenario metadata differs')
    refs=read_jsonl(root/'sealed/references.jsonl');support={};scenario_scores={}
    for condition in CONDITIONS:
        raw=read_jsonl(root/'predictions'/condition/'predictions.jsonl')
        assessment=score_evidence_support(cases,tasks,refs,gold,raw)
        save(out/(condition+'-evidence.json'),assessment);support[condition]=project(assessment['summaries'])
        scenario_scores[condition]={}
        for split in ('test','ood'):
            if Counter(assignments[c['case_id']] for c in cases if c['split']==split)!=Counter(p['panel_quotas'][split]):
                raise ValueError('Frozen scenario quotas changed')
            scenario_scores[condition][split]={}
            for scenario in p['panel_quotas'][split]:
                subset=[c for c in cases if c['split']==split and assignments[c['case_id']]==scenario];ids={c['case_id'] for c in subset}
                scenario_scores[condition][split][scenario]=project(score_predictions(subset,{k:gold[k] for k in ids},[r for r in raw if r['case_id'] in ids]))
    summary={'scope':p['scope'],'protocol_version':p['version'],'source_tasks':dict(Counter(c['split'] for c in cases)),
             'diagnostics':project(scores),'scenario_diagnostics':scenario_scores,'evidence_descriptive':support,'statistics':result,
             'full_M1_M8_goal_complete':False,'full_candidate_evaluation_complete':False,
             'new_closed_loop_or_control_results':False,'gold_is_programmatic':True,'human_evaluation':False}
    save(out/'aggregate-results.json',summary)
    save(out/'manifest.json',{'status':'completed','protocol_hash':p['lock_hash'],'new_model_calls':0})


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('generate','reveal','stats'))
    parser.add_argument('--protocol',type=Path,required=True);parser.add_argument('--ack',type=Path,required=True)
    parser.add_argument('--owned-module',required=True);a=parser.parse_args()
    p=load_lock(a.protocol)
    from intentlab.matrix_worker import wait_for_ack
    wait_for_ack(a.ack)
    {'generate':generate,'reveal':reveal,'stats':stats}[a.action](p)
