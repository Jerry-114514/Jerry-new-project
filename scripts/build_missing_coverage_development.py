"""Prepare missing-case DEVELOPMENT views; never amend frozen formal data.

Labels use original encoded-spec logic and independent saved references. This
does not retrain models or retroactively complete formal coverage requirements.
"""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from intentlab.core import canonical, initial_state
from intentlab.execution_analysis import analyze_execution
from intentlab.execution_data import validate_references
from intentlab.programmatic_labels import generate_labels
from intentlab.spec_reference import verify_references
from postformal_evidence_support import BoundArchive


def missing_views(task, reference):
    if task['split'] not in ('train','validation'):
        raise ValueError('Missing-coverage development builder rejects test/OOD sources')
    return construct_missing_views(task,reference,'postformal-dev')


def construct_missing_views(task, reference, suffix):
    """Construct views; fresh-candidate callers must enforce prospective sources.

    The development entry above remains split-restricted. This primitive does
    not grant permission to alter an existing frozen dataset or evaluate it.
    """
    missing=any(k not in row for rows in task['inputs'].values() for row in rows for k in task['spec']['required_fields'])
    report,output=task['report_path'],task['output_path']
    good=[{'op':'validate','ok':not missing}]+[
        {'op':'write','path':p,'value':deepcopy(v)} for p,v in reference['files'].items()]
    protected=next(iter(task['inputs']))
    changed=deepcopy(task['inputs'][protected])
    if not changed:changed=[{}]
    elif not changed[0]:changed.append(deepcopy(changed[0]))
    else:
        field='rid' if 'rid' in changed[0] else sorted(changed[0])[0]
        value=changed[0][field]
        offset=1+int(hashlib.sha256(task['id'].encode()).hexdigest()[:2],16)%9
        if isinstance(value,str):
            if not value:replacement=str(offset)
            elif value[0].isdigit() and value[0].isascii():replacement=str((int(value[0])+offset)%10)+value[1:]
            elif value[0] in 'abcdef':replacement='abcdef0123456789'[('abcdef0123456789'.index(value[0])+offset)%16]+value[1:]
            else:replacement=chr(ord(value[0])+1)+value[1:]
        elif type(value) is bool:replacement=not value
        elif type(value) in (int,float):replacement=value+offset
        elif value is None:replacement=0
        elif isinstance(value,list):replacement=value+[None]
        else:replacement={**value,'value':None}
        changed[0][field]=replacement
    names=('archive.json','summary.json','data.copy.json','result.json','items.json','status.json')
    extra='output/'+names[int(hashlib.sha256(task['id'].encode()).hexdigest()[:2],16)%len(names)]
    while extra in task['inputs'] or extra in (report,output):extra+='.extra'
    S,V,U='satisfied','violated','unknown'
    specs=[('hidden_snapshot_violation',good+[{'op':'write','path':protected,'value':changed}],False,(V,U,S,S)),
           ('forbidden_extra_artifact',good+[{'op':'write','path':extra,'value':[]}],True,(S,V if missing else S,V,S))]
    if not missing:
        correct=deepcopy(reference['files'][output])
        first=deepcopy(next(iter(task['inputs'].values()))[0])
        operation=task['spec']['operation']
        if correct:extra_row=deepcopy(correct[0])
        elif operation['name']=='ascii_filter_project':extra_row={k:first[k] for k in operation['fields']}
        elif operation['name']=='conditional_group_sum':extra_row={'group':first[operation['group_field']],'total':first[operation['value_field']]}
        else:extra_row=first
        wrong=correct+[extra_row]
        truthful={'status':'ok','input_rows':sum(map(len,task['inputs'].values())),'output_rows':len(wrong)}
        actions=[{'op':'validate','ok':True},{'op':'write','path':output,'value':wrong},
                 {'op':'write','path':report,'value':truthful},
                 {'op':'write','path':output,'value':deepcopy(reference['files'][output])}]
        specs.append(('data_repair_stale_report',actions,True,(S,S,S,V)))
    result=[]
    rules=('preserve_inputs','validate_before_write','exact_outputs','report_counts')
    for name,actions,visible,expected in specs:
        state=initial_state(task);state.apply(actions)
        case={'case_id':task['id']+'-'+suffix+'-'+name,
            **{k:deepcopy(task[k]) for k in ('source_task_id','split','family','template_id')},
            'source':{**deepcopy(task['source']),'trajectory':'injected'},
            'public':{'request':task['request'],'inputs':deepcopy(task['inputs']),
                'requirements':deepcopy(task['requirements']),'execution_spec':deepcopy(task['spec']),
                'observation':{'files':deepcopy(state.files),'events':deepcopy(state.events) if visible else None}}}
        by_rule=dict(zip(rules,expected))
        wanted={r['id']:by_rule[task['spec']['requirement_rules'][r['id']]] for r in task['requirements']}
        result.append((case,{'case_id':case['case_id'],'scenario':name,'expected_statuses':wanted},state,visible))
    return result


