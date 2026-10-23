"""Input-layout-matched, wording-heldout test candidates; never strict IID."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .core import canonical, digest
from .execution_data import validate_tasks
from .formal_data import read_jsonl, validate_cases, write_jsonl
from .procedural_data import make_task, task_views
from .programmatic_labels import export_programmatic
from .programmatic_protocol import source_record, validation_record
from .spec_reference import reference_files, verify_references


def reword(task):
    """Change the actual requirement wording, retaining encoded semantics."""
    task=deepcopy(task)
    old_output,old_report=task['output_path'],task['report_path']
    task['output_path'],task['report_path']='output/data.json','output/report.json'
    clauses={r['id']:r['quote'] for r in task['requirements']}
    result=clauses['R_RESULT'].split('. ',1)[1].replace(old_output,task['output_path']).replace(old_report,task['report_path'])
    clauses={
        'R_INPUT':'All original input paths are protected: never write to or delete them, including temporary changes that are later undone.',
        'R_ORDER':'Validate the required fields at least once. Every write or delete needs a prior successful validation. When fields are missing, a prior failed validation permits only writing the blocked report; no other write or delete is permitted.',
        'R_RESULT':'Read the original input arrays in ascending path order and concatenate them. '+result,
        'R_REPORT':f'Produce {task["report_path"]}. For valid input, use status=ok, integer input_rows equal to the original total row count, and integer output_rows equal to the actual result row count. For missing required fields, use status=blocked and integer input_rows only; do not include output_rows. Boolean counts are invalid.'}
    task['request']='Every input row must provide these fields: '+canonical(task['spec']['required_fields'])+'. '+' '.join(clauses.values())
    for requirement in task['requirements']:
        requirement['quote']=clauses[requirement['id']]
    task['template_id']='proc-matched-v1-'+task['family']+'-single-file-heldout-wording'
    task['source']['reference']+='; input-layout-matched wording-heldout candidate v1'
    return task


def build(base, plan_path, private_seed_path, out, count=200):
    base,plan_path,private_seed_path,out=map(Path,(base,plan_path,private_seed_path,out))
    if out.exists():
        raise FileExistsError('Preserve previous candidate batches; choose a new output')
    if type(count) is not int or count < 1:
        raise ValueError('Positive candidate source count required')
    plan=json.loads(plan_path.read_text(encoding='utf-8'))
    base_summary=json.loads((base/'summary.json').read_text(encoding='utf-8'))
    if digest(plan)!=base_summary['plan_hash']:
        raise ValueError('Base generator plan differs from recorded batch')
    seed=json.loads(private_seed_path.read_text(encoding='utf-8'))['seed']
    if not isinstance(seed,str) or len(seed)!=64 or any(c not in '0123456789abcdef' for c in seed):
        raise ValueError('Fresh private 256-bit hexadecimal seed required')
    commitment=hashlib.sha256(bytes.fromhex(seed)).hexdigest()
    if commitment in base_summary['seed_commitments'].values():
        raise ValueError('Matched test must not reuse any base split seed')
    old_tasks=read_jsonl(base/'tasks.jsonl')
    old_cases=read_jsonl(base/'cases.jsonl')
    if digest(old_tasks)!=base_summary['tasks_hash'] or digest(old_cases)!=base_summary['cases_hash']:
        raise ValueError('Base public task/case payload changed')
    matched_plan=deepcopy(plan)
    matched_plan['layouts']['test']=deepcopy(plan['layouts']['train'])
    new_tasks,new_cases,ledger=[],[],[]
    for index in range(count):
        family=plan['train_families'][index%len(plan['train_families'])]
        ordinal=index//len(plan['train_families'])
        raw,provenance=make_task(family,'test',ordinal,seed,matched_plan)
        task=reword(raw)
        ref={'task_id':task['id'],'files':reference_files(task)}
        new_tasks.append(task)
        new_cases.extend(task_views(task,ref,ordinal))
        ledger.append({'task_id':task['id'],'split':'test','family':family,**provenance})
    tasks=[t for t in old_tasks if t['split'] in {'train','validation'}]+new_tasks+[t for t in old_tasks if t['split']=='ood']
    cases=[c for c in old_cases if c['split'] in {'train','validation'}]+new_cases+[c for c in old_cases if c['split']=='ood']
    validate_tasks(tasks)
    validate_cases(cases)
    references={t['id']:{'task_id':t['id'],'files':reference_files(t)} for t in tasks}
    checked=verify_references(tasks,references)
    isolation=source_record(cases)
    validation=validation_record(cases,tasks,references)
    out.mkdir(parents=True,mode=0o700,exist_ok=False)
    (out/'private-seed.json').write_bytes(private_seed_path.read_bytes())
    write_jsonl(out/'tasks.jsonl',tasks)
    write_jsonl(out/'references.jsonl',list(references.values()))
    write_jsonl(out/'cases.jsonl',cases)
    write_jsonl(out/'matched-test-ledger.jsonl',ledger)
    exported=export_programmatic(cases,tasks,references,out/'export')
    # The active prompt search must remain valid for exactly the same rows.
    for split in ('train','validation'):
        if (out/'export'/f'{split}.jsonl').read_bytes()!=(base/'export'/f'{split}.jsonl').read_bytes():
            raise ValueError('Matched test construction changed development exports')
    heldout=[t for t in tasks if t['split'] in {'test','ood'}]
    write_jsonl(out/'execution-tasks.jsonl',heldout)
    write_jsonl(out/'execution-references.jsonl',[references[t['id']] for t in heldout])
    for name,value in [('programmatic-validation.json',validation),('source-isolation.json',isolation)]:
        (out/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    profile={}
    for split in ('train','validation','test','ood'):
        selected=[t for t in tasks if t['split']==split]
        profile[split]={'source_tasks':len(selected),
            'input_file_counts':dict(Counter(str(len(t['inputs'])) for t in selected)),
            'total_input_rows':dict(Counter(str(sum(map(len,t['inputs'].values()))) for t in selected)),
            'required_field_counts':dict(Counter(str(len(t['spec']['required_fields'])) for t in selected)),
            'blocked_tasks':sum(any(f not in row for rows in t['inputs'].values() for row in rows for f in t['spec']['required_fields']) for t in selected),
            'families':dict(Counter(t['family'] for t in selected))}
    summary={'kind':'input_layout_matched_wording_heldout_candidates','schema_version':1,
        'base_cases_hash':base_summary['cases_hash'],'matched_test_source_tasks':count,
        'matched_test_views':len(new_cases),'profile':profile,'seed_commitment':commitment,
        'tasks_hash':digest(tasks),'cases_hash':digest(cases),'labels_hash':exported['labels_hash'],
        'independent_reference_check':checked,'development_exports_byte_identical':True,
        'archived_structural_test_retained':True,'source_independence_proven':False,
        'strict_iid_claim':False,'test_model_calls':0,'formal_protocol_frozen':False,
        'human_evaluation_claim':False,
        'limitations':['Operation-family and generated input layout/scale match train; requirement wording is held out.',
            'Finite family counts and deterministic blocked cadence need explicit stratified reporting; no strict IID guarantee.',
            'Generator logic and fault-view policy remain shared, not independent human-authored tasks.',
            'Validation retains two-file structural shift. No new empirical power or natural trajectories are supplied.',
            'No test scores, model output inspection or test-dependent tuning. Candidate not yet selected or frozen.']}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    return summary
