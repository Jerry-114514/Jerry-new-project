"""Describe overlap strata before model evaluation; do not remove data."""
from collections import Counter
import hashlib
import json
from pathlib import Path

base=Path('runs/procedural-matched-test-candidates-20261023')
audit=Path('runs/matched-test-similarity-local-20261023')
tasks={t['id']:t for t in map(json.loads,(base/'tasks.jsonl').read_text(encoding='utf-8').splitlines())}
flags=json.loads((audit/'private-flags.json').read_text())
all_test={tid for tid,t in tasks.items() if t['split']=='test'}
train_pairs=[f for f in flags if f['split_pair']=='test / train']
val_pairs=[f for f in flags if f['split_pair']=='test / validation']
def test_ids(pairs):
    return {f[key] for f in pairs for key in ['left','right'] if tasks[f[key]]['split']=='test'}
exact_pairs=[f for f in train_pairs if f['edit_distance']==0]
exact=test_ids(exact_pairs)
near=test_ids(train_pairs)
dev_near=near|test_ids(val_pairs)
masks={'all_test':sorted(all_test),'normalized_exact_train_overlap':sorted(exact),
       'within_25pct_train_overlap':sorted(near),
       'no_normalized_exact_train_overlap':sorted(all_test-exact),
       'no_within_25pct_development_overlap':sorted(all_test-dev_near)}
assert len(all_test)==200 and exact<=near<=all_test
mask_path=audit/'private-overlap-strata.json'
with mask_path.open('x',encoding='utf-8',newline='\n') as handle:
    handle.write(json.dumps(masks,indent=2,sort_keys=True)+'\n')
summary={'scope':'pre_evaluation_descriptive_overlap_strata_not_data_selection',
    'test_sources':200,'test_train_exact_pairs':len(exact_pairs),'test_train_near_pairs':len(train_pairs),
    'test_validation_near_pairs':len(val_pairs),
    'exact_train_overlap_test_sources':len(exact),'near_train_overlap_test_sources':len(near),
    'near_any_development_overlap_test_sources':len(dev_near),
    'exact_pairs_by_family':dict(Counter(f['family'] for f in exact_pairs)),
    'near_train_pairs_by_family':dict(Counter(f['family'] for f in train_pairs)),
    'stratum_source_counts':{k:len(v) for k,v in masks.items()},
    'private_strata_sha256':hashlib.sha256(mask_path.read_bytes()).hexdigest(),
    'no_model_outputs_or_gold_read':True,'no_task_removed_or_regenerated':True,
    'formal_test_candidate_selected':False,
    'warning':'Normalized collisions omit random identity values and layout details. They are not identical full inputs or demonstrated answer leakage. Strata are descriptive candidates, not registered primary/sensitivity analyses. Keep all 200 tasks if selecting this candidate and finalize analysis before test model evaluation.'}
(audit/'overlap-summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(summary,indent=2))
