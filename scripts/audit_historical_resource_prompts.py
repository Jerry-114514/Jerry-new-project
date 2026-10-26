"""Classify ten old public resource-probe files by their complete literal rows.

Reads immutable historical Git objects only. Does not inspect current datasets,
labels or predictions, and does not establish broader reuse exclusion or M2.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


TARGETS = [('examples/results/formal-m3a-context-probe/data-1024', 'stress'),
           ('examples/results/formal-m3a-context-probe/data-2048', 'stress'),
           ('examples/results/formal-m3c-context-coverage/data-3328', 'stress'),
           ('examples/results/formal-m3c-context-coverage/data-4096', 'stress'),
           ('examples/results/formal-m3f-supervised-logits/data', 'supervised_logits')]
GENERATORS = {'stress': 'examples/results/formal-m3a-context-probe/context_probe.py',
              'supervised_logits': 'examples/results/formal-m3f-supervised-logits/probe-driver.py'}


def decode_lines(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key in probe')
            result[key] = value
        return result
    return [json.loads(line, object_pairs_hook=unique)
            for line in raw.decode('utf-8').splitlines() if line.strip()]


def check_rows(rows, split, family):
    if split not in ('train', 'validation') or family not in GENERATORS:
        raise ValueError('Unknown probe format')
    names = ['train-a', 'train-b'] if split == 'train' else ['validation']
    if not isinstance(rows, list) or len(rows) != len(names):
        raise ValueError('Unexpected probe population')
    fills = []
    for row, name in zip(rows, names):
        if not isinstance(row, dict) or set(row) != {'task_id', 'prompt', 'completion'}:
            raise ValueError('Unexpected probe fields')
        stress = family == 'stress'
        task = ('hardware-probe-' if stress else 'synthetic-supervised-logits-') + name
        prefix = ('Synthetic hardware stress input ' + name + '; no user task or requirement label.\n'
                  if stress else 'Synthetic hardware input ' + name + '; no real task labels.\n')
        completion = '{"hardware_probe":"synthetic-no-task-label"}' if stress else ' x' * 511
        if row['task_id'] != task or row['completion'] != completion or not isinstance(row['prompt'], str) \
                or not row['prompt'].startswith(prefix):
            raise ValueError('Probe literal prefix, identity or target differs')
        filler = row['prompt'][len(prefix):]
        if not re.fullmatch(r'( x)+', filler):
            raise ValueError('Probe contains non-filler content')
        fills.append(len(filler) // 2)
    return {'rows': len(rows), 'filler_repetitions': fills, 'complete_literal_format_matches': True}


def audit(repo, commit, inventory, expected_inventory_sha, out):
    repo, inventory, out = Path(repo), Path(inventory), Path(out)
    if out.exists():
        raise FileExistsError('Use a fresh audit directory')
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Full immutable Git commit required')
    raw_inventory = inventory.read_bytes()
    if hashlib.sha256(raw_inventory).hexdigest() != expected_inventory_sha:
        raise ValueError('Historical inventory SHA256 mismatch')
    index = {row['blob_sha']: row for row in json.loads(raw_inventory)}

    def git(*args):
        return subprocess.check_output(['git', *args], cwd=repo)

    generators = {}
    for family, path in GENERATORS.items():
        raw = git('show', commit + ':' + path)
        source = raw.decode('utf-8')
        fragments = ['prefix = "Synthetic hardware stress input " + name + "; no user task or requirement label.\\n"',
                     'prompt = prefix + " x" * n', 'completion = canonical({"hardware_probe": "synthetic-no-task-label"})'] \
                    if family == 'stress' else ["prefix = 'Synthetic hardware input ' + name + '; no real task labels.\\n'",
                                                "prompt = prefix + ' x' * fill", "target = ' x' * 511"]
        if not all(fragment in source for fragment in fragments):
            raise ValueError('Historical generator literals differ; review required')
        generators[family] = {'path': path, 'sha256': hashlib.sha256(raw).hexdigest(),
                              'literal_fragments_checked': len(fragments)}
    records = []
    for directory, family in TARGETS:
        for split in ('train', 'validation'):
            path = directory + '/' + split + '.jsonl'
            raw = git('show', commit + ':' + path)
            blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
            entry = index.get(blob)
            if entry is None or entry['bytes'] != len(raw) or entry['parse_status'] != 'parsed' \
                    or entry['extraction_counts'].get('recognized_input_containers', 0):
                raise ValueError('Probe is outside the recorded unrecognized historical scope')
            rows = decode_lines(raw)
            records.append({'path': path, 'blob_sha': blob, 'sha256': hashlib.sha256(raw).hexdigest(),
                            'bytes': len(raw), 'family': family, **check_rows(rows, split, family)})
    if inventory.read_bytes() != raw_inventory:
        raise ValueError('Inventory changed during audit')
    result = {'kind': 'historical_literal_resource_prompt_review', 'source_commit': commit,
              'historical_inventory_sha256': expected_inventory_sha, 'files_reviewed': len(records),
              'rows_reviewed': sum(r['rows'] for r in records), 'generators': generators, 'records': records,
              'full_literal_rows_checked': True, 'generator_literal_fragments_checked': True,
              'tokenizer_or_models_loaded': False, 'token_lengths_reproduced': False,
              'current_tasks_gold_predictions_opened': False, 'historical_scope_fully_reviewed': False,
              'semantic_independence_proven': False, 'm2_complete': False}
    out.mkdir(parents=True, exist_ok=False)
    (out / 'summary.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--inventory', required=True, type=Path)
    parser.add_argument('--expected-inventory-sha256', required=True)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    result = audit(args.repo, args.source_commit, args.inventory, args.expected_inventory_sha256, args.out)
    print(json.dumps({k: result[k] for k in ('files_reviewed', 'rows_reviewed', 'full_literal_rows_checked',
                                            'current_tasks_gold_predictions_opened', 'm2_complete')}))


if __name__ == '__main__':
    main()
