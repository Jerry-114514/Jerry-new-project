"""Verify saved synthetic-resource evidence; does not reproduce GPU training."""
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO))
from intentlab.core import digest


def audit():
    for name, expected in json.loads((ROOT / 'checksums.json').read_text()).items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected, name
    attempt = json.loads((ROOT / 'attempt.json').read_text())
    summary = json.loads((ROOT / 'hardware-summary.json').read_text())
    result = json.loads((ROOT / 'train/result.json').read_text())
    config = json.loads((ROOT / 'train/run_config.json').read_text())
    assert attempt['status'] == 'completed' and attempt['exit_code'] == 0
    assert attempt['sequence_tokens'] == summary['sequence_tokens'] == config['max_length'] == 4608
    assert attempt['target_tokens_per_sample'] == summary['target_tokens_per_sample'] == 512
    assert result['completed'] and result['test_deferred'] and config['defer_test']
    assert result['step'] == summary['successful_updates'] == config['steps'] == 2
    assert result['config'] == config
    rows = {name: [json.loads(line) for line in (ROOT / 'data' / (name + '.jsonl')).read_text().splitlines()] for name in ('train', 'validation')}
    assert digest(rows) == result['data_hash']
    assert len(rows['train']) == 2 and len(rows['validation']) == 1
    assert result['train_tokens'] == 4 * 4608 and result['supervised_tokens'] == 4 * 512
    assert result['examples_seen'] == 4 and all(r['count'] == 2 for r in result['sample_exposures'])
    assert len(result['history']) == 2
    assert all(r['validation']['target_tokens'] == 512 for r in result['history'])
    for name in ('peak_allocated_bytes', 'peak_reserved_bytes'):
        assert summary[name] == result[name] > 0
    assert result['peak_allocated_bytes'] <= result['peak_reserved_bytes'] < 32 * 1024**3
    assert attempt['driver_sha256'] == hashlib.sha256((ROOT / 'probe-driver.py').read_bytes()).hexdigest()
    assert attempt['neural_py_sha256'] == hashlib.sha256((REPO / 'intentlab/neural.py').read_bytes().replace(b'\r\n', b'\n')).hexdigest()
    assert json.loads((ROOT / 'source-snapshot.json').read_text())['intentlab/neural.py'] == attempt['neural_py_sha256']
    assets = json.loads((ROOT / 'official-assets-after-run.json').read_text())
    assert assets['revision'] == 'c202236235762e1c871ad0ccb60c8ee5ba337b9a' and len(assets['verified_assets']) == 13
    assert not summary['formal_training'] and not summary['human_task_labels']
    assert not summary['fewshot_coverage_proven'] and not summary['formal_training_runtime_estimated']
    return {'saved_evidence_verified': True, 'sequence_tokens': 4608, 'updates': 2, 'formal_training': False}


if __name__ == '__main__':
    print(json.dumps(audit(), indent=2))
