"""Replay aggregate counts from private per-case lengths; no answers required."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def audit(rows_path):
    checksums = json.loads((ROOT / 'checksums.json').read_text())
    for name, wanted in checksums.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == wanted, name
    expected = json.loads((ROOT / 'private-rows.json').read_text())
    assert hashlib.sha256(rows_path.read_bytes()).hexdigest() == expected['sha256']
    rows = json.loads(rows_path.read_text())
    summary = json.loads((ROOT / 'summary.json').read_text())
    assert len(rows) == len({r['case_id'] for r in rows}) == summary['views'] == 2400
    assert len({r['source_task_id'] for r in rows}) == summary['candidate_source_tasks'] == 600
    for kind in ('full', 'compact'):
        values = [r[kind]['prompt_tokens'] for r in rows]
        assert all(type(v) is int and v > 0 for v in values)
        expected = summary['formats'][kind]
        assert (min(values), max(values), sum(values)) == (expected['minimum'], expected['maximum'], expected['total_prompt_tokens'])
        assert max(values) + summary['generation_reservation'] == expected['minimum_context_with_512']
        for context, count in expected['cannot_reserve_512'].items():
            assert sum(v + summary['generation_reservation'] > int(context) for v in values) == count
        for context, count in expected['cannot_generate'].items():
            assert sum(v >= int(context) for v in values) == count
    assert not any(summary[k] for k in ('model_weights_loaded', 'gpu_used', 'human_labels_read', 'fewshot_measured', 'reviewed_SFT_targets_measured', 'training_memory_measured', 'formal_budget_approved', 'formal_training_started'))
    identity = json.loads((ROOT / 'runtime-identity.json').read_text())
    assert identity['driver_sha256'] == checksums['measure-driver.py']
    return {'verified': True, 'views': len(rows), 'formats_recomputed': 2, 'formal_ready': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows', type=Path, required=True)
    print(json.dumps(audit(parser.parse_args().rows), indent=2))
