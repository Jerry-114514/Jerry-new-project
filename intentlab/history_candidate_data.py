"""Append declared injected history views, preserving every previous case."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

from .core import digest
from .execution_data import load_execution_tasks, load_references
from .formal_data import read_jsonl, validate_cases, write_jsonl
from .history_coverage import HISTORY_PLAN, history_views, select_tasks
from .programmatic_labels import export_programmatic
from .programmatic_protocol import source_record, validation_record


def build(base, out):
    base, out = Path(base), Path(out)
    if out.exists(): raise FileExistsError('Preserve previous candidate batches')
    tasks = load_execution_tasks(base/'tasks.jsonl')
    refs = load_references(base/'references.jsonl', tasks)
    old = read_jsonl(base/'cases.jsonl')
    previous = json.loads((base/'summary.json').read_text(encoding='utf-8'))
    if digest(tasks) != previous['tasks_hash'] or digest(old) != previous['cases_hash']:
        raise ValueError('Base candidate identity changed')
    selected = select_tasks(tasks)
    added = [c for t in selected for c in history_views(t, refs[t['id']])]
    cases = old + added
    audit = validate_cases(cases)
    sources = source_record(cases)
    validation = validation_record(cases, tasks, refs)
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    def save(name, value):
        (out/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    save('preparation-status.json', {'status':'running','formal_protocol_frozen':False})
    try:
        for name in ['tasks.jsonl','references.jsonl','execution-tasks.jsonl','execution-references.jsonl',
                     'natural-cases.jsonl','natural-provenance.jsonl']:
            if (base/name).is_file(): shutil.copyfile(base/name,out/name)
        write_jsonl(out/'cases.jsonl', cases)
        write_jsonl(out/'history-cases.jsonl', added)
        exported = export_programmatic(cases, tasks, refs, out/'export')
        meta = out/'export/manifest.json'
        meta.write_text(meta.read_text(encoding='utf-8'),encoding='utf-8',newline='\n')
        original_exports = ['train.jsonl','validation.jsonl','programmatic-labels.jsonl',
            'heldout/test/cases.jsonl','heldout/test/gold.jsonl','heldout/ood/cases.jsonl','heldout/ood/gold.jsonl']
        for relative in original_exports:
            if not (out/'export'/relative).read_bytes().startswith((base/'export'/relative).read_bytes()):
                raise ValueError('History append changed or dropped a previous export row')
        save('source-isolation.json', sources)
        save('programmatic-validation.json', validation)
        summary = {'schema_version':1,'kind':'history_augmented_programmatic_natural_candidate',
            'history_plan':HISTORY_PLAN,'history_plan_hash':digest(HISTORY_PLAN),
            'tasks_hash':digest(tasks),'cases_hash':digest(cases),'labels_hash':exported['labels_hash'],
            'base_cases_hash':digest(old),'base_summary_sha256':hashlib.sha256((base/'summary.json').read_bytes()).hexdigest(),
            'views_by_split':dict(Counter(c['split'] for c in cases)),
            'source_groups_by_split':audit['source_task_groups'],
            'history_views_by_split':dict(Counter(c['split'] for c in added)),
            'trajectory_views':dict(Counter(c['source']['trajectory'] for c in cases)),
            'all_previous_export_rows_byte_identical_prefix':True,
            'new_independent_sources':0,'human_evaluation_claim':False,
            'heldout_model_outputs_read':False,'formal_candidate_selected':False,'formal_protocol_frozen':False,
            'warning':'All added repair histories are injected; natural records retain prior source/split. Source independence, near matches and distribution limits remain. Construction-side heldout references are used only for programmatic labels, not model tuning.'}
        save('summary.json', summary)
        save('data-sha256.json',{p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(out.rglob('*')) if p.is_file() and p.name not in {'data-sha256.json','preparation-status.json'}})
        save('preparation-status.json', {'status':'completed','formal_protocol_frozen':False})
        return summary
    except Exception as e:
        save('preparation-status.json',{'status':'failed','error_type':type(e).__name__,'error':str(e),'formal_protocol_frozen':False})
        raise
