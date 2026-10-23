"""Verify metadata or replay private programmatic training-label export."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO))
from intentlab.core import canonical, digest
from intentlab.formal_data import read_jsonl, formal_prompt
from intentlab.programmatic_labels import generate_labels


def audit(private=None, export=None):
    for name, wanted in json.loads((ROOT / 'checksums.json').read_text()).items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == wanted, name
    manifest = json.loads((ROOT / 'export-manifest.json').read_text())
    summary = json.loads((ROOT / 'summary.json').read_text())
    assert manifest['kind'] == 'programmatic_explicit_spec_diagnostics'
    assert not manifest['human_evaluation_claim'] and manifest['human_reviews_completed'] == 0
    assert not manifest['protocol_frozen'] and not summary['formal_training_started']
    assert summary['views'] == 2400 and summary['label_items'] == 9600
    assert summary['status_counts']['R_ORDER'].get('violated', 0) == 0
    assert not summary['formal_protocol_migrated']
    generator = (REPO / 'intentlab/programmatic_labels.py').read_bytes().replace(b'\r\n', b'\n')
    assert hashlib.sha256(generator).hexdigest() == manifest['generator_sha256']
    if (private is None) != (export is None):
        raise ValueError('Supply private source and export together')
    if private is not None:
        for name, wanted in json.loads((ROOT / 'input-sha256.json').read_text()).items():
            assert hashlib.sha256((private / name).read_bytes()).hexdigest() == wanted
        cases, tasks = read_jsonl(private / 'cases.jsonl'), read_jsonl(private / 'tasks.jsonl')
        refs = {r['task_id']: r for r in read_jsonl(private / 'candidate-references.jsonl')}
        labels = generate_labels(cases, tasks, refs)
        assert labels == read_jsonl(export / 'programmatic-labels.jsonl')
        assert digest(cases) == manifest['cases_hash'] and digest(tasks) == manifest['tasks_hash']
        assert digest(refs) == manifest['references_hash'] and digest(labels) == manifest['labels_hash']
        for name, wanted in manifest['files_sha256'].items():
            assert hashlib.sha256((export / name).read_bytes()).hexdigest() == wanted
        sft = read_jsonl(export / 'train.jsonl')
        assert len(sft) == len(cases) == 2400
        counts = defaultdict(Counter)
        for case, label, row in zip(cases, labels, sft):
            expected = {'task_id': case['source_task_id'], 'case_id': case['case_id'],
                'family': case['family'], 'template_id': case['template_id'], 'source': case['source'],
                'prompt': formal_prompt(case['public']), 'completion': canonical({'findings': label['findings']})}
            assert row == expected
            for finding in label['findings']:
                counts[finding['id']][finding['status']] += 1
        assert dict(counts) == summary['status_counts']
    return {'metadata_verified': True, 'private_labels_replayed': private is not None,
            'human_evaluation_claim': False, 'formal_ready': False}


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-root', type=Path)
    parser.add_argument('--export', type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.private_root, args.export), indent=2))
