"""Coordinator-only replayable evidence for schema-v3 programmatic labels."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path

from .core import canonical, digest
from .contract_fault_audit import audit_faults
from .contract_perturbations import perturbations
from .execution_data import load_execution_tasks, load_references
from .formal_data import read_jsonl, validate_cases
from .programmatic_labels import generate_labels
from .spec_reference import verify_references


SCOPE = 'encoded_specifications_only_no_human_evaluation'
CODE_FILES = ('programmatic_labels.py', 'spec_reference.py', 'contract_perturbations.py', 'contract_fault_audit.py', 'programmatic_protocol.py')


def validation_record(cases, tasks, references):
    labels = generate_labels(cases, tasks, references)
    development = [t for t in tasks if t['split'] in ('train', 'validation')]
    blocked = [t['id'] for t in development if any(field not in row for rows in t['inputs'].values() for row in rows for field in t['spec']['required_fields'])]
    if not development:
        raise ValueError('Development tasks required for independent fault/mutation evidence')
    refs = {t['id']: references[t['id']] for t in development}
    faults, expectations = perturbations(development, refs)
    return {'kind': 'programmatic_contract_validation', 'schema_version': 1, 'claims_scope': SCOPE,
        'cases_hash': digest(cases), 'tasks_hash': digest(tasks), 'references_hash': digest(references),
        'labels_hash': digest(labels), 'reference_check': verify_references(tasks, references),
        'fault_audit': audit_faults(faults, expectations, development, refs),
        'blocked_development_tasks_not_fault_tested': [],
        'blocked_development_tasks_fault_tested': blocked,
        'implementation_sha256': {name: hashlib.sha256((Path(__file__).parent/name).read_text(encoding='utf-8').encode()).hexdigest() for name in CODE_FILES}}


def source_record(cases):
    validate_cases(cases)
    groups = defaultdict(list)
    fingerprints = {}
    for case in cases:
        groups[case['source_task_id']].append(case)
        # Exact original input reuse across splits is forbidden even when an
        # author changes the request, task ID, template ID or operation name.
        fingerprint = digest(case['public']['inputs'])
        identity = {'split': case['split'], 'source_task_id': case['source_task_id']}
        if fingerprint in fingerprints and fingerprints[fingerprint] != identity:
            raise ValueError('Original input payload reused across programmatic source/split groups')
        fingerprints[fingerprint] = identity
    records = {}
    for source, members in groups.items():
        if len({c['source']['origin'] for c in members}) != 1 or len({c['source']['license'] for c in members}) != 1:
            raise ValueError('Source provenance differs across views')
        records[source] = {'split': members[0]['split'], 'family': members[0]['family'],
            'template_id': members[0]['template_id'], 'origin': members[0]['source']['origin'],
            'license': members[0]['source']['license'],
            'public_contract_hashes': sorted({digest({k: v for k, v in c['public'].items() if k != 'observation'}) for c in members})}
    return {'kind': 'programmatic_source_isolation', 'schema_version': 1, 'cases_hash': digest(cases),
        'claims_scope': SCOPE, 'source_groups': records, 'exact_input_fingerprints': fingerprints,
        'semantic_independence_proven': False, 'human_evaluation_claim': False,
        'warning': 'Checks declared source/template grouping and exact payload reuse; not proof of semantic independence, licensing or statistical adequacy.'}


def validate_source_record(cases, record):
    if canonical(record) != canonical(source_record(cases)):
        raise ValueError('Programmatic source-isolation evidence differs from replay')
    return {'kind': 'validated_programmatic_source_isolation', 'schema_version': 1,
        'cases_hash': digest(cases), 'source_groups': len(record['source_groups']), 'case_count': len(cases),
        'record_hash': digest(record), 'claims_scope': SCOPE, 'human_evaluation_claim': False}


def resolve_dataset(data, validation_path, formal=False):
    cases = read_jsonl(data['cases'])
    tasks = load_execution_tasks(data['tasks'])
    references = load_references(data['references'], tasks)
    if {t['source_task_id'] for t in tasks} != {c['source_task_id'] for c in cases}:
        raise ValueError('Programmatic task/source case coverage mismatch')
    labels = generate_labels(cases, tasks, references)
    if labels != read_jsonl(data['labels']):
        raise ValueError('Programmatic labels differ from independent regeneration')
    record = json.loads(Path(validation_path).read_text(encoding='utf-8'))
    expected = validation_record(cases, tasks, references)
    if canonical(record) != canonical(expected):
        raise ValueError('Programmatic validation evidence differs from replay')
    if formal and (record['blocked_development_tasks_not_fault_tested'] or record['fault_audit']['mutants_detected'] != record['fault_audit']['mutants_total']):
        raise ValueError('Formal programmatic fault/mutation coverage incomplete')
    manifest = json.loads((Path(data['export'])/'manifest.json').read_text(encoding='utf-8'))
    for key in ('cases_hash', 'tasks_hash', 'references_hash', 'labels_hash'):
        if manifest.get(key) != record[key]:
            raise ValueError('Programmatic export identity mismatch: ' + key)
    if manifest.get('kind') != 'programmatic_explicit_spec_diagnostics' or manifest.get('human_evaluation_claim') is not False:
        raise ValueError('Programmatic export must not claim human evaluation')
    if manifest.get('human_reviews_completed') != 0 or manifest.get('protocol_frozen') is not False:
        raise ValueError('Invalid programmatic export declaration')
    if manifest.get('generator_sha256') != record['implementation_sha256']['programmatic_labels.py']:
        raise ValueError('Programmatic label implementation changed')
    return {r['case_id']: {f['id']: f for f in r['findings']} for r in labels}


if __name__ == '__main__':
    import argparse
    from .report import save_json
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('cases', 'tasks', 'references', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--execution-tasks', type=Path)
    parser.add_argument('--execution-references', type=Path)
    args = parser.parse_args()
    if bool(args.execution_tasks) != bool(args.execution_references):
        parser.error('Both execution paths required together')
    args.out.mkdir(parents=True, exist_ok=False)
    save_json(args.out/'preparation-status.json', {'status': 'running', 'formal_ready': False})
    try:
        cases = read_jsonl(args.cases)
        tasks = load_execution_tasks(args.tasks)
        references = load_references(args.references, tasks)
        record = validation_record(cases, tasks, references)
        isolation = source_record(cases)
        save_json(args.out/'programmatic-validation.json', record)
        save_json(args.out/'source-isolation.json', isolation)
        if args.execution_tasks:
            execution = load_execution_tasks(args.execution_tasks)
            if any(t['split'] not in ('test', 'ood') for t in execution):
                raise ValueError('Execution audit must bind only heldout tasks')
            save_json(args.out/'execution-reference-check.json', verify_references(execution, load_references(args.execution_references, execution)))
        save_json(args.out/'preparation-status.json', {'status': 'completed', 'formal_ready': False,
            'human_evaluation_claim': False, 'cases': len(cases), 'reference_tasks': len(tasks),
            'warning': 'Evidence preparation only; other formal gates remain.'})
    except Exception as exc:
        save_json(args.out/'preparation-status.json', {'status': 'failed', 'formal_ready': False,
            'error_type': type(exc).__name__, 'error': str(exc)})
        raise
    print(json.dumps({'prepared': True, 'cases': len(cases), 'tasks': len(tasks), 'formal_ready': False}))
