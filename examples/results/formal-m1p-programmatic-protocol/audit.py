"""Verify saved v3 evidence or replay the private coordinator checks."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO))
from intentlab.core import digest
from intentlab.formal_data import read_jsonl
from intentlab.programmatic_protocol import CODE_FILES, source_record, validation_record


def audit(adapted=None, expanded=None):
    for name, wanted in json.loads((ROOT/'checksums.json').read_text()).items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == wanted, name
    record = json.loads((ROOT/'programmatic-validation.json').read_text())
    summary = json.loads((ROOT/'source-isolation-summary.json').read_text())
    comparison = json.loads((ROOT/'replay-comparison.json').read_text())
    assert record['reference_check']['tasks'] == 600
    assert record['reference_check']['operations'] == ['ascii_filter_project']
    assert record['fault_audit']['cases'] == 7200 and record['fault_audit']['mutants_detected'] == 6
    assert record['cases_hash'] == summary['cases_hash'] and summary['source_groups'] == 600
    assert summary['human_evaluation_claim'] is False and summary['semantic_independence_proven'] is False
    assert comparison['local_and_autodl_validation_equal'] and comparison['local_and_autodl_source_isolation_equal']
    assert not comparison['formal_protocol_frozen'] and not comparison['formal_training_started']
    for name in CODE_FILES:
        assert hashlib.sha256((REPO/'intentlab'/name).read_text(encoding='utf-8').encode()).hexdigest() == record['implementation_sha256'][name]
    if (adapted is None) != (expanded is None):
        raise ValueError('Supply adapted and expanded cases together')
    if adapted is not None:
        tasks = read_jsonl(adapted/'tasks.jsonl')
        references = {r['task_id']:r for r in read_jsonl(adapted/'candidate-references.jsonl')}
        cases = read_jsonl(expanded)
        assert validation_record(cases, tasks, references) == record
        assert digest(source_record(cases)) == summary['record_hash']
    return {'metadata_verified': True, 'private_v3_evidence_replayed': adapted is not None,
        'protocol_interface_version': 3, 'formal_ready': False}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adapted', type=Path)
    parser.add_argument('--expanded-cases', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.adapted, args.expanded_cases), indent=2))
