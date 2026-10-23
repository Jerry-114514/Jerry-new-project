"""One-shot private collection of the ten not-yet-run development contracts."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

source = Path('/root/autodl-tmp/Jerry-formal-v2-20261022')
sys.path.insert(0, str(source))
from intentlab.core import digest
from intentlab.formal_data import read_jsonl, write_jsonl
from intentlab.protocol import source_snapshot
from intentlab.trajectory_intake import build

assert subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD']).decode().strip() == '2e127573e6aefb4f51f1c558ce3adb7606ec4b0f'
assert not subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'])
root = Path('/root/autodl-tmp/wikisql-natural-collection-20261023')
root.mkdir(exist_ok=False)
adapted = Path('/root/autodl-tmp/wikisql-adapter-validation-20261023/source/runs/private-adaptation-v1')
tasks = read_jsonl(adapted / 'tasks.jsonl')
references = read_jsonl(adapted / 'candidate-references.jsonl')
assert digest(tasks) == json.loads((source / 'examples/results/formal-m2d-wikisql-adaptation/adapter-manifest.json').read_text())['tasks_hash']
assert len(tasks) == 12
write_jsonl(root / 'first-two-tasks.jsonl', tasks[:2])
write_jsonl(root / 'remaining-tasks.jsonl', tasks[2:])
remaining_ids = {t['id'] for t in tasks[2:]}
write_jsonl(root / 'remaining-references.jsonl', [r for r in references if r['task_id'] in remaining_ids])
assert len(remaining_ids) == 10
command = [sys.executable, '-m', 'intentlab.execution', '--tasks', str(root / 'remaining-tasks.jsonl'),
    '--references', str(root / 'remaining-references.jsonl'), '--out', str(root / 'execution'),
    '--actor-model', '/root/autodl-tmp/models/Qwen3.5-9B', '--analyzer-mode', 'rule', '--device', 'cuda',
    '--max-new-tokens', '768', '--token-budget', '8192', '--context-limit', '4096',
    '--max-repairs', '0', '--max-tool-steps', '3', '--actor-envelope', 'extract', '--policies', 'none']
(root / 'launch.json').write_text(json.dumps({'source_commit':'2e127573e6aefb4f51f1c558ce3adb7606ec4b0f',
    'source_normalized_sha256': source_snapshot(source), 'command': command,
    'selection': 'deterministic adapted task positions 2:12; first two already collected, no rerun',
    'scope': 'train_development_only', 'human_reviews_completed': 0, 'formal_training_started': False}, indent=2) + '\n')
print('Prepared ten remaining tasks; starting real-model initial attempts', flush=True)
with (root / 'execution.log').open('w') as log:
    process = subprocess.run(command, cwd=source, stdout=log, stderr=subprocess.STDOUT)
(root / 'execution-exit.json').write_text(json.dumps({'returncode': process.returncode}) + '\n')
if process.returncode:
    raise SystemExit(process.returncode)
first = build(root / 'first-two-tasks.jsonl',
    '/root/autodl-tmp/wikisql-adapter-validation-20261023/source/runs/private-execution-smoke', root / 'intake-first-two')
remaining = build(root / 'remaining-tasks.jsonl', root / 'execution', root / 'intake-remaining-ten')
print(json.dumps({'existing_runs': first['raw_runs'], 'new_runs': remaining['raw_runs'],
    'total_natural_views': first['views'] + remaining['views'], 'human_reviews_completed': 0}), flush=True)
