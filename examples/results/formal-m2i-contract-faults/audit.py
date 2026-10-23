"""Rebuild private fault cases and verify state/declared-mutation evidence."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO))
from intentlab.contract_fault_audit import audit_faults
from intentlab.contract_perturbations import perturbations
from intentlab.core import digest
from intentlab.formal_data import read_jsonl
from intentlab.programmatic_labels import generate_labels


def audit(private=None, original=None):
    for name, wanted in json.loads((ROOT / 'checksums.json').read_text()).items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == wanted, name
    summary = json.loads((ROOT / 'summary.json').read_text())
    fault = json.loads((ROOT / 'fault-audit.json').read_text())
    manifest = json.loads((ROOT / 'export-manifest.json').read_text())
    assert summary['base_views'] == 2400 and summary['new_fault_views'] == fault['cases'] == 7200
    assert summary['total_candidate_views'] == 9600 and summary['new_source_tasks'] == 0
    assert summary['source_contracts'] == 600 and summary['base_prefix_hash'] == summary['base_cases_hash']
    assert summary['status_counts']['R_ORDER']['violated'] == 1800
    assert fault['scenario_assertion_disagreements'] == 0 and fault['requirements_checked'] == 28800
    assert len(fault['scenarios']) == 12 and set(fault['scenarios'].values()) == {600}
    assert fault['mutants_detected'] == fault['mutants_total'] == 6
    assert not fault['formal_proof'] and not summary['formal_training']
    assert not summary['final_training_view_selection_frozen'] and not summary['human_evaluation_claim']
    assert manifest['labels_hash'] == summary['export_labels_hash']
    if (private is None) != (original is None):
        raise ValueError('Supply rebuilt private batch and original adapted batch together')
    if private is not None:
        for name, wanted in json.loads((ROOT / 'private-file-sha256.json').read_text()).items():
            assert hashlib.sha256((private / name).read_bytes()).hexdigest() == wanted, name
        tasks = read_jsonl(original / 'tasks.jsonl')
        refs = {r['task_id']: r for r in read_jsonl(original / 'candidate-references.jsonl')}
        base = read_jsonl(original / 'cases.jsonl')
        cases, expectations = perturbations(tasks, refs)
        assert cases == read_jsonl(private / 'fault-cases.jsonl')
        assert expectations == read_jsonl(private / 'fault-expectations.jsonl')
        assert base + cases == read_jsonl(private / 'expanded-cases.jsonl')
        assert digest(base) == summary['base_cases_hash']
        assert audit_faults(cases, expectations, tasks, refs) == fault
        labels = generate_labels(base + cases, tasks, refs)
        assert labels == read_jsonl(private / 'export/programmatic-labels.jsonl')
        assert digest(labels) == manifest['labels_hash']
        for name, wanted in manifest['files_sha256'].items():
            assert hashlib.sha256((private / 'export' / name).read_bytes()).hexdigest() == wanted
    return {'metadata_verified': True, 'private_faults_and_mutants_replayed': private is not None,
            'new_fault_views': 7200, 'new_source_tasks': 0, 'formal_ready': False}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-root', type=Path)
    parser.add_argument('--original-adapted', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.private_root, args.original_adapted), indent=2))
