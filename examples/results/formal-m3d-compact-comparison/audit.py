"""Audit aggregate prompt comparison; private replay uses raw calls, not gold."""
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
from intentlab.formal_data import read_jsonl
from intentlab.protocol import source_snapshot


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def audit(private_results=None):
    manifest=read(ROOT/'manifest.json')
    assert manifest['status']=='completed' and manifest['views']==104
    assert manifest['planned_calls']==manifest['actual_calls']==208
    assert manifest['source_commit']=='fa0cc94df39eb978e7b8609f5f8ee83b2e64eeb6'
    assert manifest['source_normalized_sha256']==source_snapshot(REPO)
    assert manifest['driver_sha256']==hashlib.sha256((ROOT/'run-comparison-driver.py').read_bytes()).hexdigest()
    runtime=read(ROOT/'runtime-identity.json')
    assert runtime['versions_captured_after_run'] is True
    assert runtime['driver_sha256']==manifest['driver_sha256']
    assert runtime['analyzer_sha256']==hashlib.sha256((ROOT/'analyze.py').read_bytes()).hexdigest()
    assert set(runtime['packages'])=={'torch','transformers','tokenizers','peft','accelerate'}
    assert manifest['conditions']==['full','compact'] and manifest['do_sample'] is False
    assert manifest['no_retry'] is manifest['budget_reset_per_call'] is True
    assert manifest['gold_loaded'] is manifest['formal_training_started'] is manifest['formal_budget_approved'] is False
    assert manifest['human_accuracy'] is None
    assert [manifest[k] for k in ('context_limit','max_new_tokens','token_budget_per_call')]==[6144,512,8192]
    original=read(ROOT.parent/'formal-m3c-context-coverage/lengths-by-context.json')['2048']
    compact=read(ROOT.parent/'formal-m3c-context-coverage/compact-trial.json')
    assert manifest['cases_hash']==original['cases_hash']==compact['cases_hash']
    preflight=read(ROOT/'preflight.json')
    assert preflight['cases_hash']==manifest['cases_hash'] and len(preflight['rows'])==208
    expected={(r['case_id'],condition):r for condition,rows in (('full',original['rows']),('compact',compact['rows'])) for r in rows}
    seen=set()
    for row in preflight['rows']:
        key=(row['case_id'],row['condition'])
        assert key in expected and key not in seen
        seen.add(key)
        assert all(row[k]==expected[key][k] for k in ('prompt_hash','prompt_tokens'))
        assert row['prompt_tokens']+512<=6144
    assert seen==set(expected)
    report=read(ROOT/'analysis.json')
    assert report['gold_loaded'] is report['formal_training_started'] is report['formal_budget_approved'] is False
    assert report['human_accuracy'] is None
    for condition in ('full','compact'):
        group=report['conditions'][condition]
        assert group['views']==104 and group['requested_items']==416
        assert group['generated_views']+group['generation_errors']==104
        for mode in ('strict','normalized'):
            assert group[mode+'_parsed_views']+group[mode+'_invalid_views']==104
            assert group[mode+'_visible_reference_constraint_valid_views']+group[mode+'_visible_reference_constraint_invalid_views']==group[mode+'_parsed_views']
        assert sum(group['predicted_'+state+'_items'] for state in ('satisfied','violated','unknown'))==4*group['normalized_parsed_views']
        assert group['preflight_prompt_tokens']==sum(r['prompt_tokens'] for r in preflight['rows'] if r['condition']==condition)
    paired=report['paired']
    assert paired['views']==104 and paired['requested_items']==416
    assert paired['comparable_views']+paired['noncomparable_views']==104
    assert paired['comparable_items']+paired['noncomparable_items']==416
    assert paired['status_disagreements']<=paired['comparable_items']
    assets=read(ROOT/'official-assets-after-run.json')
    assert assets['revision']=='c202236235762e1c871ad0ccb60c8ee5ba337b9a' and len(assets['verified_assets'])==13
    if private_results is not None:
        sums=read(ROOT/'private-file-sha256.json')
        assert {p.name for p in private_results.iterdir() if p.is_file()}==set(sums)
        assert all(hashlib.sha256((private_results/name).read_bytes()).hexdigest()==sha for name,sha in sums.items())
        assert sums['raw-calls.jsonl']==manifest['raw_calls_sha256']
        assert read(private_results/'manifest.json')==manifest
        assert read(private_results/'preflight.json')==preflight
        cases=read_jsonl(private_results/'private-coordinator-cases.jsonl')
        assert digest(cases)==manifest['cases_hash']
        full_prompt=runpy.run_path(str(REPO/'examples/results/formal-m3c-context-coverage/compact-driver.py'))['compact_prompt']
        from intentlab.formal_data import formal_prompt
        rows={(r['case_id'],r['condition']):r for r in preflight['rows']}
        for case in cases:
            for condition,prompt in (('full',formal_prompt(case['public'])),('compact',full_prompt(case['public']))):
                assert digest(prompt)==rows[(case['case_id'],condition)]['prompt_hash']
        reproduced=runpy.run_path(str(ROOT/'analyze.py'))['analyze'](cases,manifest,preflight,read_jsonl(private_results/'raw-calls.jsonl'))
        assert canonical(reproduced)==canonical(report)
    return {'scope':'unreviewed_development_prompt_interface_comparison','views':104,'calls':208,
        'raw_calls_and_aggregate_replayed':private_results is not None,'human_accuracy':None,
        'formal_training_started':False,'formal_budget_approved':False,
        'warning':'Metadata only unless private records are supplied; replay verifies records and arithmetic, not model authenticity, human truth or unchanged semantic behavior.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-results',type=Path)
    args=parser.parse_args();report=audit(args.private_results)
    name='raw-replay-verification.json' if args.private_results else 'verification.json'
    (ROOT/name).write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(report,indent=2))
