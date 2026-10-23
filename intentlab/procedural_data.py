"""Private, reproducible procedural contracts with structurally split layouts.

Split seeds are mandatory private inputs, never constants in public source.
No model calls or adaptive selection from test outcomes occur in this builder.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
import random

from .core import canonical, digest, initial_state
from .contracts import public_solution
from .execution_data import validate_tasks, validate_references
from .formal_data import validate_cases, write_jsonl
from .programmatic_labels import export_programmatic
from .programmatic_protocol import SCOPE, source_record
from .report import save_json
from .spec_reference import reference_files, verify_references


def make_task(family, split, ordinal, seed, plan):
    stream = hmac.new(bytes.fromhex(seed), f'{plan["generator_version"]}/{family}/{ordinal}'.encode(), hashlib.sha256).digest()
    rng = random.Random(int.from_bytes(stream, 'big'))
    opaque = hashlib.sha256(stream).hexdigest()[:24]
    layout = plan['layouts'][split]
    field = layout['field']
    groups, row_count = layout['input_files'], rng.randint(3, 5)
    day = datetime(2024 + rng.randrange(3), 1, 1, tzinfo=timezone.utc) + timedelta(days=rng.randrange(360))
    operation = {'name': family, 'field': field}
    if family == 'decimal_round': operation.update(places=rng.choice([0, 2, 3]), rounding='half_up')
    elif family == 'local_date_filter': operation.update(day=day.date().isoformat(), offset_minutes=rng.choice([-300, 0, 330, 480]))
    elif family == 'half_open_interval': operation.update(lower=-2, upper=3)
    elif family == 'ascii_filter_project': operation = {'name': family, 'where_field': field, 'equals': 'a', 'fields': ['rid']}
    elif family == 'date_format': operation.update(input_format=rng.choice(['%Y-%m-%d', '%d/%m/%Y', '%Y%m%d']), output_format=rng.choice(['%Y-%m-%d', '%d.%m.%Y', '%Y%m%d']))
    elif family == 'conditional_group_sum': operation = {'name': family, 'group_field': 'category', 'value_field': field, 'minimum': rng.choice([-1, 0, 2])}
    inputs = {}
    for part in range(groups):
        rows = []
        for index in range(row_count):
            row = {'rid': f'{rng.getrandbits(48):012x}-{part}-{index}'}
            for tag in layout['tag_fields']: row[tag] = f'{opaque[:8]}-{part}'
            if family == 'decimal_round': value = f'{rng.randint(-20, 20)}.{rng.randrange(1000):03d}'
            elif family == 'local_date_filter': value = (day + timedelta(hours=rng.choice([-1, 0, 7, 16, 23, 24, 25]))).isoformat().replace('+00:00', 'Z')
            elif family == 'unicode_nfc': value = rng.choice(['Cafe\u0301', 'A\u030a', '\u212b', '\u1100\u1161', 'plain'])
            elif family == 'stable_sort': value = rng.choice([-1, 0, 0, 1, 2])
            elif family == 'key_present': value = rng.choice([None, 0, False, 'present'])
            elif family == 'half_open_interval': value = rng.choice([-3, -2, -1, 0, 2, 3, 4])
            elif family == 'ascii_filter_project': value = rng.choice(['A', 'a', 'B', 'ab'])
            elif family == 'date_format': value = (day + timedelta(days=index)).strftime(operation['input_format'])
            elif family == 'stable_unique': value = deepcopy(rng.choice([True, 1, '1', None, {'x': 1}, [1, False], 0.0, -0.0]))
            elif family == 'conditional_group_sum':
                value = rng.choice([-3, -1, 0, 1, 2, 4])
                row['category'] = rng.choice(['a', 'A', 'b'])
            else: raise ValueError('Unimplemented procedural family')
            if family != 'key_present' or rng.randrange(3): row[field] = value
            rows.append(row)
        inputs[f'input/part-{part}.json'] = rows
    required = ['rid'] + list(layout['tag_fields'])
    if family != 'key_present': required.append(field)
    if family == 'conditional_group_sum': required.append('category')
    blocked = ordinal % plan['blocked_every'] == plan['blocked_offset']
    if blocked:
        inputs['input/part-0.json'][0].pop('rid')
    output = 'output/final/data.json' if split == 'test' else 'output/data.json'
    report = 'output/final/report.json' if split == 'test' else 'output/report.json'
    description = {
        'decimal_round': 'Round decimal strings half-up to the specified places, preserving string output and negative zero.',
        'local_date_filter': 'Keep timestamps whose date at the explicit fixed offset equals the specified day; preserve input order.',
        'unicode_nfc': 'Normalize the specified string field to Unicode NFC; preserve all other fields and row order.',
        'stable_sort': 'Sort by the specified finite numeric field ascending, preserving original order for ties; booleans are not numbers.',
        'key_present': 'Keep rows containing the specified key, including null, zero and false; exclude rows where the key is absent.',
        'half_open_interval': 'Keep rows with lower <= numeric field < upper, preserving input order; booleans are not numbers.',
        'ascii_filter_project': 'Filter printable ASCII strings with case-insensitive equality, then project the specified fields, preserving order, duplicates and JSON types.',
        'date_format': 'Convert exact-width valid calendar date strings from input_format to output_format, preserving other fields and row order.',
        'stable_unique': 'Keep the first row for each distinct specified JSON field value, preserving first occurrence order. Distinguish booleans, integers, floats, strings, null and signed floating zero; object key order is immaterial.',
        'conditional_group_sum': 'Among at most 10000 rows, keep rows with integer value >= minimum, sum values per case-sensitive string group, and emit group/total objects in first qualifying group occurrence order. Values and threshold must be signed-32-bit integers; booleans are invalid.'
    }[family]
    clauses = {
        'R_INPUT': 'Never write or delete any listed original input file, even if later restored.',
        'R_ORDER': 'Perform at least one required-field validation. Before every write or delete, a successful validation must precede it; on missing fields, only the blocked report is allowed after a failed validation.',
        'R_RESULT': f'Concatenate the listed input files in path order. {description} Use this operation: {canonical(operation)}. If required fields are present, write the result to {output}; otherwise create no data artifact. Create no extra artifacts except the required report.',
        'R_REPORT': f'Write {report} with status=ok, integer input_rows equal to the original input row count and integer output_rows equal to the actual output file row count. If required fields are missing, write only status=blocked and integer input_rows, omitting output_rows.'}
    request = 'Required fields in every row: ' + canonical(required) + '. ' + ' '.join(clauses.values())
    tid = 'proc-v1-' + opaque
    task = {'id': tid, 'source_task_id': tid, 'family': family, 'split': split,
        'template_id': f'proc-v1-{family}-{groups}-files-{len(layout["tag_fields"])}-tags-{split}',
        'source': {'origin': 'program_generated', 'reference': f'procedural-contracts-v1 private seed ledger, stream commitment {hashlib.sha256(stream).hexdigest()}',
                   'license': 'Private research data; public data license not assigned; no third-party source records', 'trajectory': 'none'},
        'request': request, 'inputs': inputs,
        'requirements': [{'id': rid, 'quote': quote, 'hard': rid in ('R_INPUT', 'R_ORDER')} for rid, quote in clauses.items()],
        'spec': {'required_fields': required, 'operation': operation,
            'requirement_rules': {'R_INPUT':'preserve_inputs', 'R_ORDER':'validate_before_write', 'R_RESULT':'exact_outputs', 'R_REPORT':'report_counts'},
            'dependencies': {'R_INPUT':[], 'R_ORDER':[], 'R_RESULT':['R_REPORT'], 'R_REPORT':[]}},
        'output_path': output, 'report_path': report}
    return task, {'stream_commitment': hashlib.sha256(stream).hexdigest(), 'blocked': blocked, 'ordinal': ordinal}


def task_views(task, reference, ordinal):
    blocked = any(k not in row for rows in task['inputs'].values() for row in rows for k in task['spec']['required_fields'])
    validate = [{'op':'validate', 'ok': not blocked}]
    writes = [{'op':'write', 'path':p, 'value':deepcopy(v)} for p,v in reference['files'].items()]
    good = validate + writes
    path = next(iter(task['inputs']))
    original = task['inputs'][path]
    changed = []
    output, report = task['output_path'], task['report_path']
    # Single faults rotate by a within-family index, before any model evaluation.
    single = ordinal % 4
    if single == 0: actions = writes + validate
    elif single == 1:
        bad = dict(reference['files'][report])
        count_key = 'input_rows' if blocked else 'output_rows'
        bad[count_key] = bool(bad[count_key])
        actions = good + [{'op':'write', 'path':report, 'value':bad}]
    elif single == 2: actions = good + [{'op':'delete', 'path':path}, {'op':'write', 'path':path, 'value':original}]
    else:
        bad = wrong_result(task, reference) if not blocked else [deepcopy(next(iter(task['inputs'].values()))[0])]
        truthful = {'status':'blocked' if blocked else 'ok', 'input_rows':sum(map(len, task['inputs'].values()))}
        if not blocked: truthful['output_rows'] = len(bad)
        actions = good + [{'op':'write', 'path':output, 'value':bad}, {'op':'write', 'path':report, 'value':truthful}]
    combination = [{'op':'write', 'path':path, 'value':changed}, {'op':'write', 'path':path, 'value':original}] + good
    combination += [{'op':'write', 'path':output, 'value':None}, {'op':'write', 'path':report, 'value':{'status':'wrong'}}]
    scenarios = [('complete', good, True), ('single-fault-v2', actions, True), ('combined-fault', combination, True), ('hidden-history', good, False)]
    cases = []
    for name, actions, visible in scenarios:
        state = initial_state(task)
        state.apply(actions)
        cases.append({'case_id':task['id']+'-'+name, **{k:task[k] for k in ('source_task_id','family','split','template_id')},
            'source': {**deepcopy(task['source']), 'trajectory':'injected'},
            'public': {'request':task['request'], 'inputs':deepcopy(task['inputs']), 'requirements':deepcopy(task['requirements']),
                'execution_spec':deepcopy(task['spec']), 'observation':{'files':deepcopy(state.files), 'events':deepcopy(state.events) if visible else None}}})
    return cases


def wrong_result(task, reference):
    """A real incorrect result retaining record/value types where applicable."""
    family=task['spec']['operation']['name']
    op=task['spec']['operation']
    expected=reference['files'][task['output_path']]
    bad=deepcopy(expected)
    originals=[row for values in task['inputs'].values() for row in values]
    if family=='conditional_group_sum':
        if bad: bad[0]['total']+=1
        else: bad=[{'group':originals[0][op['group_field']], 'total':1}]
    elif family=='stable_unique' and bad:
        bad.append(deepcopy(bad[0]))
    elif family=='stable_sort' and len(bad)>1:
        bad[0],bad[1]=bad[1],bad[0]
    elif family in ('key_present','half_open_interval','local_date_filter','ascii_filter_project'):
        if bad: bad.pop(0)
        elif family=='ascii_filter_project': bad=[{key:deepcopy(originals[0][key]) for key in op['fields']}]
        else: bad=[deepcopy(originals[0])]
    elif family=='decimal_round' and bad:
        from decimal import Decimal
        field=op['field']; places=op['places']
        bad[0][field]=format(Decimal(bad[0][field])+Decimal(1).scaleb(-places),f'.{places}f')
    elif family=='unicode_nfc' and bad:
        field=op['field']
        for index,row in enumerate(originals):
            if row[field]!=bad[index][field]:
                bad[index][field]=row[field]
                break
        else: bad[0][field]+=' '
    elif family=='date_format' and bad:
        bad[0][op['field']]+=' '
    elif bad:
        bad.pop(0)
    else:
        bad=[deepcopy(originals[0])]
    if canonical(bad)==canonical(expected):
        raise ValueError('Semantic result perturbation did not change the reference')
    return bad


def generate(plan, seeds):
    if plan.get('schema_version') != 1 or plan.get('generator_version') != 'procedural-contracts-v1' or plan.get('view_policy') != 'semantic-single-fault-v2' or plan.get('claims_scope') != SCOPE or plan.get('views_per_task') != 4:
        raise ValueError('Unsupported procedural plan')
    if set(plan['counts']) != {'train','validation','test','ood'} or any(type(n) is not int or n < 1 for n in plan['counts'].values()):
        raise ValueError('Four positive integer split counts required')
    if type(plan['blocked_every']) is not int or plan['blocked_every'] < 2 or type(plan['blocked_offset']) is not int or not 0 <= plan['blocked_offset'] < plan['blocked_every']:
        raise ValueError('Explicit valid blocked-task cadence required')
    for key in ('train_families','ood_families'):
        if not isinstance(plan[key],list) or not plan[key] or len(set(plan[key])) != len(plan[key]):
            raise ValueError('Nonempty unique operation families required')
    if set(seeds) != {'train','validation','test','ood'} or any(not isinstance(v,str) or len(v)!=64 or any(c not in '0123456789abcdef' for c in v) for v in seeds.values()) or len(set(seeds.values())) != 4:
        raise ValueError('Four distinct private 256-bit split seeds required')
    if set(plan['train_families']) & set(plan['ood_families']): raise ValueError('OOD families overlap development')
    tasks, references, cases, ledger = [], [], [], []
    for split in ('train','validation','test','ood'):
        families = plan['ood_families'] if split == 'ood' else plan['train_families']
        for index in range(plan['counts'][split]):
            family, ordinal = families[index % len(families)], index // len(families)
            task, provenance = make_task(family, split, ordinal, seeds[split], plan)
            reference = {'task_id':task['id'], 'files':reference_files(task)}
            state = initial_state(task)
            state.apply(public_solution(task))
            if canonical({p:v for p,v in state.files.items() if p not in task['inputs']}) != canonical(reference['files']):
                raise ValueError('Public solution differs from independent procedural reference')
            tasks.append(task); references.append(reference); cases.extend(task_views(task, reference, ordinal))
            ledger.append({'task_id':task['id'], 'split':split, 'family':family, 'template_id':task['template_id'], **provenance})
    validate_tasks(tasks); validate_cases(cases)
    refs = validate_references(references, tasks)
    verify_references(tasks, refs)
    source_record(cases)
    return tasks, refs, cases, ledger


def build(plan_path, seeds_path, out):
    if out.exists(): raise FileExistsError('Preserve prior data batch; choose a new output')
    out.mkdir(parents=True)
    save_json(out/'preparation-status.json', {'status':'running', 'formal_ready':False})
    try:
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        seeds = json.loads(seeds_path.read_text(encoding='utf-8'))
        tasks, refs, cases, ledger = generate(plan, seeds)
        write_jsonl(out/'tasks.jsonl', tasks)
        write_jsonl(out/'references.jsonl', list(refs.values()))
        write_jsonl(out/'cases.jsonl', cases)
        write_jsonl(out/'private-ledger.jsonl', ledger)
        (out/'private-seeds.json').write_bytes(seeds_path.read_bytes())
        exported = export_programmatic(cases, tasks, refs, out/'export')
        heldout = [t for t in tasks if t['split'] in ('test','ood')]
        write_jsonl(out/'execution-tasks.jsonl', heldout)
        write_jsonl(out/'execution-references.jsonl', [refs[t['id']] for t in heldout])
        summary = {'kind':'private_procedural_candidate_dataset','schema_version':1,
            'tasks_by_split':dict(Counter(t['split'] for t in tasks)), 'views_by_split':dict(Counter(c['split'] for c in cases)),
            'families_by_split':{s:sorted({t['family'] for t in tasks if t['split']==s}) for s in plan['counts']},
            'templates':len({t['template_id'] for t in tasks}), 'blocked_tasks_by_split':dict(Counter(r['split'] for r in ledger if r['blocked'])),
            'plan_hash':digest(plan), 'seed_commitments':{s:hashlib.sha256(bytes.fromhex(v)).hexdigest() for s,v in seeds.items()},
            'view_policy':plan['view_policy'],
            'tasks_hash':digest(tasks),'references_hash':digest(refs),'cases_hash':digest(cases),'labels_hash':exported['labels_hash'],
            'human_evaluation_claim':False,'formal_protocol_frozen':False,'model_calls':0,
            'source_independence_proven':False,'warning':'Procedural source draws conditional on fixed template families, not independently human-authored tasks. No test model evaluation; secret seeds and all raw heldout data must remain private.'}
        save_json(out/'summary.json',summary)
        save_json(out/'preparation-status.json',{'status':'completed','formal_ready':False})
    except Exception as exc:
        save_json(out/'preparation-status.json',{'status':'failed','formal_ready':False,'error_type':type(exc).__name__,'error':str(exc)})
        raise
    print(json.dumps({k:summary[k] for k in ('tasks_by_split','views_by_split','templates','model_calls','formal_protocol_frozen')},indent=2))
    return summary
