"""Metadata checks or coordinator-only reconstruction with private split seeds."""
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[2]
sys.path.insert(0,str(REPO))
from intentlab.core import digest
from intentlab.formal_data import read_jsonl
from intentlab.procedural_data import generate
from intentlab.programmatic_labels import generate_labels
from intentlab.programmatic_protocol import source_record, validation_record
from intentlab.spec_reference import verify_references


def audit(private=None, evidence=None):
    for name,wanted in json.loads((ROOT/'checksums.json').read_text()).items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==wanted,name
    summary=json.loads((ROOT/'summary.json').read_text())
    assert summary['tasks_by_split']=={'train':600,'validation':150,'test':200,'ood':100}
    assert summary['views_by_split']=={'train':2400,'validation':600,'test':800,'ood':400}
    assert summary['templates']==26 and summary['model_calls']==0
    assert not summary['formal_protocol_frozen'] and not summary['source_independence_proven']
    record=json.loads((ROOT/'programmatic-validation.json').read_text())
    assert record['reference_check']['tasks']==1050 and record['fault_audit']['cases']==8744
    assert len(record['blocked_development_tasks_fault_tested'])==64
    assert record['blocked_development_tasks_not_fault_tested']==[]
    assert record['fault_audit']['mutants_detected']==6
    if (private is None)!=(evidence is None):
        raise ValueError('Supply private data and evidence together')
    if private is not None:
        for name,wanted in json.loads((ROOT/'private-file-sha256.json').read_text()).items():
            assert hashlib.sha256((private/name).read_bytes()).hexdigest()==wanted,name
        plan=json.loads((REPO/'configs/procedural-data-plan.json').read_text())
        seeds=json.loads((private/'private-seeds.json').read_text())
        tasks,refs,cases,ledger=generate(plan,seeds)
        assert tasks==read_jsonl(private/'tasks.jsonl')
        assert refs=={r['task_id']:r for r in read_jsonl(private/'references.jsonl')}
        assert cases==read_jsonl(private/'cases.jsonl') and ledger==read_jsonl(private/'private-ledger.jsonl')
        assert digest(tasks)==summary['tasks_hash'] and digest(cases)==summary['cases_hash']
        labels=generate_labels(cases,tasks,refs)
        assert labels==read_jsonl(private/'export/programmatic-labels.jsonl')
        assert digest(labels)==summary['labels_hash']
        assert validation_record(cases,tasks,refs)==record
        assert json.loads((evidence/'programmatic-validation.json').read_text())==record
        source=source_record(cases)
        source_summary=json.loads((ROOT/'source-isolation-summary.json').read_text())
        assert digest(source)==source_summary['record_hash']
        assert source==json.loads((evidence/'source-isolation.json').read_text())
        heldout=[t for t in tasks if t['split'] in ('test','ood')]
        assert verify_references(heldout,{t['id']:refs[t['id']] for t in heldout})==json.loads((ROOT/'execution-reference-check.json').read_text())
    return {'metadata_verified':True,'private_dataset_and_evidence_rebuilt':private is not None,
        'source_draws':1050,'views':4200,'model_calls':0,'formal_ready':False}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--private-root',type=Path)
    parser.add_argument('--evidence-root',type=Path)
    args=parser.parse_args()
    print(json.dumps(audit(args.private_root,args.evidence_root),indent=2))
