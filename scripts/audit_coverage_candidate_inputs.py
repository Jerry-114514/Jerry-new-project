"""CPU-only candidate overlap and declared repair-root structure audit.

Inputs are private source contracts, never model predictions. Does not remove,
resample or reassign a task. Only the aggregate summary is publishable.
"""
import argparse
from collections import Counter,defaultdict
import hashlib
import itertools
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from intentlab.core import digest
from intentlab.formal_data import read_jsonl
from intentlab.execution_data import validate_tasks
from postformal_evidence_support import BoundArchive


def independent_repairable_roots(task):
    """Graph antichain of the two declared file-result repairable rule kinds.

    Preserve-inputs and validate-before-write violations in a trusted complete
    history cannot be erased by later writes. This is a declared graph check,
    not proof that an arbitrary model candidate is or is not repairable.
    """
    rules=task['spec']['requirement_rules'];graph=task['spec']['dependencies']
    if set(rules.values())!={'preserve_inputs','validate_before_write','exact_outputs','report_counts'}:
        raise ValueError('Unexpected rule universe: repairability classification requires review')
    nodes=[rid for rid,rule in rules.items() if rule in ('exact_outputs','report_counts')]
    reach={}
    for root in nodes:
        seen=set();pending=list(graph[root])
        while pending:
            node=pending.pop()
            if node not in seen:seen.add(node);pending.extend(graph[node])
        reach[root]=seen
    return max((len(group) for n in range(len(nodes)+1) for group in itertools.combinations(nodes,n)
                if all(b not in reach[a] and a not in reach[b] for a,b in itertools.combinations(group,2))),default=0)


def build(candidate,expected_summary_sha,old_archive,old_sha,out):
    candidate,out=Path(candidate),Path(out)
    if out.exists():raise FileExistsError('Preserve earlier audit; choose a fresh directory')
    raw=(candidate/'summary.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_summary_sha:raise ValueError('Candidate binding mismatch')
    expected=json.loads(raw);tasks=read_jsonl(candidate/'tasks.jsonl');validate_tasks(tasks)
    if digest(tasks)!=expected['tasks_hash']:raise ValueError('Task contracts differ from candidate receipt')
    with BoundArchive(old_archive,old_sha) as a:
        old_tasks=a.rows('dataset/tasks.jsonl');a.verify_outer()
    driver=ROOT/'examples/results/formal-m2n-matched-similarity/audit-driver.py'
    text=driver.read_text(encoding='utf-8')
    if hashlib.sha256(text.encode()).hexdigest()!='18511b4563a33141078f16887dae48d6f4d3b4a6706bbc4ee6abad50e7a0bcd7':
        raise ValueError('Original descriptive normalization helper changed')
    namespace={'__file__':str(driver),'__name__':'fixed_overlap_helpers'}
    exec(compile(text.split('def main():')[0],str(driver),'exec'),namespace)
    normalize,distance=namespace['normalize'],namespace['distance']
    groups=defaultdict(list)
    for task in tasks:
        operation,rows=normalize(task);groups[(task['family'],operation)].append((task,rows))
    matrix=defaultdict(Counter);flags=[]
    for group in groups.values():
        for (a,x),(b,y) in itertools.combinations(group,2):
            if a['split']==b['split']:continue
            key=' / '.join(sorted((a['split'],b['split'])))
            d=distance(x,y);ratio=d/max(len(x),len(y),1)
            matrix[key]['same_operation_parameter_pairs']+=1
            matrix[key]['normalized_exact_pairs']+=d==0
            matrix[key]['within_25_percent_row_edits']+=ratio<=.25
            if ratio<=.25:flags.append({'left':a['source_task_id'],'right':b['source_task_id'],'split_pair':key,'distance':ratio})
    signature=lambda t:digest({k:v for k,v in t.items() if k not in {'id','source_task_id','split','template_id','source'}})
    old_ids={t['source_task_id'] for t in old_tasks};old_signatures={signature(t) for t in old_tasks}
    fresh=[t for t in tasks if t['split'] in ('test','ood')]
    root_counts=Counter(independent_repairable_roots(t) for t in tasks)
    summary={'kind':'prospective_candidate_input_risk_audit','source_contracts':len(tasks),
        'new_heldout_sources':len(fresh),'v1_source_ids_reused_by_new_heldout':sum(t['source_task_id'] in old_ids for t in fresh),
        'v1_exact_operational_contract_matches_by_new_heldout':sum(signature(t) in old_signatures for t in fresh),
        'cross_split_normalized_pairs':{k:dict(v) for k,v in sorted(matrix.items())},
        'declared_repairable_root_antichain_counts':dict(root_counts),
        'contracts_with_two_independent_declared_repairable_roots':sum(n for k,n in root_counts.items() if k>=2),
        'threshold':.25,'threshold_role':'descriptive flags only; no removal or resampling',
        'model_outputs_read':False,'gold_read':False,'task_selection_based_on_model_outcomes':False,
        'candidate_changed':False,'all_previously_public_assets_excluded':False,
        'limitations':['Normalization removes identity/tag values and paths that may affect outputs; exact flags do not establish answer leakage.',
            'Shared generator, templates and cross-family semantic overlap are not excluded.',
            'Exact V1 contract exclusion is not exclusion of every historical/public semantic variant.',
            'Graph antichain counts classify the two encoded result rules; they do not measure actor capability or predict model findings.']}
    out.mkdir(parents=True,exist_ok=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n',encoding='utf-8',newline='\n')
    (out/'private-flags.json').write_text(json.dumps(flags,indent=2)+'\n',encoding='utf-8',newline='\n')
    return summary


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('candidate','v1-scientific-archive','out'):p.add_argument('--'+name,type=Path,required=True)
    for name in ('candidate-summary-sha256','v1-scientific-sha256'):p.add_argument('--'+name,required=True)
    a=p.parse_args();print(json.dumps(build(a.candidate,a.candidate_summary_sha256,a.v1_scientific_archive,a.v1_scientific_sha256,a.out)))
