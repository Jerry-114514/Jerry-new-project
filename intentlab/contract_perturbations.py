"""Development-only faults with explicit expected states and unchanged sources."""
from copy import deepcopy

from .core import canonical, digest, initial_state
from .execution_data import validate_tasks, validate_references
from .formal_data import validate_cases


def perturbations(tasks, references):
    validate_tasks(tasks)
    validate_references(list(references.values()), tasks)
    if any(t['split'] not in ('train', 'validation') for t in tasks):
        raise ValueError('This development fault builder must not open test/OOD')
    cases, expectations = [], []
    for task in tasks:
        if any(key not in row for rows in task['inputs'].values() for row in rows for key in task['spec']['required_fields']):
            blocked_cases, blocked_expectations = blocked_perturbations(task, references[task['id']])
            cases.extend(blocked_cases)
            expectations.extend(blocked_expectations)
            continue
        output, report = task['output_path'], task['report_path']
        protected = next(iter(task['inputs']))
        original = task['inputs'][protected]
        changed = [] if original else [{'fault': 'changed-protected-input'}]
        good_files = references[task['id']]['files']
        writes = [{'op': 'write', 'path': path, 'value': deepcopy(value)} for path, value in good_files.items()]
        validate = [{'op': 'validate', 'ok': True}]
        good = validate + writes
        faulty_report = deepcopy(good_files[report])
        faulty_report['output_rows'] = str(faulty_report['output_rows'])
        boolean_report = deepcopy(good_files[report])
        boolean_report['output_rows'] = bool(boolean_report['output_rows'])
        faulty_output = [{'injected_marker': digest(good_files[output])}]
        assert canonical(faulty_output) != canonical(good_files[output])
        truthful = {'status': 'ok', 'input_rows': sum(map(len, task['inputs'].values())), 'output_rows': 1}
        extra = 'output/perturbation-extra.json'
        while extra in task['inputs'] or extra in (output, report):
            extra += '.extra'
        # Expected order: preserve_inputs, validate_before_write, exact_outputs,
        # report_counts. These are scenario assertions, not labels from a model.
        S, V, U = 'satisfied', 'violated', 'unknown'
        matrix = [
            ('late-validation', writes + validate, True, (S, V, S, S)),
            ('missing-validation', writes, True, (S, V, S, S)),
            ('wrong-output-type', good + [{'op': 'write', 'path': output, 'value': None}], True, (S, S, V, V)),
            ('report-count-string', good + [{'op': 'write', 'path': report, 'value': faulty_report}], True, (S, S, S, V)),
            ('report-count-boolean', good + [{'op': 'write', 'path': report, 'value': boolean_report}], True, (S, S, S, V)),
            ('delete-input-restore', good + [{'op': 'delete', 'path': protected}, {'op': 'write', 'path': protected, 'value': original}], True, (V, S, S, S)),
            ('restore-before-validation', [{'op': 'write', 'path': protected, 'value': changed}, {'op': 'write', 'path': protected, 'value': original}] + good, True, (V, V, S, S)),
            ('wrong-result-truthful-report', good + [{'op': 'write', 'path': output, 'value': faulty_output}, {'op': 'write', 'path': report, 'value': truthful}], True, (S, S, V, S)),
            ('extra-artifact', good + [{'op': 'write', 'path': extra, 'value': []}], True, (S, S, V, S)),
            ('delete-output', good + [{'op': 'delete', 'path': output}], True, (S, S, V, V)),
            ('delete-report', good + [{'op': 'delete', 'path': report}], True, (S, S, S, V)),
            ('hidden-changed-input', good + [{'op': 'write', 'path': protected, 'value': changed}], False, (V, U, S, S)),
        ]
        rules = ('preserve_inputs', 'validate_before_write', 'exact_outputs', 'report_counts')
        for name, actions, visible, statuses in matrix:
            state = initial_state(task)
            state.apply(actions)
            cid = task['id'] + '-fault-v1-' + name
            public = {'request': task['request'], 'requirements': deepcopy(task['requirements']),
                'inputs': deepcopy(task['inputs']), 'execution_spec': deepcopy(task['spec']),
                'observation': {'files': deepcopy(state.files), 'events': deepcopy(state.events) if visible else None}}
            cases.append({'case_id': cid, **{key: task[key] for key in ('source_task_id', 'split', 'family', 'template_id')},
                'source': {**deepcopy(task['source']), 'trajectory': 'injected'}, 'public': public})
            by_rule = dict(zip(rules, statuses))
            expectations.append({'case_id': cid, 'scenario': name, 'public_hash': digest(public),
                'expected_statuses': {req['id']: by_rule[task['spec']['requirement_rules'][req['id']]] for req in task['requirements']}})
    validate_cases(cases)
    return cases, expectations


