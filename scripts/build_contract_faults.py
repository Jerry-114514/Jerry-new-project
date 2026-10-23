"""Build private development fault candidates without overwriting old batches."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.contract_fault_audit import audit_faults
from intentlab.contract_perturbations import perturbations
from intentlab.core import digest
from intentlab.execution_data import load_execution_tasks, load_references
from intentlab.formal_data import read_jsonl, validate_cases, write_jsonl
from intentlab.programmatic_labels import export_programmatic
from intentlab.report import save_json


def build(tasks_path, refs_path, base_path, out):
    if out.exists():
        raise FileExistsError('Preserve prior batch; choose a new output directory')
    tasks = load_execution_tasks(tasks_path)
    refs = load_references(refs_path, tasks)
    base = read_jsonl(base_path)
    if any(c['split'] not in ('train', 'validation') for c in base):
        raise ValueError('Development base must not include test/OOD')
    cases, expectations = perturbations(tasks, refs)
    validate_cases(base + cases)
    if len({digest(c['public']) for c in base + cases}) != len(base + cases):
        raise ValueError('Repeated public views need explicit dedup before export')
    report = audit_faults(cases, expectations, tasks, refs)
    out.mkdir(parents=True, exist_ok=False)
    write_jsonl(out / 'fault-cases.jsonl', cases)
    write_jsonl(out / 'fault-expectations.jsonl', expectations)
    write_jsonl(out / 'expanded-cases.jsonl', base + cases)
    save_json(out / 'fault-audit.json', report)
    exported = export_programmatic(base + cases, tasks, refs, out / 'export')
    labels = read_jsonl(out / 'export/programmatic-labels.jsonl')
    counts = defaultdict(Counter)
    for row in labels:
        for finding in row['findings']:
            counts[finding['id']][finding['status']] += 1
    summary = {'scope': 'expanded_development_fault_candidate_pool', 'base_views': len(base),
        'new_fault_views': len(cases), 'total_candidate_views': len(base) + len(cases),
        'source_contracts': len(tasks), 'new_source_contracts': 0,
        'new_source_tasks': 0, 'status_counts': dict(counts),
        'base_prefix_hash': digest((base + cases)[:len(base)]),
        'base_cases_hash': digest(base), 'export_labels_hash': exported['labels_hash'],
        'formal_training': False, 'human_evaluation_claim': False,
        'final_training_view_selection_frozen': False,
        'warning': 'Candidate pool only. Extra faults add views, not independent tasks. No new templates, test/OOD, formal view selection or budget approval.'}
    save_json(out / 'summary.json', summary)
    save_json(out / 'input-sha256.json', {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in
        (('tasks', tasks_path), ('references', refs_path), ('base_cases', base_path))})
    print(json.dumps(summary, indent=2))
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('tasks', 'references', 'base-cases', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    build(args.tasks, args.references, args.base_cases, args.out)
