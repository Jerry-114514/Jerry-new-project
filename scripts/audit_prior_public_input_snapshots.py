"""Extend prior-public input comparison to literal input-array file snapshots.

Uses the original six exact signature modes without changing frozen tasks.
Snapshot content may be model-modified; a match is a reuse risk for review,
not proof that the snapshot is the original task input or that answers leaked.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import audit_prior_public_inputs as legacy

LEGACY_SHA = '23063e03e879b7cee81671c8793ee4eb9750ed3d8246a79e441bb9df7db28bcd'
SKIP = {'oracle', 'gold', 'labels', 'findings', 'completion', 'text', 'references',
        'expected', 'expected_output', 'response', 'actions'}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def snapshots(value, counts):
    """Accept all input/ files only when every value is a literal object-row array."""
    if isinstance(value, dict):
        files = value.get('files')
        if isinstance(files, dict):
            selected = {path: rows for path, rows in files.items() if isinstance(path, str) and path.startswith('input/')}
            if selected:
                counts['snapshot_maps_with_input_paths'] += 1
                found = legacy.signatures(selected, True)
                if found is None:
                    counts['snapshot_maps_with_unsupported_input_values'] += 1
                else:
                    counts['recognized_input_snapshot_containers'] += 1
                    counts['recognized_snapshot_input_files'] += len(selected)
                    counts['recognized_snapshot_generated_rid_removed'] += sum(
                        isinstance(row.get('rid'), str) and bool(legacy.GENERATED_RID.fullmatch(row['rid']))
                        for rows in selected.values() for row in rows)
                    yield found
        for key, child in value.items():
            if key in SKIP:
                continue
            if key == 'prompt' and isinstance(child, str):
                start = child.find('{')
                if start >= 0:
                    try:
                        embedded, _ = json.JSONDecoder().raw_decode(child[start:])
                    except ValueError:
                        continue
                    yield from snapshots(embedded, counts)
            elif isinstance(child, (dict, list)):
                yield from snapshots(child, counts)
    elif isinstance(value, list):
        for child in value:
            yield from snapshots(child, counts)


def audit(repo, commit, current, expected_tasks_hash, inventory_path, expected_inventory_sha, out):
    repo, current, out = Path(repo), Path(current), Path(out)
    if out.exists():
        raise FileExistsError('Choose a fresh private audit directory')
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Full immutable Git commit required')
    if sha(Path(legacy.__file__).read_bytes()) != LEGACY_SHA:
        raise ValueError('Original six-mode signature helper changed')
    raw = current.read_bytes()
    tasks = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    if legacy.digest(tasks) != expected_tasks_hash:
        raise ValueError('Current contracts differ from the frozen content digest')
    index = defaultdict(list)
    for task in tasks:
        if set(task) & {'oracle', 'gold', 'labels', 'findings', 'references'}:
            raise ValueError('Current public contracts contain hidden fields')
        signatures = legacy.signatures(task['inputs'], True)
        if signatures is None:
            raise ValueError('Unsupported current public input map')
        for mode, signature in signatures.items():
            index[(mode, signature)].append((task['source_task_id'], task['split']))
    inventory_raw = Path(inventory_path).read_bytes()
    if sha(inventory_raw) != expected_inventory_sha:
        raise ValueError('Historical object inventory changed')
    inventory = json.loads(inventory_raw)
    listing = subprocess.check_output(['git', '-c', 'core.quotepath=false', 'rev-list', '--objects', commit,
                                      '--', 'data', 'examples/results'], cwd=repo).decode('utf-8')
    reachable = {line.split(' ', 1)[0] for line in listing.splitlines()
                 if ' ' in line and line.endswith(('.json', '.jsonl'))}
    if len(inventory) != len(reachable) or {r['blob_sha'] for r in inventory} != reachable:
        raise ValueError('Historical population differs from the recorded frozen scope')
    totals, records, flags, matched = Counter(), [], [], defaultdict(set)
    historical_signatures = defaultdict(set)
    process = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for entry in sorted(inventory, key=lambda r: r['blob_sha']):
            blob = entry['blob_sha']
            process.stdin.write((blob + '\n').encode('ascii')); process.stdin.flush()
            header = process.stdout.readline().decode('ascii').split()
            if len(header) != 3 or header[:2] != [blob, 'blob']:
                raise ValueError('Unexpected historical Git object')
            content = process.stdout.read(int(header[2]))
            if len(content) != int(header[2]) or process.stdout.read(1) != b'\n':
                raise ValueError('Incomplete historical object read')
            old, extra, found = Counter(), Counter(), set()
            record = {'blob_sha': blob, 'path_alias': entry['path_alias'], 'bytes': len(content)}
            try:
                text = content.decode('utf-8')
                values = [json.loads(line) for line in text.splitlines() if line.strip()] if entry['path_alias'].endswith('.jsonl') else [json.loads(text)]
                for value in values:
                    for name, generator in [('explicit_inputs', legacy.containers(value, old, True)),
                                            ('input_array_snapshots', snapshots(value, extra))]:
                        found.update((name, tuple(sorted(s.items()))) for s in generator)
            except (ValueError, UnicodeError, RecursionError) as exc:
                record.update(parse_status='unsupported_or_invalid_json', error_type=type(exc).__name__)
                totals['unparsed_json_objects'] += 1
            else:
                record['parse_status'] = 'parsed'
                totals['parsed_json_objects'] += 1
                totals['objects_with_any_supported_inputs' if found else 'objects_without_supported_inputs'] += 1
            if dict(old) != entry['extraction_counts'] or record['parse_status'] != entry['parse_status']:
                raise ValueError('Legacy extraction no longer reproduces the original inventory')
            if extra.get('recognized_input_snapshot_containers', 0):
                totals['objects_with_input_array_snapshots'] += 1
                if not old.get('recognized_input_containers', 0):
                    totals['previously_unrecognized_objects_with_input_array_snapshots'] += 1
            for extractor, signatures in sorted(found):
                for mode, signature in signatures:
                    historical_signatures[(extractor, mode)].add(signature)
                    for source, split in index.get((mode, signature), []):
                        flags.append({'source_task_id': source, 'split': split, 'mode': mode, 'extractor': extractor,
                                      'historical_blob_sha': blob, 'historical_path_alias': entry['path_alias']})
                        matched[(extractor, mode, split)].add(source)
            record.update(legacy_extraction_counts=dict(old), snapshot_extraction_counts=dict(extra))
            records.append(record)
            totals.update(old); totals.update(extra)
        process.stdin.close()
        if process.wait(timeout=30) != 0:
            raise ValueError('Historical Git reader failed')
    finally:
        if process.poll() is None:
            process.terminate(); process.wait(timeout=30)
    if current.read_bytes() != raw or Path(inventory_path).read_bytes() != inventory_raw:
        raise ValueError('Audit input changed')
    out.mkdir(parents=True, exist_ok=False)
    matches_raw = (json.dumps(flags, indent=2, sort_keys=True) + '\n').encode('utf-8')
    records_raw = (json.dumps(records, indent=2, sort_keys=True) + '\n').encode('utf-8')
    (out / 'private-matches.json').write_bytes(matches_raw)
    (out / 'historical-snapshot-inventory.json').write_bytes(records_raw)
    summary = {'kind': 'prior_public_literal_input_snapshot_reuse_audit', 'schema_version': 1,
        'source_commit': commit, 'historical_roots': ['data', 'examples/results'],
        'historical_inventory_sha256': expected_inventory_sha, 'historical_json_blobs': len(inventory),
        'legacy_helper_sha256': LEGACY_SHA, 'legacy_counts_reproduced_for_all_objects': True,
        'current_tasks_file_sha256': sha(raw), 'current_tasks_content_hash': legacy.digest(tasks),
        'current_sources_by_split': dict(Counter(t['split'] for t in tasks)), 'coverage': dict(totals),
        'current_generated_rid_fields_removed': sum(isinstance(row.get('rid'), str) and
            bool(legacy.GENERATED_RID.fullmatch(row['rid'])) for t in tasks for rows in t['inputs'].values() for row in rows),
        'distinct_historical_signatures_by_extractor_mode': {'/'.join(key): len(value)
            for key, value in sorted(historical_signatures.items())},
        'match_records': len(flags), 'matching_current_sources_by_extractor_mode_split': {
            '/'.join(key): len(value) for key, value in sorted(matched.items())},
        'private_matches_sha256': sha(matches_raw), 'new_inventory_sha256': sha(records_raw),
        'driver_sha256': sha(Path(__file__).read_bytes()), 'candidate_changed': False,
        'current_gold_references_or_model_outputs_opened': False, 'historical_output_bearing_json_parsed': True,
        'semantic_independence_proven': False, 'm2_complete': False,
        'limitations': ['Only the fixed recorded historical Git scope; external/untracked assets and pretraining data remain outside it.',
            'New extraction requires a files map whose input/ entries are all literal arrays of object rows; strings, other structures and other path conventions remain unsupported.',
            'Uses the original six exact signature modes. Only declared generated rid strings and selected path/file-boundary normalization are removed; other fields, values, types and row order remain.',
            'Only the first JSON object in prompt strings is traversed; answer-bearing fields are skipped using the original policy.',
            'File snapshots may include modified inputs; a match is a conservative public-reuse risk, not proof of original input identity or answer leakage.',
            'No matched candidates are removed or regenerated. Cross-split near duplicates and statistical independence are not resolved.']}
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--current-tasks', type=Path, required=True)
    parser.add_argument('--expected-tasks-hash', required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--expected-inventory-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.repo, args.source_commit, args.current_tasks, args.expected_tasks_hash,
                   args.inventory, args.expected_inventory_sha256, args.out)
    print(json.dumps({k: result[k] for k in ('historical_json_blobs', 'coverage', 'match_records',
          'matching_current_sources_by_extractor_mode_split', 'm2_complete')}))
