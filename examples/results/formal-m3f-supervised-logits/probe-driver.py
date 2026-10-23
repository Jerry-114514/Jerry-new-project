"""Two-update synthetic 4608-token resource probe, with 512 target tokens."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

source = Path('/root/autodl-tmp/supervised-logits-source-20261023')
root = Path('/root/autodl-tmp/supervised-logits-probe-20261023')
root.mkdir(exist_ok=False)
sys.path.insert(0, str(source))
from intentlab.neural import encode_pair
from intentlab.prompts import prompt_ids
from transformers import AutoTokenizer
tokenizer = AutoTokenizer.from_pretrained('/root/autodl-tmp/models/Qwen3.5-9B', local_files_only=True, trust_remote_code=False)
target = ' x' * 511
assert len(tokenizer.encode(target, add_special_tokens=False)) + 1 == 512
rows = []
for name in ('train-a', 'train-b', 'validation'):
    prefix = 'Synthetic hardware input ' + name + '; no real task labels.\n'
    fill = 4096 - len(prompt_ids(tokenizer, prefix))
    for _ in range(10):
        prompt = prefix + ' x' * fill
        actual = len(prompt_ids(tokenizer, prompt))
        if actual == 4096:
            break
        fill += 4096 - actual
    row = {'task_id': 'synthetic-supervised-logits-' + name, 'prompt': prompt, 'completion': target}
    encoded = encode_pair(tokenizer, row, 4608)
    assert len(encoded['input_ids']) == 4608
    assert sum(v != -100 for v in encoded['labels']) == 512
    rows.append(row)
data = root / 'data'
data.mkdir()
for name, subset in [('train', rows[:2]), ('validation', rows[2:])]:
    (data / (name + '.jsonl')).write_text(''.join(json.dumps(r, sort_keys=True) + '\n' for r in subset))
(data / 'test.jsonl').write_text('DO NOT READ: no test data exists\n')
command = [sys.executable, '-m', 'intentlab.neural', '--data', str(data), '--out', str(root / 'train'),
    '--model', '/root/autodl-tmp/models/Qwen3.5-9B', '--mode', 'qlora', '--device', 'cuda', '--schedule', 'cosine',
    '--steps', '2', '--eval-every', '1', '--batch-size', '1', '--accumulation', '2', '--max-length', '4608',
    '--lr', '0.00005', '--minimum-lr', '0.000005', '--rank', '16', '--alpha', '32', '--seed', '0', '--limit', '0', '--threads', '2', '--defer-test']
record = {'scope': 'synthetic_hardware_only', 'status': 'running', 'created_utc': datetime.now(timezone.utc).isoformat(),
    'sequence_tokens': 4608, 'target_tokens_per_sample': 512, 'command': command,
    'source_parent': 'e698bec8b9c77c5e20344551145acaaee66050bc',
    'neural_py_sha256': hashlib.sha256((source / 'intentlab/neural.py').read_bytes()).hexdigest(),
    'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'formal_training': False, 'human_labels': False}
(root / 'attempt.json').write_text(json.dumps(record, indent=2) + '\n')
started = time.perf_counter()
with (root / 'train.log').open('w') as handle:
    result = subprocess.run(command, cwd=source, stdout=handle, stderr=subprocess.STDOUT)
record.update(status='completed' if result.returncode == 0 else 'failed', exit_code=result.returncode, wall_seconds=time.perf_counter() - started)
(root / 'attempt.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record, indent=2), flush=True)
