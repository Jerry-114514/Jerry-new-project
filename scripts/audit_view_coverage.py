"""Count explicit view/label predicates; do not infer coverage from source code.

Requires private case/task/label files. Outputs aggregate counts only. It does
not use model outputs, tune models, or change a frozen dataset.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from intentlab.core import canonical
from intentlab.formal_data import validate_cases


def case_predicates(c,t,g):
    """Explicit observed predicates; g maps requirement IDs to program labels."""
    o=c['public']['observation'];events=o['events'];files=o['files']
    rid={rule:key for key,rule in t['spec']['requirement_rules'].items()}
    changed=any(p not in files or canonical(files[p])!=canonical(v) for p,v in t['inputs'].items())
    found=set()
    if events is None and changed and g[rid['preserve_inputs']]=='violated':
        found.add('hidden_history_snapshot_proves_input_violation')
    if events and not changed and any(e.get('path') in t['inputs'] and e['op'] in ('write','delete') for e in events) \
            and g[rid['preserve_inputs']]=='violated':found.add('input_written_then_restored')
    if events:
        data=[i for i,e in enumerate(events) if e['op']=='write' and e.get('path')==t['output_path']]
        report=[i for i,e in enumerate(events) if e['op']=='write' and e.get('path')==t['report_path']]
        if data and report and max(data)>max(report) and g[rid['exact_outputs']]=='satisfied' and g[rid['report_counts']]=='violated':
            found.add('data_repair_leaves_stale_report')
        if len(data)>=3 and len(report)>=3:found.add('multiple_data_and_report_rewrites')
        if len(events)>=31:found.add('long_history_31_or_more_events')
    if set(files)-set(t['inputs'])-{t['output_path'],t['report_path']}:found.add('forbidden_extra_artifact_final')
    if any(v=='unknown' for v in g.values()):found.add('insufficient_evidence_unknown')
    if rid['report_counts'] in t['spec']['dependencies'].get(rid['exact_outputs'],[]):found.add('result_report_dependency')
    return found


def audit(cases,tasks,labels):
    validate_cases(cases)
    by_source={t['source_task_id']:t for t in tasks}
    truth={r['case_id']:{f['id']:f['status'] for f in r['findings']} for r in labels}
    if len(truth)!=len(labels) or set(truth)!={c['case_id'] for c in cases}:
        raise ValueError('Labels must cover exactly the audited cases')
    names=('hidden_history_snapshot_proves_input_violation','input_written_then_restored',
        'data_repair_leaves_stale_report','forbidden_extra_artifact_final',
        'insufficient_evidence_unknown','multiple_data_and_report_rewrites',
        'long_history_31_or_more_events','result_report_dependency')
    counts=Counter({k:0 for k in names})
    by_split={s:Counter({k:0 for k in names}) for s in sorted({c['split'] for c in cases})}
    for c in cases:
        found=case_predicates(c,by_source[c['source_task_id']],truth[c['case_id']])
        counts.update(found);by_split[c['split']].update(found)
    return {'kind':'explicit_view_predicate_coverage','views':len(cases),'source_contracts':len(by_source),
        'counts':dict(counts),'by_split':{s:dict(v) for s,v in by_split.items()},
        'model_outputs_read':False,'data_changed':False,
        'warning':'Counts apply only to these explicit predicates and input files. They do not measure learned-model ability, exhaustive semantic coverage or formal proof.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('cases','tasks','labels','out'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args()
    if a.out.exists():raise FileExistsError('Preserve the previous audit')
    read=lambda x:[json.loads(l) for l in x.read_text(encoding='utf-8').splitlines() if l.strip()]
    r=audit(read(a.cases),read(a.tasks),read(a.labels));a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(r,indent=2)+'\n',encoding='utf-8',newline='\n');print(json.dumps(r))
