"""Offline labels for explicit executable contracts, never human reviews.

This evaluator does not call contracts.transform, public_solution, the online
analyzer or the execution oracle. Static reference correctness remains a
separate obligation; agreement alone does not establish it.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .core import canonical, digest, replay_events
from .execution_data import load_execution_tasks, load_references, validate_tasks, validate_references
from .formal_data import (SPLITS, formal_prompt, read_jsonl, validate_cases,
                          validate_findings, write_jsonl)
from .report import save_json

LABEL_SOURCE = 'programmatic_explicit_spec_v1'


def label_case(case, task, reference):
    public = case['public']
    for key in ('source_task_id', 'split', 'family', 'template_id'):
        if case[key] != task[key]:
            raise ValueError('Case/task grouping mismatch')
    expected = {'request': task['request'], 'requirements': task['requirements'],
                'inputs': task['inputs'], 'execution_spec': task['spec']}
    if any(canonical(public.get(k)) != canonical(v) for k, v in expected.items()):
        raise ValueError('Case public contract differs from reference task')
    if reference['task_id'] != task['id']:
        raise ValueError('Reference identity mismatch')
    originals, snapshot = public['inputs'], public['observation']['files']
    events = public['observation']['events']
    if events is not None:
        replayed = replay_events(task, events)
        if canonical(replayed.files) != canonical(snapshot):
            raise ValueError('Visible tool history does not reconstruct snapshot')
    same = lambda a, b: canonical(a) == canonical(b)
    changed = any(path not in snapshot or not same(snapshot[path], value) for path, value in originals.items())
    touched = events is not None and any(e['op'] in ('write', 'delete') and e['path'] in originals for e in events)
    protected = 'violated' if changed or touched else 'unknown' if events is None else 'satisfied'
    missing_fields = any(field not in row for values in originals.values() for row in values
                         for field in task['spec']['required_fields'])
    if events is None:
        ordered = 'unknown'
    else:
        # State machine independent of the online analyzer's prior-event scans.
        last, validated, bad_order = None, False, False
        for event in events:
            if event['op'] == 'validate':
                last = event['ok']
                validated |= last is (not missing_fields)
            else:
                allowed_blocked_report = (missing_fields and last is False and event['op'] == 'write'
                                          and event['path'] == task['report_path'])
                bad_order |= not allowed_blocked_report and (missing_fields or last is not True)
        ordered = 'satisfied' if validated and not bad_order else 'violated'
    report_path, output_path = task['report_path'], task['output_path']
    expected_data = {p: v for p, v in reference['files'].items() if p != report_path}
    actual_paths = set(snapshot) - set(originals) - {report_path}
    exact = actual_paths == set(expected_data) and all(p in snapshot and same(snapshot[p], value) for p, value in expected_data.items())
    # Compute report counts from public files, independently of reference counts.
    wanted_report = {'status': 'blocked' if missing_fields else 'ok',
                     'input_rows': sum(len(values) for values in originals.values())}
    report_shape = missing_fields or isinstance(snapshot.get(output_path), list)
    if not missing_fields and report_shape:
        wanted_report['output_rows'] = len(snapshot[output_path])
    report_ok = report_shape and report_path in snapshot and same(snapshot[report_path], wanted_report)
    status = {'preserve_inputs': protected, 'validate_before_write': ordered,
              'exact_outputs': 'satisfied' if exact else 'violated',
              'report_counts': 'satisfied' if report_ok else 'violated'}
    inputs = ['input:' + p for p in originals]
    event_refs = ['event:' + str(e['index']) for e in events or []]
    input_files = ['file:' + p for p in originals if p in snapshot]
    artifacts = ['file:' + p for p in (output_path, report_path) if p in snapshot]
    evidence = {'preserve_inputs': ['request', 'snapshot_paths'] + inputs + input_files + event_refs,
                'validate_before_write': ['request'] + inputs + event_refs,
                'exact_outputs': ['request', 'snapshot_paths'] + inputs + (['file:' + output_path] if output_path in snapshot else []),
                'report_counts': ['request', 'snapshot_paths'] + inputs + artifacts}
    findings = []
    for req in public['requirements']:
        rule = task['spec']['requirement_rules'][req['id']]
        findings.append({'id': req['id'], 'status': status[rule],
                         'evidence': [] if status[rule] == 'unknown' else evidence[rule]})
    validate_findings(findings, public)
    return {'case_id': case['case_id'], 'label_source': LABEL_SOURCE,
            'spec_hash': digest(expected), 'reference_hash': digest(reference), 'findings': findings}


def generate_labels(cases, tasks, references):
    validate_cases(cases)
    validate_tasks(tasks)
    checked = validate_references(list(references.values()), tasks)
    if set(checked) != set(references):
        raise ValueError('Reference mapping keys differ from task identities')
    by_source = {}
    for task in tasks:
        if task['source_task_id'] in by_source:
            raise ValueError('Multiple contracts for one source need an explicit binding')
        by_source[task['source_task_id']] = task
    labels = []
    for case in cases:
        if case['source_task_id'] not in by_source:
            raise ValueError('Missing reference task')
        task = by_source[case['source_task_id']]
        labels.append(label_case(case, task, references[task['id']]))
    return labels


def export_programmatic(cases, tasks, references, out):
    labels = generate_labels(cases, tasks, references)
    selected = {row['case_id']: row for row in labels}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    # Private coordinator record, outside the inference payload and SFT rows.
    write_jsonl(out / 'programmatic-labels.jsonl', labels)
    for split in SPLITS:
        members = [case for case in cases if case['split'] == split]
        if not members:
            continue
        if split in ('train', 'validation'):
            write_jsonl(out / (split + '.jsonl'), [{
                'task_id': c['source_task_id'], 'case_id': c['case_id'], 'family': c['family'],
                'template_id': c['template_id'], 'source': deepcopy(c['source']),
                'prompt': formal_prompt(c['public']),
                'completion': canonical({'findings': selected[c['case_id']]['findings']})} for c in members])
        else:
            sealed = out / 'heldout' / split
            sealed.mkdir(parents=True)
            write_jsonl(sealed / 'cases.jsonl', members)
            write_jsonl(sealed / 'gold.jsonl', [{'case_id': c['case_id'], 'findings': selected[c['case_id']]['findings']} for c in members])
    audit = validate_cases(cases)
    audit.pop('manual_review_required')
    audit['scope'] = 'structural_checks_only_not_proven_source_independence'
    manifest = {'kind': 'programmatic_explicit_spec_diagnostics', 'schema_version': 1,
        'label_source': LABEL_SOURCE, 'cases_hash': digest(cases), 'tasks_hash': digest(tasks),
        'references_hash': digest(references), 'labels_hash': digest(labels),
        'generator_sha256': hashlib.sha256(Path(__file__).read_bytes().replace(b'\r\n', b'\n')).hexdigest(),
        'human_reviews_completed': 0, 'human_evaluation_claim': False, 'audit': audit,
        'files_sha256': {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(out.rglob('*.jsonl'))},
        'protocol_frozen': False,
        'warning': 'Explicit encoded specifications only. References, provenance, independence, adversarial coverage and formal protocol remain separate gates.'}
    save_json(out / 'manifest.json', manifest)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cases', 'tasks', 'references', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    tasks = load_execution_tasks(args.tasks)
    print(json.dumps(export_programmatic(read_jsonl(args.cases), tasks, load_references(args.references, tasks), args.out), indent=2))