def build(archive_path, expected_sha, out):
    out=Path(out)
    if out.exists():raise FileExistsError('Use a fresh development output directory')
    with BoundArchive(archive_path,expected_sha) as a:
        # Coordinator filters the mixed source catalog. No heldout source is
        # used for case construction; no model score/output archive is opened.
        candidates=[t for t in a.rows('dataset/tasks.jsonl') if t['split'] in ('train','validation')]
        ids={t['id'] for t in candidates}
        references={r['task_id']:r for r in a.rows('dataset/references.jsonl') if r['task_id'] in ids}
        a.verify_outer()
    strata=defaultdict(list)
    for t in sorted(candidates,key=lambda t:t['id']):
        blocked=any(k not in r for rows in t['inputs'].values() for r in rows for k in t['spec']['required_fields'])
        strata[(t['split'],t['family'],blocked)].append(t)
    selected=[rows[0] for _,rows in sorted(strata.items())]
    selected_refs={t['id']:references[t['id']] for t in selected}
    validate_references(list(selected_refs.values()),selected);verify_references(selected,selected_refs)
    bundles=[(t,item) for t in selected for item in missing_views(t,selected_refs[t['id']])]
    cases=[item[0] for _,item in bundles];expectations=[item[1] for _,item in bundles]
    labels=generate_labels(cases,selected,selected_refs)
    label_map={r['case_id']:{f['id']:f['status'] for f in r['findings']} for r in labels}
    for task,(case,wanted,state,visible) in bundles:
        if label_map[case['case_id']]!=wanted['expected_statuses']:
            raise ValueError('Constructed scenario differs from its independent assertion')
        online={f['id']:f['status'] for f in analyze_execution(task,state,events_visible=visible)}
        if online!=wanted['expected_statuses']:raise ValueError('Online rule analyzer differs from scenario assertion')
    report={'kind':'postformal_missing_coverage_development_package','scope':'development_only_after_formal_evaluation',
        'selected_existing_development_sources':len(selected),'new_independent_sources':0,'views':len(cases),
        'scenarios':dict(Counter(e['scenario'] for e in expectations)),
        'split_views':dict(Counter(c['split'] for c in cases)),'heldout_sources_selected':0,
        'mixed_source_catalog_filtered_by_split':True,'model_scores_or_outputs_opened':False,
        'programmatic_and_rule_scenario_disagreements':0,'formal_dataset_modified':False,
        'formal_models_trained_on_these_new_views':False,'formal_coverage_retroactively_completed':False,
        'warning':'Development regression data only. New formal training/testing requires a separately frozen prospective protocol and fresh heldout sources.'}
    out.mkdir(parents=True,exist_ok=False)
    for name,rows in [('cases.jsonl',cases),('labels.jsonl',labels),('expectations.jsonl',expectations),
                      ('tasks.jsonl',selected),('references.jsonl',list(selected_refs.values()))]:
        (out/name).write_text(''.join(canonical(r)+'\n' for r in rows),encoding='utf-8',newline='\n')
    (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--scientific-archive',type=Path,required=True);p.add_argument('--scientific-sha256',required=True)
    p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    print(json.dumps(build(a.scientific_archive,a.scientific_sha256,a.out)))
