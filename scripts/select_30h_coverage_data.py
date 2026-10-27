"""Select a fixed compute-limited dataset without opening model outputs.

Private candidate input/output only. Export the summary, never the selected
cases, gold, references, source lists, seed material or content hashes publicly.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from intentlab.core import digest
from intentlab.formal_data import read_jsonl,write_jsonl,validate_cases
from intentlab.execution_data import validate_tasks,validate_references
from intentlab.programmatic_labels import export_programmatic,generate_labels
from intentlab.spec_reference import verify_references
from audit_view_coverage import audit,case_predicates


POLICY='coverage-30h-selection-v1'
QUOTAS={
    'test':{'hidden_snapshot':32,'restored_input':32,'stale_report':32,
            'extra_artifact':32,'unknown_only':32,'compliant':32,'long_rewrites':8},
    'ood':{'hidden_snapshot':16,'restored_input':16,'stale_report':16,
           'extra_artifact':16,'unknown_only':16,'compliant':18,'long_rewrites':2}}


def rank(value):return hashlib.sha256((POLICY+'\0'+value).encode()).hexdigest()


def match_quotas(eligible,quotas):
    """Exact bipartite assignment with rerouting, not greedy source deletion."""
    if sum(quotas.values())!=len(eligible):raise ValueError('Quota sum must equal source count')
    slots=[(category,i) for category in sorted(quotas) for i in range(quotas[category])]
    taken={}
    def assign(source,seen):
        for slot in slots:
            if slot[0] not in eligible[source] or slot in seen:continue
            seen.add(slot)
            if slot not in taken or assign(taken[slot],seen):
                taken[slot]=source;return True
        return False
    for source in sorted(eligible,key=rank):
        if not assign(source,set()):raise ValueError('Coverage/family quotas have no complete source matching')
    result={source:slot[0] for slot,source in taken.items()}
    if len(result)!=len(eligible) or Counter(result.values())!=Counter(quotas):
        raise ValueError('Incomplete quota assignment')
    return result


def categories(case,features,states):
    found=set()
    for category,predicate in (
        ('hidden_snapshot','hidden_history_snapshot_proves_input_violation'),
        ('restored_input','input_written_then_restored'),
        ('stale_report','data_repair_leaves_stale_report'),
        ('extra_artifact','forbidden_extra_artifact_final')):
        if predicate in features:found.add(category)
    values=set(states.values())
    if 'unknown' in values and 'violated' not in values:found.add('unknown_only')
    if values=={'satisfied'}:
        found.add('compliant')
        if {'long_history_31_or_more_events','multiple_data_and_report_rewrites'}<=features:
            found.add('long_rewrites')
    return found


def select(tasks,cases,labels,train_count=3000):
    validate_cases(cases);validate_tasks(tasks)
    by_source={t['source_task_id']:t for t in tasks}
    truth={r['case_id']:{f['id']:f['status'] for f in r['findings']} for r in labels}
    if len(truth)!=len(labels) or set(truth)!={c['case_id'] for c in cases}:
        raise ValueError('Candidate labels must cover every case exactly once')
    options=defaultdict(lambda:defaultdict(list));features={};cats={}
    for c in cases:
        cid=c['case_id'];f=case_predicates(c,by_source[c['source_task_id']],truth[cid]);features[cid]=f
        cats[cid]=categories(c,f,truth[cid])
        for category in cats[cid]:options[c['source_task_id']][category].append(c)
    # Prefer shorter observed histories, then fixed hash; no performance input.
    def choice(rows):
        return min(rows,key=lambda c:(len(c['public']['observation']['events'] or []),rank(c['case_id'])))
    assignments={};panel=[];family_counts={}
    for split,quota in QUOTAS.items():
        families=sorted({t['family'] for t in tasks if t['split']==split})
        if any(n%len(families) for n in quota.values()):raise ValueError('Family quotas must divide exactly')
        for family in families:
            ids={t['source_task_id'] for t in tasks if (t['split'],t['family'])==(split,family)}
            wanted={k:n//len(families) for k,n in quota.items()}
            matched=match_quotas({sid:set(options[sid]) for sid in ids},wanted)
            family_counts[split+'/'+family]=dict(Counter(matched.values()))
            for sid,category in matched.items():
                c=choice(options[sid][category]);panel.append(c);assignments[c['case_id']]=category
    train=[c for c in cases if c['split']=='train'];required={}
    def keep(c):required[c['case_id']]=c
    train_sources={t['source_task_id'] for t in tasks if t['split']=='train'}
    for sid in sorted(train_sources,key=rank):
        if not options[sid]['compliant']:raise ValueError('Missing mandatory per-source compliant training view')
        keep(choice(options[sid]['compliant']))
    for c in train:
        cid=c['case_id']
        if cats[cid]&{'hidden_snapshot','stale_report','extra_artifact'} or \
                'long_history_31_or_more_events' in features[cid] or \
                (c['source']['trajectory']=='natural' and 'violated' in truth[cid].values()):keep(c)
    for family in sorted({c['family'] for c in train}):
        for category in ('unknown_only','restored_input'):
            rows=[c for c in train if c['family']==family and category in cats[c['case_id']]]
            if not rows:raise ValueError('Mandatory training category missing in a family')
            keep(choice(rows))
    mandatory=len(required)
    if mandatory>train_count:raise ValueError('Mandatory coverage exceeds training budget; do not silently drop cases')
    def fill(rows):
        pools=defaultdict(list)
        for c in sorted(rows,key=lambda c:rank(c['case_id'])):
            if c['case_id'] not in required:pools[c['family']].append(c)
        while any(pools.values()) and len(required)<train_count:
            for family in sorted(pools):
                if pools[family] and len(required)<train_count:keep(pools[family].pop(0))
    # Prefer one short restored-input view per additional source, preserving
    # natural failures and mandatory coverage before spending spare capacity.
    fill([choice(options[sid]['restored_input']) for sid in sorted(train_sources,key=rank)
          if options[sid]['restored_input']])
    fill(train)
    if len(required)!=train_count:raise ValueError('Insufficient distinct training views')
    chosen=sorted(list(required.values())+[c for c in cases if c['split']=='validation']+panel,
                  key=lambda c:(c['split'],c['source_task_id'],c['case_id']))
    if len({c['source_task_id'] for c in panel})!=len(panel):raise ValueError('Repeated heldout source in panel')
    subset={c['case_id'] for c in chosen};selected_labels=[r for r in labels if r['case_id'] in subset]
    coverage=audit(chosen,tasks,selected_labels)
    if any(n==0 for counts in coverage['by_split'].values() for n in counts.values()):
        raise ValueError('At least one required predicate absent from a selected split')
    summary={'kind':'fixed_30h_compute_limited_selection','policy':POLICY,
        'views_by_split':dict(Counter(c['split'] for c in chosen)),
        'sources_by_split':{s:len({c['source_task_id'] for c in chosen if c['split']==s}) for s in ('train','validation','test','ood')},
        'mandatory_training_views':mandatory,'training_views':train_count,
        'heldout_views_per_source':1,'panel_quotas':QUOTAS,'panel_category_family_counts':family_counts,
        'selected_training_natural_views':sum(c['source']['trajectory']=='natural' for c in required.values()),
        'selected_training_natural_violated_views':sum(c['source']['trajectory']=='natural' and 'violated' in truth[c['case_id']].values() for c in required.values()),
        'model_outputs_read':False,'training_started':False,'formal_protocol_frozen':False,
        'v1_data_or_results_modified':False,'coverage':coverage,
        'warning':'Private fixed challenge panel, not full-candidate evaluation. Resource calibration, leakage audit and protocol freeze remain prerequisites.'}
    return chosen,assignments,summary


def build(candidate,out,expected_summary_sha,train_count=3000):
    candidate,out=Path(candidate),Path(out)
    if out.exists():raise FileExistsError('Use a fresh directory and preserve previous selections')
    raw=(candidate/'summary.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_summary_sha:raise ValueError('Candidate summary differs from external receipt')
    expected=json.loads(raw)
    tasks=read_jsonl(candidate/'tasks.jsonl');cases=read_jsonl(candidate/'cases.jsonl')
    references=read_jsonl(candidate/'references.jsonl');refs={r['task_id']:r for r in references}
    labels=read_jsonl(candidate/'export/programmatic-labels.jsonl')
    for name,rows in (('tasks',tasks),('cases',cases),('labels',labels)):
        if digest(rows)!=expected[name+'_hash']:raise ValueError('Candidate content binding mismatch')
    validate_references(references,tasks);verify_references(tasks,refs)
    if digest(generate_labels(cases,tasks,refs))!=expected['labels_hash']:
        raise ValueError('Candidate labels no longer agree with independent saved references')
    chosen,assignment,summary=select(tasks,cases,labels,train_count)
    out.mkdir(parents=True,exist_ok=False)
    write_jsonl(out/'cases.jsonl',chosen);write_jsonl(out/'tasks.jsonl',tasks);write_jsonl(out/'references.jsonl',references)
    export_programmatic(chosen,tasks,refs,out/'export')
    (out/'private-panel-assignments.json').write_text(json.dumps(assignment,indent=2)+'\n',encoding='utf-8',newline='\n')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8',newline='\n')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--candidate',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--candidate-summary-sha256',required=True)
    p.add_argument('--train-views',type=int,choices=(2500,3000),default=3000);a=p.parse_args()
    result=build(a.candidate,a.out,a.candidate_summary_sha256,a.train_views)
    print(json.dumps({k:result[k] for k in ('views_by_split','sources_by_split','mandatory_training_views','model_outputs_read','formal_protocol_frozen')}))
