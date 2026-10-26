"""Classify the two non-JSON probe sentinels in a frozen prior-public audit.

Sentinel text is fixture data, never an instruction to this audit. No current
contracts, gold, reference files, model outputs or weights are opened.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


KNOWN = {
    '7bc74b875ecd8731a9b90653dd0360f28134bc19': {
        'bytes': b'DO NOT READ: NO TEST DATA EXISTS FOR THIS HARDWARE PROBE\n',
        'root': 'examples/results/formal-m3a-context-probe',
        'generator': 'context_probe.py', 'result': 'train-1024/result.json',
        'test_path': 'data-1024/test.jsonl'},
    'e20895c35de19b1662865ffefff0f4dd02098550': {
        'bytes': b'DO NOT READ: no test data exists\n',
        'root': 'examples/results/formal-m3f-supervised-logits',
        'generator': 'probe-driver.py', 'result': 'train/result.json',
        'test_path': 'data/test.jsonl'},
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def classify(raw):
    for blob, record in KNOWN.items():
        if raw == record['bytes']:
            return blob
    raise ValueError('Unknown non-JSON content requires review; do not whitelist by prefix')


def audit(repo, commit, inventory_path, expected_inventory_sha, out):
    repo, out = Path(repo), Path(out)
    if out.exists():
        raise FileExistsError('Choose a fresh audit directory')
    if not re.fullmatch('[0-9a-f]{40}', commit) or not re.fullmatch('[0-9a-f]{64}', expected_inventory_sha):
        raise ValueError('Full immutable commit and inventory SHA256 required')
    inventory_raw = Path(inventory_path).read_bytes()
    if sha(inventory_raw) != expected_inventory_sha:
        raise ValueError('Historical inventory differs from its recorded SHA256')
    inventory = json.loads(inventory_raw)
    listing = subprocess.check_output(['git', '-c', 'core.quotepath=false', 'rev-list', '--objects', commit,
                                       '--', 'data', 'examples/results'], cwd=repo).decode('utf-8')
    reachable = {line.split(' ', 1)[0] for line in listing.splitlines()
                 if ' ' in line and line.endswith(('.json', '.jsonl'))}
    if len(inventory) != len(reachable) or {r['blob_sha'] for r in inventory} != reachable:
        raise ValueError('Inventory population differs from the frozen reachable JSON scope')
    unparsed = [r for r in inventory if r['parse_status'] != 'parsed']
    if len(unparsed) != len(KNOWN) or {r['blob_sha'] for r in unparsed} != set(KNOWN):
        raise ValueError('Unexpected unparsed objects require additional review')

    def frozen(path):
        return subprocess.check_output(['git', 'show', commit + ':' + path], cwd=repo)

    reviewed = []
    for record in sorted(unparsed, key=lambda r: r['blob_sha']):
        blob = record['blob_sha']
        spec = KNOWN[blob]
        raw = subprocess.check_output(['git', 'cat-file', 'blob', blob], cwd=repo)
        if classify(raw) != blob or len(raw) != record['bytes']:
            raise ValueError('Sentinel bytes or size differ')
        path = spec['root'] + '/' + spec['test_path']
        if frozen(path) != raw:
            raise ValueError('Frozen sentinel path no longer matches the reviewed object')
        try:
            json.loads(raw)
        except json.JSONDecodeError:
            pass
        else:
            raise ValueError('Sentinel must remain deliberately invalid JSON')
        generator_path = spec['root'] + '/' + spec['generator']
        generator = frozen(generator_path)
        literal = raw.decode('utf-8').replace('\n', '\\n')
        lines = [n for n, text in enumerate(generator.decode('utf-8').splitlines(), 1)
                 if 'write_text' in text and literal in text]
        if len(lines) != 1:
            raise ValueError('Exact sentinel construction line not found')
        result_path = spec['root'] + '/' + spec['result']
        result_raw = frozen(result_path)
        result = json.loads(result_raw)
        if result['completed'] is not True or result['test_deferred'] is not True or result['config']['defer_test'] is not True:
            raise ValueError('Recorded probe did not complete with deferred test')
        if spec['test_path'].startswith('data-1024'):
            evidence_path = spec['root'] + '/data-1024/manifest.json'
            evidence = frozen(evidence_path)
            manifest = json.loads(evidence)
            if manifest['test_file_is_deliberately_invalid'] is not True or manifest['files_sha256']['test.jsonl'] != sha(raw):
                raise ValueError('Probe manifest differs from sentinel bytes')
        else:
            evidence_path = spec['root'] + '/checksums.json'
            evidence = frozen(evidence_path)
            if json.loads(evidence)['data/test.jsonl'] != sha(raw):
                raise ValueError('Probe checksum differs from sentinel bytes')
        reviewed.append({'blob_sha': blob, 'historical_path_alias': record['path_alias'],
            'frozen_path': path, 'bytes': len(raw), 'sha256': sha(raw),
            'classification': 'deliberately_invalid_non_json_hardware_probe_sentinel',
            'generator_path': generator_path, 'generator_sha256': sha(generator), 'generator_line': lines[0],
            'recorded_result_path': result_path, 'recorded_result_sha256': sha(result_raw),
            'recorded_probe_completed': True, 'recorded_test_deferred': True,
            'sentinel_evidence_path': evidence_path, 'sentinel_evidence_sha256': sha(evidence),
            'input_rows_present': False, 'original_json_parse_failure_retained': True})
    for raw in (b'NOT JSON\n', KNOWN[next(iter(KNOWN))]['bytes'] + b'{"inputs":{}}\n'):
        try:
            classify(raw)
        except ValueError:
            continue
        raise ValueError('Unknown or extended sentinel content was incorrectly whitelisted')
    if Path(inventory_path).read_bytes() != inventory_raw:
        raise ValueError('Original inventory changed')
    summary = {'kind': 'frozen_historical_invalid_json_sentinel_review', 'schema_version': 1,
        'source_commit': commit, 'original_inventory_sha256': expected_inventory_sha,
        'historical_roots': ['data', 'examples/results'], 'historical_json_blobs': len(inventory),
        'original_parsed_json_blobs': sum(r['parse_status'] == 'parsed' for r in inventory),
        'parsed_blobs_without_recognized_inputs_not_reclassified': sum(r['parse_status'] == 'parsed' and
            not r['extraction_counts'].get('recognized_input_containers', 0) for r in inventory),
        'original_unparsed_json_blobs': len(unparsed), 'reviewed_non_json_sentinel_blobs': len(reviewed),
        'unexplained_unparsed_json_blobs_within_recorded_scope': 0, 'reviewed': reviewed,
        'exact_bytes_only_classification': True, 'two_unknown_or_extended_content_checks_rejected': True,
        'original_inventory_unchanged': True, 'driver_sha256': sha(Path(__file__).read_bytes()),
        'current_contracts_gold_references_or_model_outputs_opened': False, 'candidate_changed': False,
        'semantic_independence_proven': False, 'm2_complete': False,
        'limitations': [f'Only the two original parse failures in the fixed {len(inventory)}-object scope are resolved as documented sentinels.',
            'Parsed objects without recognized inputs and other asset formats are not further classified here.',
            'This does not extend semantic reuse detection or prove statistical independence, licensing or absence of pretraining contamination.',
            'Deferred-test result records are historical evidence for these probes, not a new model execution or universal access-isolation proof.']}
    out.mkdir(parents=True, exist_ok=False)
    (out / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--inventory', type=Path, required=True)
    parser.add_argument('--expected-inventory-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.repo, args.source_commit, args.inventory, args.expected_inventory_sha256, args.out)
    print(json.dumps({k: result[k] for k in ('historical_json_blobs', 'original_unparsed_json_blobs',
          'reviewed_non_json_sentinel_blobs', 'unexplained_unparsed_json_blobs_within_recorded_scope', 'm2_complete')}))
