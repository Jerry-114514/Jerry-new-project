"""Offline replay of completed development search; no model/test execution."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path.cwd()))
from intentlab.core import canonical, digest
from intentlab.formal_data import read_jsonl
from intentlab.formal_eval import paired_task_bootstrap, score_predictions

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root',type=Path,required=True)
parser.add_argument('--out',type=Path,required=True)
args=parser.parse_args()
root=args.root
plan=json.loads((root/'plan.json').read_text(encoding='utf-8'))
assert json.loads((root/'inference-status.json').read_text())['status']=='completed'
for name,expected in plan['file_sha256'].items():
    assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected,name
cases=read_jsonl(root/'validation-cases.jsonl')
gold=json.loads((root/'validation-gold.json').read_text(encoding='utf-8'))
expected_selection=json.loads((root/'scoring/selection.json').read_text())
assert digest(plan)==expected_selection['plan_hash']
scores={}
costs={}
for condition in plan['conditions']:
    directory=root/condition
    manifest=json.loads((directory/'manifest.json').read_text())
    assert manifest['status']=='completed' and manifest['case_count']==600
    for name,expected in manifest['file_sha256'].items():
        assert hashlib.sha256((directory/name).read_bytes()).hexdigest()==expected
    score=score_predictions(cases,gold,read_jsonl(directory/'predictions.jsonl'))
    score['evidence_semantic_support']='Not scored. Programmatic state labels only; no human validation claim.'
    assert canonical(score)==canonical(json.loads((root/'scoring'/(condition+'.json')).read_text()))
    scores[condition]=score
    calls=read_jsonl(directory/'calls.jsonl')
    assert len(calls)==600 and {c['case_id'] for c in calls}=={c['case_id'] for c in cases}
    measured={r['case_id']:r['prompt_tokens'] for r in json.loads((root/'lengths.json').read_text()) if r['condition']==condition}
    for call in calls:
        if call['status']=='generated':
            assert call['usage']['prompt_tokens']==measured[call['case_id']]
            assert call['budget']['charged_tokens']==sum(call['usage'].values())
    errors=Counter(error for row in score['records'] for error in set(row['parse_errors'].values()))
    costs[condition]={'wall_seconds':manifest['seconds'],'calls':len(calls),
        'generation_errors':sum(c['status']=='error' for c in calls),
        'known_prompt_tokens':sum(c['budget']['known_prompt_tokens'] for c in calls),
        'known_completion_tokens':sum(c['budget']['known_completion_tokens'] for c in calls),
        'charged_tokens':sum(c['budget']['charged_tokens'] for c in calls),
        'successful_calls_reaching_512_cap':sum(c.get('usage',{}).get('completion_tokens')==512 for c in calls),
        'parse_error_messages_by_case':dict(errors)}
chosen=min(['B3','B4'],key=lambda n:(scores[n]['task_mean_error_rate'],scores[n]['counts']['strict_errors'],int(n[1:])))
assert chosen==expected_selection['selected_B']
bootstrap=paired_task_bootstrap(scores['A']['per_task_error_rate'],scores[chosen]['per_task_error_rate'])
assert canonical(bootstrap)==canonical(expected_selection['descriptive_B_minus_A'])
summary={'scope':'completed_validation_search_not_test_or_confirmatory',
    'source_commit':plan['source_commit'],'plan_hash':digest(plan),'selected_B':chosen,
    'selected_example_ids':expected_selection['selected_example_ids'],
    'calls':1800,'source_groups_per_condition':150,'views_per_condition':600,'judgments_per_condition':2400,
    'local_raw_prediction_and_score_replay_exact':True,'budgets':{k:plan[k] for k in ['context','max_new_tokens','token_budget']},
    'scores':{n:{k:scores[n][k] for k in ['counts','task_mean_error_rate','source_task_groups','confusion']} for n in scores},
    'costs':costs,'descriptive_B_minus_A':bootstrap,
    'all_condition_wall_seconds':json.loads((root/'inference-status.json').read_text())['seconds'],
    'formal_protocol_frozen':False,'heldout_files_read':False,'human_evaluation_claim':False,
    'warning':'Same validation data chose B3: comparison and bootstrap interval are selection-biased/descriptive. Existing two-candidate plan kept, no test scores or partial outcomes used to change it. Four-example negative outcome and malformed predictions retained.'}
args.out.mkdir(parents=True,exist_ok=False)
(args.out/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
(args.out/'private-file-sha256.json').write_text(json.dumps({p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()},indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({'selected_B':chosen,'state_error_rates':{n:scores[n]['task_mean_error_rate'] for n in scores},'costs':costs},indent=2))
