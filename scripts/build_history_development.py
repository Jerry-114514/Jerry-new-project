"""Build development-only injected repair histories; no formal data switch."""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.core import digest
from intentlab.execution_data import load_execution_tasks
from intentlab.formal_data import write_jsonl
from intentlab.history_coverage import HISTORY_PLAN, history_views, select_tasks
from intentlab.programmatic_labels import export_programmatic


def build(base, out):
    if out.exists(): raise FileExistsError('Preserve previous development batches')
    tasks = [t for t in load_execution_tasks(base/'tasks.jsonl') if t['split'] in ('train','validation')]
    # Reference file is construction-side material. No heldout SFT/gold or model
    # predictions are read; only selected development references are retained.
    all_refs = [json.loads(line) for line in (base/'references.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    ids = {t['id'] for t in tasks}
    refs_list = [r for r in all_refs if r['task_id'] in ids]
    from intentlab.execution_data import validate_references
    refs = validate_references(refs_list, tasks)
    chosen = select_tasks(tasks)
    cases = [c for t in chosen for c in history_views(t, refs[t['id']])]
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    write_jsonl(out/'cases.jsonl',cases)
    exported = export_programmatic(cases,tasks,refs,out/'export')
    summary = {'kind':'injected_history_development_only','plan':HISTORY_PLAN,
               'plan_hash':digest(HISTORY_PLAN),'cases_hash':digest(cases),
               'labels_hash':exported['labels_hash'],
               'views_by_split':dict(Counter(c['split'] for c in cases)),
               'sources_by_split':dict(Counter(t['split'] for t in chosen)),
               'event_count_range':[min(len(c['public']['observation']['events']) for c in cases),max(len(c['public']['observation']['events']) for c in cases)],
               'formal_protocol_frozen':False,'model_calls':0,'human_evaluation_claim':False,
               'new_independent_sources':0,'test_views_built':False}
    (out/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();print(json.dumps(build(args.base,args.out),indent=2))
