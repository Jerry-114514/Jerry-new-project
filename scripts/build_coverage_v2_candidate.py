"""Prepare a prospective V2 candidate; never freeze, train, or score a model.

Preserves V1 train/validation source contracts and views. Generates genuinely
fresh heldout source contracts with new seed commitments, retaining all draws.
New cases and labels stay private. V1 formal artifacts are never modified.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import secrets
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from intentlab.core import canonical,digest
from intentlab.formal_data import validate_cases,write_jsonl
from intentlab.execution_data import validate_tasks,validate_references
from intentlab.history_coverage import select_tasks,history_views
from intentlab.matched_test_data import reword
from intentlab.procedural_data import make_task,task_views
from intentlab.programmatic_labels import generate_labels,export_programmatic
from intentlab.spec_reference import reference_files,verify_references
from postformal_evidence_support import BoundArchive
from build_missing_coverage_development import construct_missing_views


def build(path,expected_sha,out,seeds_path=None):
    out=Path(out)
    if out.exists():raise FileExistsError('Preserve all candidates; select a new directory')
    with BoundArchive(path,expected_sha) as archive:
        old_tasks=archive.rows('dataset/tasks.jsonl');old_cases=archive.rows('dataset/cases.jsonl')
        old_refs={r['task_id']:r for r in archive.rows('dataset/references.jsonl')}
        archive.verify_outer()
    dev_tasks=[t for t in old_tasks if t['split'] in ('train','validation')]
    dev_cases=[c for c in old_cases if c['split'] in ('train','validation')]
    old_ids={t['source_task_id'] for t in old_tasks}
    plan=json.loads((ROOT/'configs/procedural-data-plan.json').read_text())
    out.mkdir(parents=True,exist_ok=False)
    seeds=({s:secrets.token_hex(32) for s in ('test','ood')} if seeds_path is None
           else json.loads(Path(seeds_path).read_text()))
    if set(seeds)!={'test','ood'} or len(set(seeds.values()))!=2 or any(
            not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v) for v in seeds.values()):
        raise ValueError('Two distinct 256-bit heldout seeds required')
    (out/'private-heldout-seeds.json').write_text(json.dumps(seeds,indent=2)+'\n')
    progress={'kind':'prospective_coverage_v2_preparation','status':'building',
              'formal_protocol_frozen':False,'model_calls':0,'v1_artifacts_modified':False}
    def save():(out/'status.json').write_text(json.dumps(progress,indent=2)+'\n')
    save()
    try:
        fresh=[];base_views=[]
        for split in ('test','ood'):
            local=deepcopy(plan)
            if split=='test':local['layouts']['test']=deepcopy(plan['layouts']['train'])
            families=local['ood_families'] if split=='ood' else local['train_families']
            for index in range(local['counts'][split]):
                task,_=make_task(families[index%len(families)],split,index//len(families),seeds[split],local)
                if split=='test':task=reword(task)
                if task['source_task_id'] in old_ids:raise ValueError('Fresh candidate reused a V1 source')
                ref={'task_id':task['id'],'files':reference_files(task)}
                fresh.append(task);base_views.extend(task_views(task,ref,index))
        tasks=dev_tasks+fresh
        validate_tasks(tasks)
        refs={t['id']:(old_refs[t['id']] if t['split'] in ('train','validation') else
                       {'task_id':t['id'],'files':reference_files(t)}) for t in tasks}
        validate_references(list(refs.values()),tasks);verify_references(tasks,refs)
        new_histories=[c for t in select_tasks(fresh) for c in history_views(t,refs[t['id']])]
        extra=[];expected=[]
        for task in tasks:
            # Heldout construction is allowed ONLY for the new source population,
            # not for V1 heldout IDs; no model result is used in this builder.
            if task['split'] in ('test','ood') and task['source_task_id'] in old_ids:
                raise ValueError('Cannot amend old heldout views')
            for case,wanted,_,_ in construct_missing_views(task,refs[task['id']],'coverage-v2'):
                extra.append(case);expected.append(wanted)
        cases=dev_cases+base_views+new_histories+extra
        validate_cases(cases)
        labels=generate_labels(cases,tasks,refs)
        actual={r['case_id']:{f['id']:f['status'] for f in r['findings']} for r in labels}
        if any(actual[e['case_id']]!=e['expected_statuses'] for e in expected):
            raise ValueError('New coverage assertions differ from programmatic labels')
        if digest([c for c in cases if c['split'] in ('train','validation') and not c['case_id'].endswith(tuple(
                '-coverage-v2-'+s for s in ('hidden_snapshot_violation','forbidden_extra_artifact','data_repair_stale_report')))])!=digest(dev_cases):
            raise ValueError('V1 development views changed')
        for name,rows in [('tasks.jsonl',tasks),('cases.jsonl',cases),('references.jsonl',list(refs.values())),
                          ('new-coverage-expectations.jsonl',expected)]:write_jsonl(out/name,rows)
        exported=export_programmatic(cases,tasks,refs,out/'export')
        heldout=[t for t in tasks if t['split'] in ('test','ood')]
        write_jsonl(out/'execution-tasks.jsonl',sorted(heldout,key=lambda t:t['id']))
        write_jsonl(out/'execution-references.jsonl',[refs[t['id']] for t in sorted(heldout,key=lambda t:t['id'])])
        summary={'kind':'prospective_coverage_v2_candidate','formal_protocol_frozen':False,
            'source_counts':dict(Counter(t['split'] for t in tasks)),
            'views_by_split':dict(Counter(c['split'] for c in cases)),
            'new_coverage_by_scenario':dict(Counter(e['scenario'] for e in expected)),
            'fresh_heldout_sources':len(fresh),'v1_heldout_sources_reused':0,
            'preserved_v1_development_sources':len(dev_tasks),'preserved_v1_development_views':len(dev_cases),
            'new_history_views':len(new_histories),'labels':len(labels),
            'independent_references_checked':len(tasks),'coverage_assertion_disagreements':0,
            'heldout_seed_commitments':{s:hashlib.sha256(bytes.fromhex(v)).hexdigest() for s,v in seeds.items()},
            'tasks_hash':digest(tasks),'cases_hash':digest(cases),'labels_hash':exported['labels_hash'],
            'model_calls':0,'v1_results_replaced':False,'training_started':False,
            'warning':'Prospective candidate only; not a replacement for V1, not yet protocol-frozen or budget-approved. Shared-generator and normalized-neighbor risks still require audit.'}
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8',newline='\n')
        progress.update(status='completed',candidate_prepared=True);save()
        return summary
    except BaseException as exc:
        progress.update(status='failed',error_type=type(exc).__name__,error=str(exc));save();raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scientific-archive',type=Path,required=True);p.add_argument('--scientific-sha256',required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--heldout-seeds-file',type=Path);a=p.parse_args()
    result=build(a.scientific_archive,a.scientific_sha256,a.out,a.heldout_seeds_file)
    print(json.dumps({k:result[k] for k in ('formal_protocol_frozen','source_counts','views_by_split','fresh_heldout_sources','v1_heldout_sources_reused','model_calls')}))
