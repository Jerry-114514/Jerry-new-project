"""Rebuild this development report from raw traces; not confirmatory statistics."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.formal_eval import parse_prediction

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root', type=Path, default=Path('examples/results/formal-m1d-development'))
root = parser.parse_args().root
tasks = {row['id']: row for row in [json.loads(s) for s in (root/'inputs/tasks.jsonl').read_text(encoding='utf-8').splitlines()]}
conditions = {}
for guard in ('on', 'off'):
    directory = root/'final'/('guard-'+guard)
    conditions[guard] = json.loads((directory/'summary.json').read_text(encoding='utf-8'))
manifest = json.loads((root/'final/guard-on/manifest.json').read_text(encoding='utf-8'))
if manifest['redact_events']:
    raise ValueError('This descriptive comparison assumes fully visible history; hidden views need visibility-aware labels')
rows = [json.loads(s) for s in (root/'final/guard-on/runs.jsonl').read_text(encoding='utf-8').splitlines()]
rows = [row for row in rows if row['policy'] == 'fixed-full']
raw_errors = online_errors = strict = references_accepted = 0
task_details = []
for row in rows:
    task = tasks[row['task_id']]
    response = next(item for item in row['model_pool']['generations'] if item['role'] == 'analyzer')
    raw = parse_prediction(response['text'], task['requirements'])
    strict += 1
    references_accepted += not bool(row['analyzer_errors'])
    truth = row['initial_metrics']['requirements']
    target = {rid: 'satisfied' if value else 'violated' for rid, value in truth.items()}
    raw_count = sum(raw[rid]['status'] != status for rid, status in target.items())
    applied = {item['id']: item['status'] for item in row['history'][0]['findings']}
    applied_count = sum(applied[rid] != status for rid, status in target.items())
    raw_errors += raw_count
    online_errors += applied_count
    task_details.append({'task_id': row['task_id'], 'oracle_requirements': truth,
        'raw_status_errors': raw_count, 'online_gate_status_errors': applied_count,
        'analyzer_errors': row['analyzer_errors'], 'committed_paths': list(row['final_state']['files'])})
decomposition = {'kind': 'descriptive_development_error_decomposition',
    'reference_condition': 'guard-on/fixed-full', 'source_task_groups': 8,
    'strict_findings_schema_outputs': strict, 'online_reference_check_passed_outputs': references_accepted,
    'status_denominator': sum(len(task['requirements']) for task in tasks.values()),
    'raw_predicted_status_errors': raw_errors, 'online_gate_status_errors': online_errors,
    'task_details': task_details, 'warning': 'Static unreviewed development references; no human-confirmed generalization or independent duplicated samples.'}
(root/'error-decomposition.json').write_text(json.dumps(decomposition,indent=2)+'\n',encoding='utf-8')
runtime = json.loads((root/'runtime-identity.json').read_text(encoding='utf-8'))
runtime_matches = {name: hashlib.sha256(Path(name).read_text(encoding='utf-8').encode('utf-8')).hexdigest() == value
                   for name,value in runtime['source_normalized_utf8_sha256'].items() if name.startswith('intentlab/')}
assert all(runtime_matches.values()), runtime_matches
audit = json.loads((root/'replay-audit.json').read_text(encoding='utf-8'))
assert all(value['verified'] for value in audit.values())
report = {'kind': 'development_execution_engineering_verification', 'scope': 'development',
    'autodl_tests': 98, 'autodl_skipped': 0, 'local_tests': 98, 'local_skipped': 7,
    'final_runs': 32, 'all_replayed_runs_including_debugging': sum(value['runs'] for value in audit.values()),
    'source_task_groups': 8, 'human_reviews_completed': 0, 'formal_training_started': False,
    'runtime_module_content_matches_final_source': runtime_matches,
    'post_run_module_added': 'intentlab/execution_audit.py', 'conditions': conditions,
    'error_decomposition': {key: decomposition[key] for key in ('strict_findings_schema_outputs','online_reference_check_passed_outputs','status_denominator','raw_predicted_status_errors','online_gate_status_errors')},
    'files_sha256': {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in sorted(root.rglob('*')) if path.is_file() and path.name != 'verification.json'}}
(root/'verification.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
print(json.dumps({'runtime_modules': len(runtime_matches), 'replayed_runs': report['all_replayed_runs_including_debugging'],
                  'raw_status_errors': raw_errors, 'online_status_errors': online_errors}))
