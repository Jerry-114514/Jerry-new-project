"""Combine archived natural development evidence without changing heldout data."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil

from .core import canonical, digest
from .execution import replay_execution
from .execution_data import load_execution_tasks, load_references
from .formal_data import read_jsonl, validate_cases, write_jsonl
from .programmatic_labels import export_programmatic
from .programmatic_protocol import source_record, validation_record
from .trajectory_intake import extract_views


def build(base, selection, execution, out):
    base,selection,execution,out=map(Path,(base,selection,execution,out))
    if out.exists():
        raise FileExistsError('Keep previous combined batches; choose a fresh output')
    selected=load_execution_tasks(selection/'tasks.jsonl')
    if not selected or any(t['split'] not in {'train','validation'} for t in selected):
        raise ValueError('Natural development merge refuses test/OOD tasks before raw/reference access')
    tasks=load_execution_tasks(base/'tasks.jsonl')
    refs=load_references(base/'references.jsonl',tasks)
    old_cases=read_jsonl(base/'cases.jsonl')
    base_summary=json.loads((base/'summary.json').read_text(encoding='utf-8'))
    if digest(tasks)!=base_summary['tasks_hash'] or digest(old_cases)!=base_summary['cases_hash']:
        raise ValueError('Base candidate contract/case identity changed')
    by_id={t['id']:t for t in tasks}
    if any(t['id'] not in by_id or canonical(t)!=canonical(by_id[t['id']]) for t in selected):
        raise ValueError('Natural task differs from candidate source contract')
    selected_refs=load_references(selection/'references.jsonl',selected)
    if any(canonical(selected_refs[t['id']])!=canonical(refs[t['id']]) for t in selected):
        raise ValueError('Natural static references differ from candidate references')
    manifest=json.loads((execution/'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('offline_reference_hash')!=digest(selected_refs):
        raise ValueError('Natural reference binding changed')
    raw=(execution/'runs.jsonl').read_bytes()
    records=[json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    replay=replay_execution(selected,selected_refs,records)
    natural,index=extract_views(selected,manifest,records,hashlib.sha256(raw).hexdigest())
    cases=old_cases+natural
    audit=validate_cases(cases)
    sources=source_record(cases)
    validation=validation_record(cases,tasks,refs)
    out.mkdir(parents=True,mode=0o700,exist_ok=False)
    def save(name,value):
        (out/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    save('preparation-status.json',{'status':'running','formal_protocol_frozen':False})
    try:
        for name in ('tasks.jsonl','references.jsonl','execution-tasks.jsonl','execution-references.jsonl'):
            shutil.copyfile(base/name,out/name)
        write_jsonl(out/'cases.jsonl',cases)
        write_jsonl(out/'natural-cases.jsonl',natural)
        write_jsonl(out/'natural-provenance.jsonl',index)
        exported=export_programmatic(cases,tasks,refs,out/'export')
        # Normalize newly written metadata only; historical batches stay intact.
        metadata=out/'export/manifest.json'
        metadata.write_text(metadata.read_text(encoding='utf-8'),encoding='utf-8',newline='\n')
        for split in ('test','ood'):
            for name in ('cases.jsonl','gold.jsonl'):
                relative=Path('export/heldout')/split/name
                if (out/relative).read_bytes()!=(base/relative).read_bytes():
                    raise ValueError('Natural development merge changed heldout material')
        save('programmatic-validation.json',validation)
        save('source-isolation.json',sources)
        summary={'kind':'combined_programmatic_and_natural_candidate','schema_version':1,
            'tasks_hash':digest(tasks),'cases_hash':digest(cases),'labels_hash':exported['labels_hash'],
            'views_by_split':dict(Counter(c['split'] for c in cases)),
            'source_groups_by_split':audit['source_task_groups'],
            'trajectory_views':dict(Counter(c['source']['trajectory'] for c in cases)),
            'natural_runs':len(records),'natural_views':len(natural),
            'natural_source_groups':len({c['source_task_id'] for c in natural}),
            'natural_execution_status_counts':dict(Counter(r['status'] for r in records)),
            'natural_compliant_runs':sum(r['metrics']['compliant_success'] for r in records),
            'raw_natural_sha256':hashlib.sha256(raw).hexdigest(),
            'base_cases_hash':base_summary['cases_hash'],'natural_replay':replay,
            'heldout_cases_and_gold_byte_identical':True,
            'new_independent_source_tasks':0,'human_evaluation_claim':False,
            'heldout_model_outputs_read':False,'formal_candidate_selected':False,
            'formal_protocol_frozen':False,
            'warning':'Natural views retain existing source/split; all recorded failures survive. Gold is regenerated offline from explicit contracts/static references, not copied from online judgments. No test model tuning or current protocol switch. Long-history/multi-repair coverage and remaining scientific/budget gates need separate review.'}
        save('summary.json',summary)
        save('data-sha256.json',{p.relative_to(out).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
             for p in sorted(out.rglob('*')) if p.is_file() and p.name not in {'data-sha256.json','preparation-status.json'}})
        save('preparation-status.json',{'status':'completed','formal_protocol_frozen':False})
        return summary
    except Exception as exc:
        save('preparation-status.json',{'status':'failed','error_type':type(exc).__name__,'error':str(exc),
            'formal_protocol_frozen':False})
        raise
