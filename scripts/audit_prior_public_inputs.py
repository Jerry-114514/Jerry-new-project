"""Compare frozen public inputs with recognizable inputs in prior Git JSON history.

This reports exact reuse only. It does not inspect current gold, score models,
remove candidates, prove semantic independence, or certify data authorization.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import subprocess


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


GENERATED_RID = re.compile(r'[0-9a-f]{12}-[0-9]+-[0-9]+')


def signatures(inputs, drop_generated_rid=False):
    if not isinstance(inputs, dict) or not inputs or not all(
        isinstance(path, str) and isinstance(rows, list) and all(isinstance(row, dict) for row in rows)
        for path, rows in inputs.items()
    ):
        return None
    groups = [inputs[path] for path in sorted(inputs)]
    result = {
        'exact_paths_fields_values': digest(inputs),
        'path_names_removed_file_groups_preserved': digest(groups),
        'paths_and_file_boundaries_removed': digest([row for rows in groups for row in rows]),
    }
    if drop_generated_rid:
        stripped = {path: [{key: value for key, value in row.items()
                           if not (key == 'rid' and isinstance(value, str) and GENERATED_RID.fullmatch(value))}
                          for row in rows] for path, rows in inputs.items()}
        clean_groups = [stripped[path] for path in sorted(stripped)]
        result.update({
            'generated_rid_removed_paths_preserved': digest(stripped),
            'generated_rid_and_paths_removed_groups_preserved': digest(clean_groups),
            'generated_rid_paths_and_file_boundaries_removed': digest([row for rows in clean_groups for row in rows]),
        })
    return result


def containers(value, counts, drop_generated_rid=False):
    """Read only input containers, plus JSON objects embedded in prompt fields."""
    if isinstance(value, dict):
        if 'inputs' in value:
            found = signatures(value['inputs'], drop_generated_rid)
            if found is not None:
                counts['recognized_input_containers'] += 1
                if drop_generated_rid:
                    counts['recognized_generated_rid_fields_removed'] += sum(
                        isinstance(row.get('rid'), str) and bool(GENERATED_RID.fullmatch(row['rid']))
                        for rows in value['inputs'].values() for row in rows)
                yield found
        for key, child in value.items():
            if key in {'oracle', 'gold', 'labels', 'findings', 'completion', 'text',
                       'references', 'expected', 'expected_output', 'response', 'actions'}:
                continue
            if key == 'prompt' and isinstance(child, str):
                counts['prompt_strings_seen'] += 1
                start = child.find('{')
                if start >= 0:
                    try:
                        embedded, _ = json.JSONDecoder().raw_decode(child[start:])
                    except ValueError:
                        counts['prompt_json_not_decodable'] += 1
                    else:
                        counts['prompt_first_json_decoded'] += 1
                        yield from containers(embedded, counts, drop_generated_rid)
                else:
                    counts['prompt_without_json_object'] += 1
            elif isinstance(child, (dict, list)):
                yield from containers(child, counts, drop_generated_rid)
    elif isinstance(value, list):
        for child in value:
            yield from containers(child, counts, drop_generated_rid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--current-tasks', type=Path, required=True)
    parser.add_argument('--expected-tasks-hash', required=True, help='Frozen canonical list digest, not file SHA256')
    parser.add_argument('--source-commit', required=True, help='Full pre-test commit SHA')
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--out', type=Path, required=True, help='New private audit directory')
    parser.add_argument('--drop-generated-rid', action='store_true',
                        help='Also compare after removing rid strings matching the declared generated identity format')
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{40}', args.source_commit):
        raise ValueError('A full immutable Git commit is required')
    raw = args.current_tasks.read_bytes()
    tasks = [json.loads(line) for line in raw.decode('utf-8').splitlines() if line.strip()]
    if digest(tasks) != args.expected_tasks_hash:
        raise ValueError('Current public contracts differ from frozen content digest')
    index = defaultdict(list)
    for task in tasks:
        if set(task) & {'oracle', 'gold', 'labels', 'findings', 'references'}:
            raise ValueError('Current contracts must not contain hidden answers')
        found = signatures(task['inputs'], args.drop_generated_rid)
        if found is None:
            raise ValueError('Unsupported current input container')
        for mode, signature in found.items():
            index[(mode, signature)].append((task['source_task_id'], task['split']))
    listing = subprocess.check_output([
        'git', '-c', 'core.quotepath=false', 'rev-list', '--objects', args.source_commit,
        '--', 'data', 'examples/results'], cwd=args.repo, text=True, encoding='utf-8')
    inventory = {}
    for line in listing.splitlines():
        if ' ' in line and line.endswith(('.json', '.jsonl')):
            sha, alias = line.split(' ', 1)
            inventory[sha] = alias
    args.out.mkdir(parents=True, exist_ok=False)
    records, flags, totals = [], [], Counter()
    matched = defaultdict(set)
    process = subprocess.Popen(['git', 'cat-file', '--batch'], cwd=args.repo,
        stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    try:
        for sha, alias in sorted(inventory.items()):
            process.stdin.write((sha + '\n').encode('ascii'))
            process.stdin.flush()
            header = process.stdout.readline().decode('ascii').split()
            if len(header) != 3 or header[0] != sha or header[1] != 'blob':
                raise ValueError('Historical object is not the expected blob')
            size = int(header[2])
            content = process.stdout.read(size)
            if len(content) != size or process.stdout.read(1) != b'\n':
                raise ValueError('Incomplete historical object read')
            stats = Counter()
            record = {'blob_sha': sha, 'path_alias': alias, 'bytes': size}
            try:
                decoded = content.decode('utf-8')
                values = [json.loads(line) for line in decoded.splitlines() if line.strip()] if alias.endswith('.jsonl') else [json.loads(decoded)]
                found = {tuple(sorted(item.items())) for value in values for item in containers(value, stats, args.drop_generated_rid)}
            except (ValueError, UnicodeError, RecursionError) as exc:
                record.update(parse_status='unsupported_or_invalid_json', error_type=type(exc).__name__)
                totals['unparsed_json_objects'] += 1
                found = set()
            else:
                record['parse_status'] = 'parsed'
                totals['parsed_json_objects'] += 1
                totals['objects_with_recognized_inputs' if found else 'objects_without_recognized_inputs'] += 1
            for entry in found:
                for mode, signature in entry:
                    for source, split in index.get((mode, signature), []):
                        flags.append({'source_task_id': source, 'split': split, 'mode': mode,
                            'historical_blob_sha': sha, 'historical_path_alias': alias})
                        matched[(mode, split)].add(source)
            record['extraction_counts'] = dict(stats)
            records.append(record)
            totals.update(stats)
        process.stdin.close()
        if process.wait(timeout=30) != 0:
            raise ValueError('Historical Git reader did not exit cleanly')
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=30)
    private_flags = (json.dumps(flags, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
    (args.out / 'private-matches.json').write_bytes(private_flags)
    inventory_bytes = (json.dumps(records, indent=2) + '\n').encode('utf-8')
    (args.out / 'historical-object-inventory.json').write_bytes(inventory_bytes)
    summary = {
        'kind': 'prior_public_identity_removed_input_reuse_audit' if args.drop_generated_rid else 'prior_public_exact_input_reuse_audit',
        'source_commit': args.source_commit, 'generated_rid_removal_enabled': args.drop_generated_rid,
        'historical_roots': ['data', 'examples/results'], 'unique_historical_json_blobs': len(records),
        'current_tasks_file_sha256': hashlib.sha256(raw).hexdigest(), 'current_tasks_content_hash': digest(tasks),
        'current_sources_by_split': dict(Counter(task['split'] for task in tasks)),
        'current_generated_rid_fields_removed': sum(
            isinstance(row.get('rid'), str) and bool(GENERATED_RID.fullmatch(row['rid']))
            for task in tasks for rows in task['inputs'].values() for row in rows) if args.drop_generated_rid else 0,
        'coverage': dict(totals), 'match_records': len(flags),
        'matching_current_sources_by_mode_and_split': {mode + '/' + split: len(sources) for (mode, split), sources in sorted(matched.items())},
        'private_matches_sha256': hashlib.sha256(private_flags).hexdigest(),
        'historical_inventory_sha256': hashlib.sha256(inventory_bytes).hexdigest(),
        'driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'current_gold_read': False, 'current_model_predictions_read': False, 'candidate_changed': False,
        'historical_output_bearing_json_parsed': True,
        'semantic_independence_proven': False, 'm2_complete': False,
        'limitations': [
            'Only objects reachable from the named commit in the two recorded roots; not unreachable commits, external/untracked assets or model pretraining data.',
            'A historical blob has one Git path alias; repeated identical bytes at multiple paths are not separate inputs.',
            'Recognizes inputs maps of file paths to lists of object rows and first decodable JSON objects in prompt fields only. Other formats remain unassessed.',
            'Three original exact modes retain all fields and values. Optional additional modes remove only rid strings matching [0-9a-f]{12}-[0-9]+-[0-9]+; all other fields, types, values and row order remain. No semantic, arbitrary identity/field-alias renaming or near-duplicate inference.',
            'Removing paths or file boundaries may flag shared inputs with different requested operations; matches are reuse risks, not proof of answer leakage.',
            'Public historical JSON is parsed structurally, but answer/output fields are excluded from comparisons; current heldout gold is never opened.',
            'Zero matches does not resolve previously recorded within-dataset normalized near neighbors or establish statistical independence, licensing or broad exclusion.',
        ],
    }
    (args.out / 'summary.json').write_bytes((json.dumps(summary, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
