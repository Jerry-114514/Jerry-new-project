"""Read train/validation exports only; measure exact production SFT encoding."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

SOURCE = Path('/root/autodl-tmp/Jerry-formal-v2-20261022')
DATA = Path('/root/autodl-tmp/procedural-candidates-v3-20261023/export')
MODEL = Path('/root/autodl-tmp/models/Qwen3.5-9B')
OUT = Path('/root/autodl-tmp/procedural-target-lengths-20261023')
sys.path.insert(0, str(SOURCE))
from intentlab.neural import encode_pair
from intentlab.prompts import prompt_ids
from transformers import AutoTokenizer

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def stats(values):
    values = sorted(values)
    return {'minimum': values[0], 'maximum': values[-1], 'sum': sum(values),
            'p50': values[(len(values)-1)*50//100],
            'p95': values[(len(values)-1)*95//100],
            'p99': values[(len(values)-1)*99//100]}

head = subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip()
assert head == '8eacc3a05b289b9d10189b2a304fdea82d8e7eb7'
assert not subprocess.check_output(['git', '-C', str(SOURCE), 'status', '--porcelain'])
expected = json.loads((SOURCE/'examples/results/formal-m2j-procedural-candidates/private-file-sha256.json').read_text())
official = json.loads((SOURCE/'configs/qwen35-official-assets.json').read_text())
wanted = {'config.json', 'tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja', 'merges.txt', 'vocab.json'}
assets = {}
for entry in official['assets']:
    if entry['path'] not in wanted:
        continue
    raw = (MODEL/entry['path']).read_bytes()
    actual = hashlib.sha256(raw).hexdigest() if 'sha256' in entry else hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    assert actual == entry.get('sha256', entry.get('git_blob_sha1'))
    assets[entry['path']] = hashlib.sha256(raw).hexdigest()
assert set(assets) == wanted
OUT.mkdir(mode=0o700, exist_ok=False)
(OUT/'driver.py').write_bytes(Path(__file__).read_bytes())
(OUT/'status.json').write_text(json.dumps({'status': 'running', 'source_commit': head}))
tokenizer = AutoTokenizer.from_pretrained(MODEL, local_files_only=True, trust_remote_code=False)
summary = {'source_commit': head, 'driver_sha256': sha(Path(__file__)),
           'tokenizer_files_sha256': assets, 'official_revision': official['revision'],
           'packages': {p: importlib.metadata.version(p) for p in ('transformers', 'tokenizers')},
           'weights_loaded': False, 'gpu_used': False, 'heldout_files_read': False,
           'truncation': False, 'fewshot_measured': False,
           'formal_budget_approved': False, 'splits': {}}
all_rows = []
for split, count in [('train', 2400), ('validation', 600)]:
    path = DATA/(split+'.jsonl')
    assert sha(path) == expected['export/'+path.name]
    pairs = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    assert len(pairs) == count
    rows = []
    for pair in pairs:
        prompt = len(prompt_ids(tokenizer, pair['prompt']))
        target = len(tokenizer.encode(pair['completion'], add_special_tokens=False)) + int(tokenizer.eos_token_id is not None)
        encoded = encode_pair(tokenizer, pair, prompt+target)
        assert len(encoded['input_ids']) == prompt+target
        assert sum(x != -100 for x in encoded['labels']) == target
        rows.append({'case_id': pair['case_id'], 'source_task_id': pair['task_id'],
                     'family': pair['family'], 'split': split,
                     'prompt_tokens': prompt, 'target_tokens_including_eos': target,
                     'total_tokens': prompt+target})
    summary['splits'][split] = {'views': count, 'pair_file_sha256': sha(path),
        'prompt_tokens': stats([r['prompt_tokens'] for r in rows]),
        'target_tokens_including_eos': stats([r['target_tokens_including_eos'] for r in rows]),
        'total_tokens': stats([r['total_tokens'] for r in rows]),
        'training_overflow': {str(n): sum(r['total_tokens'] > n for r in rows) for n in (2048,3328,4096,4608,6144,8192)},
        'inference_cannot_reserve_512': {str(n): sum(r['prompt_tokens']+512 > n for r in rows) for n in (2048,3328,4096,4608,6144,8192)},
        'targets_exceed_512': sum(r['target_tokens_including_eos'] > 512 for r in rows)}
    all_rows.extend(rows)
for name, value in [('summary.json', summary), ('lengths.json', all_rows), ('status.json', {'status': 'completed'})]:
    (OUT/name).write_text(json.dumps(value, indent=2, sort_keys=True)+'\n', encoding='utf-8')
print(json.dumps(summary, indent=2), flush=True)
