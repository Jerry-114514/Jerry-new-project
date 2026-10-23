"""Two-update development probe: actual median/max train and validation pairs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

SOURCE = Path('/root/autodl-tmp/Jerry-formal-v2-20261022')
DATA = Path('/root/autodl-tmp/procedural-candidates-v3-20261023/export')
LENGTHS = Path('/root/autodl-tmp/procedural-target-lengths-20261023')
OUT = Path('/root/autodl-tmp/procedural-real-probe-20261023')
head = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
assert head == '8eacc3a05b289b9d10189b2a304fdea82d8e7eb7'
assert not subprocess.check_output(['git', '-C', str(SOURCE), 'status', '--porcelain'])
summary = json.loads((LENGTHS/'summary.json').read_text())
lengths = json.loads((LENGTHS/'lengths.json').read_text())
OUT.mkdir(mode=0o700, exist_ok=False)
(OUT/'driver.py').write_bytes(Path(__file__).read_bytes())
data = OUT/'data'
data.mkdir()
selection = {}
for split in ('train', 'validation'):
    path = DATA/(split+'.jsonl')
    assert hashlib.sha256(path.read_bytes()).hexdigest() == summary['splits'][split]['pair_file_sha256']
    pairs = {r['case_id']: r for r in map(json.loads, path.read_text().splitlines())}
    ordered = sorted((r for r in lengths if r['split'] == split), key=lambda r: (r['total_tokens'], r['case_id']))
    selected = [ordered[(len(ordered)-1)//2], ordered[-1]]
    assert len({r['source_task_id'] for r in selected}) == 2
    selection[split] = selected
    (data/(split+'.jsonl')).write_text(''.join(json.dumps(pairs[r['case_id']], sort_keys=True)+'\n' for r in selected))
(data/'test.jsonl').write_text('INVALID JSON: deferred test must never be read\n')
command = [sys.executable, '-m', 'intentlab.neural', '--data', str(data), '--out', str(OUT/'train'),
    '--model', '/root/autodl-tmp/models/Qwen3.5-9B', '--mode', 'qlora', '--device', 'cuda',
    '--schedule', 'cosine', '--steps', '2', '--eval-every', '1', '--batch-size', '1',
    '--accumulation', '2', '--max-length', '7168', '--lr', '0.00005', '--minimum-lr', '0.000005',
    '--rank', '16', '--alpha', '32', '--seed', '0', '--limit', '0', '--threads', '2', '--defer-test']
record = {'status': 'running', 'scope': 'real_development_resource_probe_not_formal_training',
          'source_commit': head, 'selection_policy': 'lower median and maximum total length per split; case_id tie break',
          'selection': selection, 'command': command, 'heldout_read': False,
          'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
(OUT/'attempt.json').write_text(json.dumps(record, indent=2)+'\n')
start = time.perf_counter()
with (OUT/'train.log').open('w') as log:
    result = subprocess.run(command, cwd=SOURCE, stdout=log, stderr=subprocess.STDOUT)
record.update(status='completed' if result.returncode == 0 else 'failed', exit_code=result.returncode,
              wall_seconds=time.perf_counter()-start)
(OUT/'attempt.json').write_text(json.dumps(record, indent=2)+'\n')
print(json.dumps(record, indent=2), flush=True)
raise SystemExit(result.returncode)
