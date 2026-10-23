"""Select natural-trajectory development contracts before any actor outcomes."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from intentlab.core import digest
from intentlab.execution_data import load_execution_tasks
from intentlab.formal_data import write_jsonl
from intentlab.spec_reference import reference_files, verify_references


def prepare(tasks_path, out):
    tasks_path,out=Path(tasks_path),Path(out)
    if out.exists():
        raise FileExistsError('Preserve prior selection; choose a fresh output')
    task_bytes=tasks_path.read_bytes()
    tasks=load_execution_tasks(tasks_path)
    # Only public source contracts are read; no reference/gold file is opened.
    groups=defaultdict(list)
    for task in tasks:
        if task['split'] not in {'train','validation'}:
            continue
        blocked=any(field not in row for rows in task['inputs'].values() for row in rows for field in task['spec']['required_fields'])
        groups[(task['split'],task['family'],blocked)].append(task)
    families={family for _,family,_ in groups}
    required={(split,family,blocked) for split in ('train','validation') for family in families for blocked in (False,True)}
    if not families or set(groups)!=required:
        raise ValueError('Both present-field and blocked contracts required per development split/family')
    selected=[min(groups[key],key=lambda task:hashlib.sha256(task['id'].encode()).hexdigest()) for key in sorted(groups)]
    if len({task['source_task_id'] for task in selected})!=len(selected):
        raise ValueError('Selected source identities overlap')
    references={task['id']:{'task_id':task['id'],'files':reference_files(task)} for task in selected}
    check=verify_references(selected,references)
    if tasks_path.read_bytes()!=task_bytes:
        raise ValueError('Source contracts changed while selecting')
    out.mkdir(parents=True,exist_ok=False)
    write_jsonl(out/'tasks.jsonl',selected)
    write_jsonl(out/'references.jsonl',list(references.values()))
    plan={'kind':'natural_development_collection_plan','selection_rule':'Minimum SHA256(task_id) within split/family/blocked status; one per cell before actor outcomes.',
        'source_tasks_sha256':hashlib.sha256(task_bytes).hexdigest(),'tasks_hash':digest(selected),
        'references_hash':digest(references),'reference_check':check,
        'selected_source_tasks':len(selected),'expected_visibility_views':2*len(selected),
        'selected_ids':[task['id'] for task in selected],
        'splits':['train','validation'],'families':sorted(families),
        'collector_settings':{'policies':['none'],'max_repairs':0,'max_tool_steps':3,'actor_envelope':'extract',
            'max_new_tokens':1536,'context_limit':13312,'token_budget':24576,'analyzer_mode':'rule','hard_guard_enabled':True},
        'actor':'Official original Qwen3.5-9B; revision c202236235762e1c871ad0ccb60c8ee5ba337b9a',
        'collection_started':False,'gold_files_read':False,'heldout_passed_to_model':False,
        'formal_training_started':False,'warning':'Stratified failure-mode coverage, not representative natural-error prevalence. Source count is unchanged when adding views. Preserve interface failures and time/budget failures. No test/OOD selection or model calls.'}
    (out/'plan.json').write_text(json.dumps(plan,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:plan[k] for k in ['selected_source_tasks','expected_visibility_views','collection_started']},indent=2))
    return plan


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tasks',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    prepare(args.tasks,args.out)
