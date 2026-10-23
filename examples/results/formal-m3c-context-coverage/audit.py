"""Verify context arithmetic and hardware records; optionally retokenize inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import sys

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[2]
sys.path.insert(0,str(REPO))
from intentlab.core import canonical,digest
from intentlab.formal_data import read_jsonl,formal_prompt
from intentlab.protocol import source_snapshot


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def audit(model=None,injected=None,natural=None):
    if len([p for p in (model,injected,natural) if p is not None]) not in (0,3):
        raise ValueError('Provide model, injected cases and natural root together')
    reports,summary=read(ROOT/'lengths-by-context.json'),read(ROOT/'summary.json')
    identity=read(ROOT/'runtime-identity.json')
    assert source_snapshot(REPO)==identity['source_normalized_sha256']
    assert identity['model_weights_loaded'] is identity['gpu_used'] is False
    assert identity['probe_script_sha256']==hashlib.sha256((ROOT/'measure-driver.py').read_bytes()).hexdigest()
    assert identity['official_revision']=='c202236235762e1c871ad0ccb60c8ee5ba337b9a'
    membership=read(ROOT/'case-batches.json')
    assert len(membership)==104
    assert [summary['cannot_reserve_512_by_context'][str(n)] for n in (2048,3072,4096)]==[73,31,6]
    assert [summary['cannot_generate_by_context'][str(n)] for n in (2048,3072,4096)]==[56,13,3]
    for key in ('human_labels_read','fewshot_audited','reviewed_SFT_target_lengths_audited',
                'training_memory_measured','formal_budget_approved','formal_training_started'):
        assert summary[key] is False
    first=reports['2048']['rows']
    assert len(first)==104 and {r['case_id'] for r in first}==set(membership)
    for n in (2048,3072,4096):
        r=reports[str(n)]
        assert r['context_limit']==n and r['max_new_tokens']==512 and r['token_budget']==8192
        assert len(r['rows'])==104 and r['cases_hash']==reports['2048']['cases_hash']
        for old,row in zip(first,r['rows']):
            assert all(row[k]==old[k] for k in ('case_id','source_task_id','prompt_hash','prompt_tokens'))
            allowance=max(0,min(512,n-row['prompt_tokens'],8192-row['prompt_tokens']))
            assert row['generation_allowance']==allowance and row['full_generation_reservation_fits']==(allowance==512)
        assert r['cannot_generate']==sum(row['generation_allowance']==0 for row in r['rows'])
        assert r['cannot_reserve_full_generation']==sum(not row['full_generation_reservation_fits'] for row in r['rows'])
        assert r['cannot_generate']==summary['cannot_generate_by_context'][str(n)]
        assert r['cannot_reserve_full_generation']==summary['cannot_reserve_512_by_context'][str(n)]
    assert min(r['prompt_tokens'] for r in first)==summary['minimum_prompt_tokens']==727
    assert max(r['prompt_tokens'] for r in first)==summary['maximum_prompt_tokens']==4691
    compact=read(ROOT/'compact-trial.json')
    assert compact['cases_hash']==reports['2048']['cases_hash'] and len(compact['rows'])==104
    assert {r['case_id'] for r in compact['rows']}==set(membership)
    assert max(r['prompt_tokens'] for r in compact['rows'])==compact['maximum_prompt_tokens']==2710
    assert min(r['prompt_tokens'] for r in compact['rows'])==compact['minimum_prompt_tokens']==660
    assert compact['public_payload_and_schema_unchanged'] is compact['all_original_catalog_values_reconstructable'] is True
    assert compact['core_prompt_changed'] is compact['inference_performed'] is compact['semantic_equivalence_for_model_verified'] is compact['formal_budget_approved'] is False
    for n in (2048,3072,4096):
        assert compact['cannot_reserve_512_by_context'][str(n)]==sum(r['prompt_tokens']+512>n for r in compact['rows'])
    assert max(r['prompt_tokens']+512 for r in compact['rows'])<=3328
    hardware=read(ROOT/'hardware-summary.json')
    assert hardware['formal_training'] is hardware['human_task_targets'] is hardware['fits_all_formal_targets_or_fewshot'] is False
    for n in (3328,4096):
        attempt=read(ROOT/f'attempt-{n}.json')
        assert attempt['actual_sequence_tokens']==n and attempt['formal_training'] is attempt['human_task_labels'] is False
        assert attempt['exit_code']==(0 if n==3328 else 1)
        assert attempt['status']==('completed' if n==3328 else 'failed')
        manifest=read(ROOT/f'data-{n}/manifest.json')
        assert manifest['actual_sequence_tokens']==n and manifest['human_task_labels'] is manifest['formal_training'] is False
        for name,sha in manifest['files_sha256'].items():
            assert hashlib.sha256((ROOT/f'data-{n}'/name).read_bytes()).hexdigest()==sha
    assert 'Triton Error [CUDA]: out of memory' in (ROOT/'train-4096.log').read_text(encoding='utf-8')
    assert not (ROOT/'train-4096/result.json').exists()
    result=read(ROOT/'train-3328/result.json')
    assert result['completed'] and result['step']==2 and result['test_deferred'] is True and 'test' not in result
    assert result['config']==read(ROOT/'train-3328/run_config.json')
    for key,value in {'max_length':3328,'steps':2,'batch_size':1,'accumulation':2,'rank':16,'alpha':32,'mode':'qlora','device':'cuda','defer_test':True}.items():
        assert result['config'][key]==value
    assert result['train_tokens']==4*3328 and result['examples_seen']==4
    assert result['supervised_tokens']==4*read(ROOT/'data-3328/manifest.json')['target_tokens_per_example']
    assert result['peak_reserved_bytes']==hardware['peak_reserved_bytes']
    assert result['peak_allocated_bytes']==hardware['peak_allocated_bytes']
    assert read(ROOT/'official-assets-after-run.json')['revision']==identity['official_revision']
    if model is not None:
        from transformers import AutoTokenizer
        from intentlab.prompts import prompt_ids
        from intentlab.neural import encode_pair
        tokenizer=AutoTokenizer.from_pretrained(model,local_files_only=True,trust_remote_code=False)
        for name,sha in identity['tokenizer_files_sha256'].items():
            assert hashlib.sha256((model/name).read_bytes()).hexdigest()==sha
        cases=read_jsonl(REPO/'examples/results/formal-m2b-source-triage/triage/coordinator-cases.jsonl')+read_jsonl(injected)+read_jsonl(natural/'first-two/intake/coordinator-cases.jsonl')+read_jsonl(natural/'remaining-ten/intake/coordinator-cases.jsonl')
        assert digest(cases)==reports['2048']['cases_hash']
        proposed=runpy.run_path(str(ROOT/'compact-driver.py'))['compact_prompt']
        for case,old,new in zip(cases,first,compact['rows']):
            for prompt,row in ((formal_prompt(case['public']),old),(proposed(case['public']),new)):
                assert row['case_id']==case['case_id'] and row['prompt_hash']==digest(prompt)
                assert row['prompt_tokens']==len(prompt_ids(tokenizer,prompt))
        for n in (3328,4096):
            rows=read_jsonl(ROOT/f'data-{n}/train.jsonl')+read_jsonl(ROOT/f'data-{n}/validation.jsonl')
            assert all(len(encode_pair(tokenizer,row,n)['input_ids'])==n for row in rows)
    return {'scope':'context_and_synthetic_hardware_evidence_only','views':104,
        'actual_tokenizer_and_private_prompts_replayed':model is not None,'original_max_prompt_tokens':4691,
        'proposed_compact_max_prompt_tokens':2710,'passed_synthetic_length':3328,'failed_synthetic_length':4096,
        'formal_budget_approved':False,'formal_training_started':False,
        'warning':'New prompt proposal has not been used for inference or training. Synthetic probes do not establish real-label fit, few-shot behavior, universal memory boundaries or 48/80GB fit.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model',type=Path);parser.add_argument('--injected',type=Path);parser.add_argument('--natural-root',type=Path)
    args=parser.parse_args();report=audit(args.model,args.injected,args.natural_root)
    name='tokenizer-replay-verification.json' if args.model else 'verification.json'
    (ROOT/name).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(report,indent=2))
