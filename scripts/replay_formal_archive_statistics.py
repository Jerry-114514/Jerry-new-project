"""Portable CPU arithmetic replay of final archives, without server paths/models.

This verifies archive bytes, seals and the registered arithmetic. It does not
replay the model or independently prove oracle truth or sampling assumptions.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from intentlab.core import canonical, digest
from intentlab.research_statistics import analyze_records
from postformal_evidence_support import BoundArchive, completed_m7


def replay(package, manifest_sha, source_commit, out):
    package,out=Path(package),Path(out)
    if out.exists():raise FileExistsError('Use a fresh output directory')
    manifest_raw=(package/'release-manifest.json').read_bytes()
    if hashlib.sha256(manifest_raw).hexdigest()!=manifest_sha:
        raise ValueError('Release manifest differs from externally trusted SHA256')
    release=json.loads(manifest_raw)
    names=subprocess.check_output(['git','ls-tree','-r','--name-only',source_commit,'intentlab'],cwd=ROOT).decode().splitlines()
    if not names:raise ValueError('Frozen scientific source not found')
    for name in names:
        raw=subprocess.check_output(['git','show',source_commit+':'+name],cwd=ROOT)
        if (ROOT/name).read_text(encoding='utf-8')!=raw.decode():
            raise ValueError('Current scientific source differs from frozen commit: '+name)
    with ExitStack() as stack:
        archives={name:stack.enter_context(BoundArchive(package/name,release['assets'][name]['sha256'])) for name in (
            'frozen-scientific-data.tar.gz','sealed-predictions.tar','sealed-scoring.tar',
            'sealed-execution.tar','sealed-ablation.tar','sealed-statistics.tar')}
        for name,a in archives.items():
            expected=release['assets'][name]
            actual={m:{'bytes':a.members[m].size,'sha256':a.member_hash(m)} for m in a.members}
            if actual!={m['path']:{'bytes':m['bytes'],'sha256':m['sha256']} for m in expected['members']}:
                raise ValueError('Release member inventory changed')
        scientific=archives['frozen-scientific-data.tar.gz']
        protocol=scientific.json('protocol/formal-protocol.lock.json')
        protocol_hash=protocol['lock_hash']
        if digest({k:v for k,v in protocol.items() if k!='lock_hash'})!=protocol_hash:
            raise ValueError('Changed protocol')
        stats=archives['sealed-statistics.tar']
        supervised=stats.json('supervision/supervisor-status.json')
        binding=supervised['binding_hash']
        if supervised['status']!='completed' or supervised['canonical_reports_identical'] is not True \
                or supervised['runtime_commit']!=source_commit \
                or any(s['status']!='completed' or type(s['exit_code']) is not int or s['exit_code']!=0 for s in supervised['stages']):
            raise ValueError('Original statistics did not complete')
        completed_m7(archives['sealed-ablation.tar'],protocol_hash,binding)
        pred=archives['sealed-predictions.tar'].sealed('', 'frozen_diagnostic_predictions','sealed','seal_hash',protocol_hash,binding)
        scoring=archives['sealed-scoring.tar'].sealed('', 'frozen_diagnostic_reveal','completed','receipt_hash',protocol_hash,binding)
        execution=archives['sealed-execution.tar']
        interactions=execution.sealed('interactions/','frozen_execution_interactions','sealed','seal_hash',protocol_hash,binding)
        reveal=execution.sealed('reveal/','frozen_execution_reveal','completed','receipt_hash',protocol_hash,binding)
        if pred['gold_loaded'] is not False or scoring['gold_opened_after_claim'] is not True \
                or scoring['prediction_seal_hash']!=pred['seal_hash'] or reveal['interaction_seal_hash']!=interactions['seal_hash']:
            raise ValueError('Broken upstream receipt chain')
        original=stats.json('analysis/report.json')
        previous_replay=stats.json('replay/report.json')
        if canonical(original)!=canonical(previous_replay):raise ValueError('Original reports differ')
        scores=archives['sealed-scoring.tar'].json('scores.json')
        losses={f'{c}-seed-{s}':archives['sealed-scoring.tar'].rows(f'{c}-seed-{s}-loss.jsonl')
                for c in ('D','E') for s in (0,1,2)}
        fresh=analyze_records(protocol,scores,losses,execution.rows('reveal/runs.jsonl'),
            archives['sealed-ablation.tar'].rows('reveal/runs.jsonl'),include_auxiliary=True)
        fresh['remaining'].remove('verified statistics entry/receipt')
        fresh['analysis_stage_receipt']='manifest.json'
        if canonical(fresh)!=canonical(original):raise ValueError('Fresh registered arithmetic differs from original')
        for a in archives.values():a.verify_outer()
    out.mkdir(parents=True,exist_ok=False)
    (out/'report.json').write_text(json.dumps(fresh,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    proof={'kind':'portable_registered_archive_arithmetic_replay','status':'completed',
        'release_manifest_sha256':manifest_sha,'source_commit':source_commit,'scientific_files_checked':len(names),
        'protocol_hash':protocol_hash,'binding_hash':binding,'comparisons':len(fresh['comparisons']),
        'all_original_report_fields_canonical_equal':True,'gold_or_reference_contents_decoded':False,
        'model_called':False,'server_absolute_paths_used':False,'m8_complete':False,
        'warning':'Archive arithmetic replay only; does not rerun oracle verification, source independence or model training.'}
    (out/'replay-verification.json').write_text(json.dumps(proof,indent=2)+'\n',encoding='utf-8',newline='\n')
    return proof


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('package','out'):p.add_argument('--'+name,type=Path,required=True)
    for name in ('expected-manifest-sha256','source-commit'):p.add_argument('--'+name,required=True)
    a=p.parse_args()
    print(json.dumps(replay(a.package,a.expected_manifest_sha256,a.source_commit,a.out)))
