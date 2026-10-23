"""Separate offline development scoring after all candidate generations finish."""
import json
from pathlib import Path
import sys

source=Path('/root/autodl-tmp/Jerry-formal-v2-20261022')
root=Path('/root/autodl-tmp/procedural-fewshot-development-20261023')
sys.path.insert(0,str(source))
from intentlab.core import digest
from intentlab.formal_data import read_jsonl
from intentlab.formal_eval import score_predictions, paired_task_bootstrap
from intentlab.protocol import file_hash

plan=json.loads((root/'plan.json').read_text())
status=json.loads((root/'inference-status.json').read_text())
assert status['status']=='completed', 'No selection on incomplete generation'
for name, expected in plan['file_sha256'].items():
    assert file_hash(root/name)==expected,name
cases=read_jsonl(root/'validation-cases.jsonl')
gold=json.loads((root/'validation-gold.json').read_text())
out=root/'scoring'
out.mkdir(exist_ok=False)
scores={}
for name in plan['conditions']:
    manifest=json.loads((root/name/'manifest.json').read_text())
    assert manifest['status']=='completed' and manifest['case_count']==600
    for filename, expected in manifest['file_sha256'].items():
        assert file_hash(root/name/filename)==expected
    scores[name]=score_predictions(cases,gold,read_jsonl(root/name/'predictions.jsonl'))
    scores[name]['evidence_semantic_support']='Not scored. Programmatic state labels only; no human validation claim.'
    (out/(name+'.json')).write_text(json.dumps(scores[name],indent=2,sort_keys=True)+'\n')
selected=min(['B3','B4'],key=lambda n:(scores[n]['task_mean_error_rate'],scores[n]['counts']['strict_errors'],int(n[1:])))
result={'scope':'validation_development_search_not_test_or_confirmatory',
        'plan_hash':digest(plan),'selected_B':selected,'selected_example_ids':plan['example_ids'][:int(selected[1:])],
        'selection_rule':plan['B_selection_rule'], 'eligible_B_conditions':['B3','B4'],
        'heldout_read':False,'formal_frozen':False,
        'scores':{n:{k:scores[n][k] for k in ['counts','task_mean_error_rate','source_task_groups','confusion']} for n in scores},
        'descriptive_B_minus_A':paired_task_bootstrap(scores['A']['per_task_error_rate'],scores[selected]['per_task_error_rate']),
        'warning':'B selection uses these same development cases: comparison is selection-biased and not heldout evidence. Missing or malformed outputs count as errors.'}
(out/'selection.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
print(json.dumps(result,indent=2),flush=True)
