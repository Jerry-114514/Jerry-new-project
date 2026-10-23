"""Prepare observed coordinator evidence; leave unfinished gates missing."""
from collections import Counter
import hashlib,json,shutil,sys
from pathlib import Path
src=Path('/root/autodl-tmp/intentlab-history-cpu-source-20261023')
sys.path.insert(0,str(src))
from intentlab.core import digest
from intentlab.execution_data import load_execution_tasks,load_references
from intentlab.formal_data import read_jsonl
from intentlab.protocol import check_spec,file_hash
from intentlab.spec_reference import verify_references
data=Path('/root/autodl-tmp/history-augmented-candidate-20261023')
out=Path('/root/autodl-tmp/history-freeze-preparation-20261023');out.mkdir(mode=0o700,exist_ok=False)
evidence=out/'evidence';evidence.mkdir(mode=0o700)
def save(p,v):p.write_text(json.dumps(v,indent=2,sort_keys=True)+'\n')
status={'status':'running','formal_protocol_frozen':False,'heldout_model_outputs_read':False}
save(out/'status.json',status)
expected=json.loads((src/'examples/results/formal-m3s-history-candidate/data-sha256.json').read_text())
assert all(file_hash(data/name)==sha for name,sha in expected.items())
tasks=load_execution_tasks(data/'tasks.jsonl');refs=load_references(data/'references.jsonl',tasks)
summary=json.loads((data/'summary.json').read_text())
assert digest(tasks)==summary['tasks_hash']
for source,target in [('source-isolation.json','source-isolation.json'),('programmatic-validation.json','programmatic-validation.json')]:
    shutil.copyfile(data/source,evidence/target)
execution=load_execution_tasks(data/'execution-tasks.jsonl')
assert len(execution)==300 and all(t['split'] in ('test','ood') for t in execution)
save(evidence/'execution-reference-check.json',verify_references(execution,load_references(data/'execution-references.jsonl',execution)))
power=json.loads((src/'examples/results/formal-m3t-development-power/summary.json').read_text())
assert power['heldout_model_outputs_read'] is False and len(power['cells'])==16
(evidence/'power-analysis.md').write_text((src/'docs/development-power-calibration.md').read_text()+'\n\nBound actual calibration:\n```json\n'+json.dumps(power,indent=2)+'\n```\n')
profile=json.loads(Path('/root/autodl-tmp/history-candidate-full-profile-20261023/summary.json').read_text())
for split in ['train','validation']:
    assert profile['splits'][split]['file_sha256']==file_hash(data/'export'/(split+'.jsonl'))
    assert profile['splits'][split]['over_training_context_12288']==0
assert profile['splits']['validation']['B3_over_17408_with_1536_reserve']==0
(evidence/'length-compute-budget.draft.md').write_text((src/'docs/paired-initialization-and-compute-budget.md').read_text()+'\n\nBound full profile:\n```json\n'+json.dumps(profile,indent=2)+'\n```\n')
provenance={'kind':'coordinator_generated_source_and_release_scope_review','human_evaluation_claim':False,
    'tasks_hash':digest(tasks),'cases_hash':summary['cases_hash'],'labels_hash':summary['labels_hash'],
    'origins':dict(Counter(t['source']['origin'] for t in tasks)),
    'licenses':dict(Counter(t['source']['license'] for t in tasks)),
    'source_counts_by_split':dict(Counter(t['split'] for t in tasks)),
    'natural_raw_sha256':'4129f438be0e98cdc65de3b48d38533e26ecc60e2826b5a9d9972975d5dd252c',
    'all_previous_records_preserved':summary['all_previous_export_rows_byte_identical_prefix'],
    'release_scope':'Code, aggregate evidence and hashes now; private seeds, test material, raw gold and not-yet-revealed model outputs withheld.',
    'normalized_test_train_exact_pairs':6,'normalized_test_train_near_pairs':165,
    'exact_affected_test_sources':5,'near_affected_test_sources':74,
    'legal_license_certification':False,'new_license_granted':False,'strict_iid_claim':False,
    'limitation':'Generated sources with fixed family quotas and wording/layout differences. IDs and metadata do not establish semantic independence. Same-root roles are not OS access-isolated. No third-party source records were imported by these builders; no public data license assigned.'}
(evidence/'provenance-release.md').write_text('# Generated-source provenance and publication scope\n\n'+json.dumps(provenance,indent=2)+'\n')
heldout={name:file_hash(data/name) for name in expected if name.startswith('export/heldout/')}
save(evidence/'preseal-integrity-inventory.json',{'heldout_files':heldout,'execution_files':{name:file_hash(data/name) for name in ['execution-tasks.jsonl','execution-references.jsonl']},'final_protocol_sealed':False,'same_root_access_isolation_claim':False,'purpose':'Integrity inventory only; final protocol and reveal receipts still required.'})
spec=json.loads((src/'configs/formal-protocol.history-candidate.draft.json').read_text())
spec['source_root']=str(src)
spec['dataset']={'cases':str(data/'cases.jsonl'),'labels':str(data/'export/programmatic-labels.jsonl'),'tasks':str(data/'tasks.jsonl'),'references':str(data/'references.jsonl'),'export':str(data/'export')}
spec['execution']['tasks']=str(data/'execution-tasks.jsonl');spec['execution']['references']=str(data/'execution-references.jsonl')
for key in spec['evidence']:
    spec['evidence'][key]=str(evidence/Path(spec['evidence'][key]).name)
spec['evidence']['model_weight_verification']=str(src/'configs/qwen35-official-assets.json')
save(out/'candidate-protocol.json',spec)
ready=check_spec(spec);save(out/'preliminary-readiness.json',ready)
assert not ready['ready'],'Never freeze while controller, budget or final seal is missing'
status.update(status='prepared_not_frozen',preliminary_blockers=ready['blockers'],deep_readiness_checks_completed=False,
    warning='check_spec returns early on missing files; this does not establish that these are the only remaining gates.')
save(out/'status.json',status);print(json.dumps(status),flush=True)
