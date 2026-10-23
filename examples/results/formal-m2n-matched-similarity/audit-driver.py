"""Descriptive input similarity audit; no reference, gold or model outputs."""
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

SOURCE=Path('/root/autodl-tmp/Jerry-formal-v2-20261022')
DATA=Path('/root/autodl-tmp/procedural-matched-test-candidates-20261023')
OUT=Path('/root/autodl-tmp/matched-test-similarity-20261023')
sys.path.insert(0,str(SOURCE))
from intentlab.core import canonical, digest

def normalize(task):
    operation=deepcopy(task['spec']['operation'])
    fields={key:operation[key] for key in ('field','where_field','group_field','value_field') if key in operation}
    for key in fields:
        operation[key]='$'+key
    if 'fields' in operation:
        operation['fields']=['$identity' if f=='rid' else f for f in operation['fields']]
    tokens=[]
    for path in sorted(task['inputs']):
        for row in task['inputs'][path]:
            values={key:{'present':name in row, 'value':row.get(name)} for key,name in fields.items()}
            # Preserve the validity pattern even when identity/tag values are
            # removed. Tags are present-only constraints, not operation values.
            values['missing_required_count']=sum(f not in row for f in task['spec']['required_fields'])
            tokens.append(canonical(values))
    return canonical(operation),tokens

def distance(left,right):
    previous=list(range(len(right)+1))
    for i,a in enumerate(left,1):
        current=[i]
        for j,b in enumerate(right,1):
            current.append(min(current[-1]+1,previous[j]+1,previous[j-1]+(a!=b)))
        previous=current
    return previous[-1]

def main():
    # Bound the core invariants independently of the research batch.
    assert distance(['x','y'],['x','z'])==1
    assert distance([],['x'])==1 and distance(['x'],['x'])==0
    assert canonical(True)!=canonical(1) and canonical(1)!=canonical(1.0)
    expected={'tasks.jsonl': '3adb95d02a0224b4b4078f237813c5f47d808e5055a637d2b7ce3a706c8c4c24'}
    path=DATA/'tasks.jsonl'
    assert hashlib.sha256(path.read_bytes()).hexdigest()==expected['tasks.jsonl']
    tasks=[json.loads(line) for line in path.read_text().splitlines()]
    assert len(tasks)==1050 and len({t['source_task_id'] for t in tasks})==1050
    groups=defaultdict(list)
    normalized={}
    for task in tasks:
        operation,tokens=normalize(task)
        normalized[task['id']]=(operation,tokens)
        groups[(task['family'],operation)].append(task)
    matrix=defaultdict(Counter)
    nearest={t['id']:1.0 for t in tasks}
    flags=[]
    for members in groups.values():
        for i,left in enumerate(members):
            for right in members[i+1:]:
                if left['split']==right['split']:
                    continue
                key=' / '.join(sorted([left['split'],right['split']]))
                a,b=normalized[left['id']][1],normalized[right['id']][1]
                d=distance(a,b)
                ratio=d/max(len(a),len(b),1)
                matrix[key]['same_operation_parameter_pairs']+=1
                matrix[key]['normalized_exact_pairs']+=d==0
                matrix[key]['within_25_percent_row_edits']+=ratio<=0.25
                nearest[left['id']]=min(nearest[left['id']],ratio)
                nearest[right['id']]=min(nearest[right['id']],ratio)
                if ratio<=0.25:
                    flags.append({'left':left['id'],'right':right['id'],'family':left['family'],
                                  'split_pair':key,'edit_distance':d,'normalized_distance':ratio})
    summary={'scope':'descriptive_structural_normalization_not_semantic_independence_proof',
        'input_tasks_sha256':expected['tasks.jsonl'],'source_tasks':len(tasks),'gold_read':False,
        'model_outputs_read':False,'task_content_used_for_model_selection':False,
        'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'normalization':'Remove identity values, tag values, file boundaries and paths; rename operation fields by role. Preserve typed operation values, operation parameters, concatenated row order and missing-required counts.',
        'threshold':{'normalized_levenshtein_row_distance':0.25,'purpose':'descriptive flags only; not an acceptance gate or estimated leakage probability'},
        'cross_split_pairs':{k:dict(v) for k,v in sorted(matrix.items())},
        'sources_with_flagged_cross_split_neighbor':len({f[k] for f in flags for k in ['left','right']}),
        'no_candidate_removed_or_reassigned':True,
        'limitations':['Conditional on shared operation parameters; no cross-family semantic matching.',
                      'Shared specification templates and generator logic remain even without duplicate row sequences.',
                      'Distinct split row counts can prevent exact matches by construction; zero exact matches does not establish independence.',
                      'All views of a source remain together; view count must not be treated as independent sample count.',
                      'Heldout public source contracts inspected only for data construction/isolation; no heldout gold or model scores accessed.']}
    OUT.mkdir(mode=0o700,exist_ok=False)
    (OUT/'driver.py').write_bytes(Path(__file__).read_bytes())
    for name,value in [('summary.json',summary),('private-flags.json',flags),('private-normalized-hashes.json',{k:digest(v) for k,v in normalized.items()})]:
        (OUT/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')
    print(json.dumps(summary,indent=2),flush=True)

if __name__=='__main__':
    main()
