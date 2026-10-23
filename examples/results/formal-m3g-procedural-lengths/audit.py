"""Check recorded development evidence; does not replay tokenizer or GPU."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
checks = json.loads((root/'checksums.json').read_text(encoding='utf-8'))
for name, expected in checks.items():
    assert hashlib.sha256((root/name).read_bytes()).hexdigest() == expected, name
summary = json.loads((root/'summary.json').read_text(encoding='utf-8'))
attempt = json.loads((root/'probe-attempt.json').read_text(encoding='utf-8'))
result = json.loads((root/'probe-result.json').read_text(encoding='utf-8'))
assert attempt['status'] == 'completed' and attempt['exit_code'] == 0
assert summary['source_commit'] == attempt['source_commit']
assert summary['heldout_files_read'] is False and attempt['heldout_read'] is False
assert summary['formal_budget_approved'] is False and summary['fewshot_measured'] is False
assert summary['splits']['train']['views'] == 2400
assert summary['splits']['validation']['views'] == 600
assert result['completed'] and result['test_deferred'] and result['step'] == 2
assert result['examples_seen'] == 4 and result['train_tokens'] == 13616
assert result['supervised_tokens'] == 692
assert result['peak_reserved_bytes'] >= result['peak_allocated_bytes'] > 0
assert len(result['history']) == 2
assert all(h['validation']['target_tokens'] == 426 for h in result['history'])
assert attempt['driver_sha256'] == checks['probe-driver.py']
assert summary['driver_sha256'] == checks['measure-driver.py']
for split in ('train', 'validation'):
    selected = attempt['selection'][split]
    assert len({r['source_task_id'] for r in selected}) == 2
    assert max(r['total_tokens'] for r in selected) == summary['splits'][split]['total_tokens']['maximum']
    assert max(r['total_tokens'] for r in selected) <= result['config']['max_length']
print('Saved real-development length/probe evidence verified; formal experiments remain incomplete.')
