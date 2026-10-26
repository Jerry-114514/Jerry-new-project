"""Reconstruct public contracts from committed generators and private seed commitments.

Reads no labels, reference files, model predictions or model weights. Never writes
contracts or changes the frozen dataset. The output contains aggregate evidence only.
"""
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def audit(commit, tasks_path, base_seed_path, matched_seed_path, out):
    out = Path(out)
    if out.exists():
        raise FileExistsError('Preserve previous audits; choose a new output directory')
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Full frozen source commit required')

    def frozen(path):
        return subprocess.check_output(['git', 'show', commit + ':' + path], cwd=ROOT)

    source_hashes = {}
    for name in ('core', 'procedural_data', 'matched_test_data'):
        path = 'intentlab/' + name + '.py'
        raw = frozen(path)
        if (ROOT / path).read_text(encoding='utf-8') != raw.decode('utf-8'):
            raise ValueError('Current generator source differs from frozen commit: ' + path)
        source_hashes[path] = sha(raw)
    from intentlab.core import canonical, digest
    from intentlab.procedural_data import make_task
    from intentlab.matched_test_data import reword

    plan = json.loads(frozen('configs/procedural-data-plan.json'))
    base = json.loads(frozen('examples/results/formal-m2j-procedural-candidates/summary.json'))
    matched = json.loads(frozen('examples/results/formal-m2m-matched-test/summary.json'))
    files = json.loads(frozen('examples/results/formal-m2m-matched-test/private-file-sha256-local.json'))
    if digest(plan) != base['plan_hash']:
        raise ValueError('Frozen plan hash mismatch')
    seeds = json.loads(Path(base_seed_path).read_text(encoding='utf-8'))
    matched_seed = json.loads(Path(matched_seed_path).read_text(encoding='utf-8'))['seed']
    splits = ('train', 'validation', 'test', 'ood')
    if set(seeds) != set(splits):
        raise ValueError('Four base split seeds required')
    values = list(seeds.values()) + [matched_seed]
    if any(not isinstance(s, str) or not re.fullmatch(r'[0-9a-f]{64}', s) for s in values):
        raise ValueError('Invalid private seed format')
    if len(set(values)) != 5:
        raise ValueError('Five distinct private streams required')
    if any(sha(bytes.fromhex(seeds[s])) != base['seed_commitments'][s] for s in splits):
        raise ValueError('Base seed commitment mismatch')
    if sha(bytes.fromhex(matched_seed)) != matched['seed_commitment']:
        raise ValueError('Matched seed commitment mismatch')

    original = Path(tasks_path).read_bytes()
    if sha(original) != files['tasks.jsonl']:
        raise ValueError('Task file differs from frozen file SHA256')
    tasks = [json.loads(line) for line in original.splitlines() if line.strip()]
    if digest(tasks) != matched['tasks_hash']:
        raise ValueError('Task list differs from frozen canonical digest')
    rebuilt = []
    for split in splits:
        families = plan['ood_families'] if split == 'ood' else plan['train_families']
        local_plan = deepcopy(plan)
        seed, count = seeds[split], plan['counts'][split]
        if split == 'test':
            seed, count = matched_seed, matched['matched_test_source_tasks']
            local_plan['layouts']['test'] = deepcopy(plan['layouts']['train'])
        for index in range(count):
            family = families[index % len(families)]
            task, _ = make_task(family, split, index // len(families), seed, local_plan)
            rebuilt.append(reword(task) if split == 'test' else task)
    rebuilt_raw = ''.join(canonical(task) + '\n' for task in rebuilt).encode('utf-8')
    by_id = {task['id']: task for task in tasks}
    rebuilt_by_id = {task['id']: task for task in rebuilt}
    summary = {
        'kind': 'frozen_public_contract_regeneration', 'schema_version': 1,
        'frozen_source_commit': commit, 'generator_source_sha256': source_hashes,
        'plan_hash': digest(plan), 'private_seed_commitments_verified': 5,
        'source_tasks': len(tasks), 'split_counts': dict(Counter(t['split'] for t in tasks)),
        'unique_original_ids': len(by_id), 'unique_regenerated_ids': len(rebuilt_by_id),
        'id_sets_equal': by_id.keys() == rebuilt_by_id.keys(),
        'all_contract_fields_equal': tasks == rebuilt,
        'canonical_list_digest': digest(tasks), 'regenerated_list_digest': digest(rebuilt),
        'frozen_tasks_file_sha256': sha(original), 'regenerated_tasks_file_sha256': sha(rebuilt_raw),
        'canonical_jsonl_byte_identical': original == rebuilt_raw,
        'source_origins': dict(Counter(t['source']['origin'] for t in tasks)),
        'source_license_declarations': dict(Counter(t['source']['license'] for t in tasks)),
        'labels_or_references_opened': False, 'model_calls': 0,
        'frozen_data_changed': False, 'human_evaluation_claim': False,
        'semantic_independence_proven': False, 'm2_complete': False,
        'limitations': [
            'Proves deterministic reconstruction under the recorded generator and seed commitments, not universal originality.',
            'Shared generators, finite operation support and retained cross-split near duplicates remain unchanged.',
            'Source license strings are declarations, not independent legal certification.',
            'Does not audit all external assets, pretraining contamination, label semantics or model generalization.',
        ],
    }
    summary['passed'] = (len(tasks) == len(by_id) == len(rebuilt_by_id) == 1050
                         and summary['id_sets_equal'] and summary['all_contract_fields_equal']
                         and summary['canonical_jsonl_byte_identical'])
    out.mkdir(parents=True, exist_ok=False)
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + '\n',
                                      encoding='utf-8', newline='\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--tasks', required=True)
    parser.add_argument('--base-seeds', required=True)
    parser.add_argument('--matched-seed', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    result = audit(args.source_commit, args.tasks, args.base_seeds, args.matched_seed, args.out)
    print(json.dumps({key: result[key] for key in ('passed', 'source_tasks', 'split_counts',
                                                  'canonical_jsonl_byte_identical', 'm2_complete')}))
    raise SystemExit(0 if result['passed'] else 1)
