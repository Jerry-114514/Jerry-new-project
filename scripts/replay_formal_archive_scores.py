"""CPU replay of frozen M5 scores and M6/M7 oracle/candidate audits.

Uses private final archives. Does not publish inputs, rerun language models,
recompute model forward losses, or establish statistical independence.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from intentlab.core import canonical, digest
from intentlab.diagnostic_protocol import CONDITIONS, rule_predictions
from intentlab.execution_data import validate_references, validate_tasks
from intentlab.execution_protocol import contract_identity
from intentlab.formal_data import validate_findings
from intentlab.formal_eval import score_predictions
from intentlab.frozen_execution import score_records, summary
from replay_formal_archive_statistics import replay as replay_statistics
from postformal_evidence_support import BoundArchive


def replay(package, manifest_sha, source_commit, out):
    package,out=Path(package),Path(out)
    if out.exists():raise FileExistsError('Use a fresh output directory')
    # Complete hash/source/seal validation and original statistics comparison
    # precede the first gold/reference decoding below.
    stats=replay_statistics(package,manifest_sha,source_commit,out/'statistics')
    status={'kind':'portable_raw_score_and_oracle_replay','status':'running',
        'model_called':False,'model_forward_losses_recomputed':False,'m8_complete':False}
    def save():
        (out/'score-replay-verification.json').write_text(json.dumps(status,indent=2)+'\n',encoding='utf-8',newline='\n')
    save()
    try:
        manifest=json.loads((package/'release-manifest.json').read_text())
        if hashlib.sha256((package/'release-manifest.json').read_bytes()).hexdigest()!=manifest_sha:
            raise ValueError('Package manifest changed after statistics verification')
        with ExitStack() as stack:
            archives={n:stack.enter_context(BoundArchive(package/n,manifest['assets'][n]['sha256'])) for n in (
                'frozen-scientific-data.tar.gz','sealed-predictions.tar','sealed-scoring.tar',
                'sealed-execution.tar','sealed-ablation.tar')}
            data=archives['frozen-scientific-data.tar.gz']
            protocol=data.json('protocol/formal-protocol.lock.json')
            cases=[c for s in ('test','ood') for c in data.rows(f'dataset/export/heldout/{s}/cases.jsonl')]
            if len(cases)!=1240 or len({c['case_id'] for c in cases})!=1240:
                raise ValueError('Expected complete 1240-case diagnostic population')
            gold={}
            for split in ('test','ood'):
                for row in data.rows(f'dataset/export/heldout/{split}/gold.jsonl'):
                    if row['case_id'] in gold:raise ValueError('Duplicate gold')
                    gold[row['case_id']]=row['findings']
            if set(gold)!={c['case_id'] for c in cases}:raise ValueError('Gold coverage differs')
            gold={c['case_id']:validate_findings(gold[c['case_id']],c['public']) for c in cases}
            fresh={};raw_predictions=archives['sealed-predictions.tar']
            for condition in CONDITIONS:
                raw=raw_predictions.rows(condition+'/predictions.jsonl')
                fresh[condition]={}
                for split in ('test','ood'):
                    selected=[c for c in cases if c['split']==split];ids={c['case_id'] for c in selected}
                    fresh[condition][split]=score_predictions(selected,
                        {c['case_id']:[gold[c['case_id']][r['id']] for r in c['public']['requirements']] for c in selected},
                        [r for r in raw if r['case_id'] in ids])
            if canonical(fresh)!=canonical(archives['sealed-scoring.tar'].json('scores.json')):
                raise ValueError('Diagnostic score replay differs')
            status.update(diagnostic_conditions=len(fresh),diagnostic_cases_per_condition=len(cases),
                diagnostic_raw_prediction_records=sum(len(raw_predictions.rows(c+'/predictions.jsonl')) for c in CONDITIONS),
                complete_diagnostic_scores_canonical_equal=True)
            save()
            tasks=sorted(validate_tasks(data.rows('dataset/execution-tasks.jsonl')),key=lambda t:t['id'])
            references=validate_references(data.rows('dataset/execution-references.jsonl'),tasks)
            rule_predictions(cases,{contract_identity(t,{'request':t['request'],'inputs':t['inputs'],
                'requirements':t['requirements'],'execution_spec':t['spec']}):t for t in tasks},out/'rule-replay')
            regenerated=[json.loads(line) for line in (out/'rule-replay/predictions.jsonl').read_text().splitlines()]
            if canonical(regenerated)!=canonical(raw_predictions.rows('C/predictions.jsonl')):
                raise ValueError('Rule predictions differ from original')
            status['rule_baseline_raw_predictions_canonical_equal']=True;save()
            for stage,name in (('M6','sealed-execution.tar'),('M7','sealed-ablation.tar')):
                archive=archives[name]
                interactions=archive.json('interactions/manifest.json')
                raw=archive.rows('interactions/interactions.jsonl')
                fresh_rows=score_records(tasks,references,raw,candidate_metrics=True)
                if canonical(fresh_rows)!=canonical(archive.rows('reveal/runs.jsonl')):
                    raise ValueError(stage+' complete oracle/candidate rows differ')
                binding={'models':{role:{'path':path} for role,path in interactions['model_paths'].items()}}
                actual_summary=summary(tasks,references,fresh_rows,protocol,binding,interactions['conditions'])
                if canonical(actual_summary)!=canonical(archive.json('reveal/summary.json')):
                    raise ValueError(stage+' trace/ledger/intensity audit differs')
                status[stage]={'records':len(fresh_rows),'complete_scored_rows_canonical_equal':True,
                    'final_initial_and_candidate_oracle_recomputed':True,
                    'committed_events_ledger_intensity_and_frozen_summary_recomputed':True}
                save()
            for archive in archives.values():archive.verify_outer()
        status.update(status='completed',source_commit=source_commit,
            registered_statistics_all_fields_equal=stats['all_original_report_fields_canonical_equal'])
        status['limitations']=['Reuses original encoded-spec evaluators; not an independent second oracle implementation.',
            'No language-model generation or forward loss replay, no training resume or environment reinstall.',
            'Programmatic gold and oracle are not human truth; does not prove source independence.',
            'Private raw data stay private; successful local replay is not public independent reproducibility.']
        save();return status
    except BaseException as exc:
        status.update(status='failed',error_type=type(exc).__name__,error=str(exc));save();raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('package','out'):p.add_argument('--'+n,type=Path,required=True)
    for n in ('expected-manifest-sha256','source-commit'):p.add_argument('--'+n,required=True)
    a=p.parse_args()
    print(json.dumps(replay(a.package,a.expected_manifest_sha256,a.source_commit,a.out)))