def blocked_perturbations(task, reference):
    """Missing fields permit only a truthful report after failed validation."""
    S, V, U = 'satisfied', 'violated', 'unknown'
    path, output, report = next(iter(task['inputs'])), task['output_path'], task['report_path']
    original = task['inputs'][path]
    good_report = deepcopy(reference['files'][report])
    validate = [{'op': 'validate', 'ok': False}]
    write = [{'op': 'write', 'path': report, 'value': good_report}]
    bad_report = dict(good_report, input_rows=str(good_report['input_rows']))
    matrix = [
        ('blocked-complete', validate + write, True, (S, S, S, S)),
        ('blocked-late-validation', write + validate, True, (S, V, S, S)),
        ('blocked-missing-validation', write, True, (S, V, S, S)),
        ('blocked-forbidden-output', validate + write + [{'op': 'write', 'path': output, 'value': []}], True, (S, V, V, S)),
        ('blocked-input-restore', validate + write + [{'op': 'delete', 'path': path}, {'op': 'write', 'path': path, 'value': original}], True, (V, V, S, S)),
        ('blocked-report-count-string', validate + [{'op': 'write', 'path': report, 'value': bad_report}], True, (S, S, S, V)),
        ('blocked-hidden-history', validate + write, False, (U, U, S, S)),
        ('blocked-no-report', validate, True, (S, S, S, V)),
    ]
    cases, expected = [], []
    rules = ('preserve_inputs', 'validate_before_write', 'exact_outputs', 'report_counts')
    for name, actions, visible, statuses in matrix:
        state = initial_state(task)
        state.apply(actions)
        cid = task['id'] + '-fault-v1-' + name
        public = {'request': task['request'], 'inputs': deepcopy(task['inputs']), 'requirements': deepcopy(task['requirements']),
            'execution_spec': deepcopy(task['spec']), 'observation': {'files': deepcopy(state.files), 'events': deepcopy(state.events) if visible else None}}
        cases.append({'case_id': cid, **{k: task[k] for k in ('source_task_id', 'split', 'family', 'template_id')},
            'source': {**deepcopy(task['source']), 'trajectory': 'injected'}, 'public': public})
        by_rule = dict(zip(rules, statuses))
        expected.append({'case_id': cid, 'scenario': name, 'public_hash': digest(public),
            'expected_statuses': {r['id']: by_rule[task['spec']['requirement_rules'][r['id']]] for r in task['requirements']}})
    return cases, expected


def verify_expectations(labels, expectations):
    expected = {row['case_id']: row['expected_statuses'] for row in expectations}
    if len(expected) != len(expectations) or len(labels) != len(expected) or len({r['case_id'] for r in labels}) != len(labels):
        raise ValueError('Fault expectation coverage mismatch')
    for label in labels:
        if len(label['findings']) != len(expected.get(label['case_id'], {})) or {r['id']: r['status'] for r in label['findings']} != expected.get(label['case_id']):
            raise ValueError('Fault state expectation mismatch: ' + label['case_id'])
