"""Measure complete unreviewed train prompts; never load weights or labels."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import runpy
import subprocess
import sys


def main(source, model, cases_path, out):
    sys.path.insert(0, str(source))
    from intentlab.core import digest
    from intentlab.formal_data import formal_prompt, read_jsonl, validate_cases
    from intentlab.prompts import prompt_ids
    from intentlab.protocol import source_snapshot
    from transformers import AutoTokenizer

    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD']).decode().strip()
    assert head == '031007bef9f16360e5d4ff30f3c55acd0835954c'
    assert not subprocess.check_output(['git', '-C', str(source), 'status', '--porcelain'])
    case_sha = hashlib.sha256(cases_path.read_bytes()).hexdigest()
    file_hashes = json.loads((source / 'examples/results/formal-m2g-training-scale/private-file-sha256.json').read_text())
    assert case_sha == file_hashes['adapted/cases.jsonl']
    official = json.loads((source / 'configs/qwen35-official-assets.json').read_text())
    wanted = {'config.json', 'tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja', 'merges.txt', 'vocab.json'}
    assets = {}
    for entry in official['assets']:
        if entry['path'] not in wanted:
            continue
        raw = (model / entry['path']).read_bytes()
        actual = hashlib.sha256(raw).hexdigest() if 'sha256' in entry else hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        assert actual == entry.get('sha256', entry.get('git_blob_sha1'))
        assets[entry['path']] = hashlib.sha256(raw).hexdigest()
    assert set(assets) == wanted
    cases = read_jsonl(cases_path)
    manifest = json.loads((source / 'examples/results/formal-m2g-training-scale/adapter-manifest.json').read_text())
    assert digest(cases) == manifest['cases_hash']
    validate_cases(cases)
    assert len(cases) == len({c['case_id'] for c in cases}) == 2400
    assert len({c['source_task_id'] for c in cases}) == 600
    assert all(c['split'] == 'train' for c in cases)
    compact = runpy.run_path(str(source / 'examples/results/formal-m3c-context-coverage/compact-driver.py'))['compact_prompt']
    tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True, trust_remote_code=False)
    rows = []
    for case in cases:
        row = {'case_id': case['case_id'], 'source_task_id': case['source_task_id']}
        for kind, prompt in [('full', formal_prompt(case['public'])), ('compact', compact(case['public']))]:
            row[kind] = {'prompt_hash': digest(prompt), 'prompt_tokens': len(prompt_ids(tokenizer, prompt))}
        rows.append(row)
    prior = json.loads((source / 'examples/results/formal-m3c-context-coverage/lengths-by-context.json').read_text())
    prior_compact = json.loads((source / 'examples/results/formal-m3c-context-coverage/compact-trial.json').read_text())
    old = {r['case_id']: r for r in prior['2048']['rows']}
    old_compact = {r['case_id']: r for r in prior_compact['rows']}
    overlap = [r for r in rows if r['case_id'] in old]
    assert len(overlap) == 48
    for row in overlap:
        for key in ('prompt_hash', 'prompt_tokens'):
            assert row['full'][key] == old[row['case_id']][key]
            assert row['compact'][key] == old_compact[row['case_id']][key]
    report = {'scope': 'unreviewed_single_template_train_zero_shot_lengths', 'views': 2400,
        'candidate_source_tasks': 600, 'prior_views_verified': 48, 'generation_reservation': 512,
        'cases_sha256': case_sha, 'cases_hash': digest(cases), 'formats': {},
        'model_weights_loaded': False, 'gpu_used': False, 'human_labels_read': False,
        'fewshot_measured': False, 'reviewed_SFT_targets_measured': False,
        'training_memory_measured': False, 'formal_budget_approved': False,
        'formal_training_started': False,
        'warning': 'Complete zero-shot input lengths only. A 512-token allowance is not a measured training target. Compact format preserves public data but can change predictions. No truncation, labels or formal approval.'}
    for kind in ('full', 'compact'):
        values = sorted(r[kind]['prompt_tokens'] for r in rows)
        report['formats'][kind] = {'minimum': values[0], 'maximum': values[-1],
            'total_prompt_tokens': sum(values), 'minimum_context_with_512': values[-1] + 512,
            'cannot_reserve_512': {str(n): sum(v + 512 > n for v in values) for n in (2048, 3072, 3328, 4096, 6144, 8192)},
            'cannot_generate': {str(n): sum(v >= n for v in values) for n in (2048, 3072, 3328, 4096, 6144, 8192)}}
    identity = {'source_commit': head, 'source_normalized_sha256': source_snapshot(source),
        'python': platform.python_version(), 'packages': {n: importlib.metadata.version(n) for n in ('transformers', 'tokenizers')},
        'official_model': official['model'], 'official_revision': official['revision'],
        'tokenizer_files_sha256': assets, 'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    out.mkdir(exist_ok=False)
    for name, data in [('summary.json', report), ('lengths.json', rows), ('runtime-identity.json', identity)]:
        (out / name).write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(report, indent=2), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source', 'model', 'cases', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    main(args.source, args.model, args.cases, args.out)
