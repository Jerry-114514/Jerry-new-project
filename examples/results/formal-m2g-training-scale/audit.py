"""Metadata-only scale evidence, optionally rebuilding private train candidates."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import sys
import tempfile

ROOT=Path(__file__).resolve().parent
REPO=ROOT.parents[2]
sys.path.insert(0,str(REPO))
from intentlab.core import digest,initial_state
from intentlab.contracts import public_solution
from intentlab.execution_oracle import evaluate_execution
from intentlab.formal_data import read_jsonl
from intentlab.protocol import source_snapshot
from scripts.intake_wikisql import build_pool,MEMBERS,LIMITS
from scripts.adapt_wikisql_equality import build,eligible


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def hashes(root):
    return {p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
            for name in ('pool','adapted') for p in (root/name).rglob('*') if p.is_file()}


def capacity(rows):
    candidates=[r for r in rows if eligible(r)]
    pages,payloads=set(),set()
    for row in candidates:
        page=digest(row['table']['page_id']);payload=digest({k:row['table'][k] for k in ('header','types','rows')})
        if page in pages or payload in payloads:continue
        pages.add(page);payloads.add(payload)
    return {'source_candidates':len(rows),'eligible_equality_records':len(candidates),
        'after_page_and_exact_payload_dedup':len(pages),
        'excluded_by_selected_group_or_payload_overlap':len(candidates)-len(pages),
        'requested_training_candidate_contracts':600,'human_reviews_completed':0}


def prefixes(private):
    return {'source_pool_first_600_hash':digest(read_jsonl(private/'pool/coordinator-pool.jsonl')[:600]),
        'source_index_first_600_hash':digest(read_jsonl(private/'pool/public-index.jsonl')[:600]),
        'tasks_first_12_hash':digest(read_jsonl(private/'adapted/tasks.jsonl')[:12]),
        'references_first_12_hash':digest(read_jsonl(private/'adapted/candidate-references.jsonl')[:12]),
        'cases_first_48_hash':digest(read_jsonl(private/'adapted/cases.jsonl')[:48]),
        'lineage_first_12_hash':digest(read_jsonl(private/'adapted/coordinator-lineage.jsonl')[:12])}


def quality_summary(rows):
    q=runpy.run_path(str(ROOT.parent/'formal-m2c-wikisql-source-intake/audit.py'))['quality'](rows)
    return {k:q[k] for k in ('selected_candidates','distinct_table_ids','distinct_exact_table_payloads','distinct_supplied_page_id_values')}|{
        'missing_page_id_candidates':len(q['missing_page_id_candidates']),
        'duplicate_supplied_page_id_groups':len(q['duplicate_supplied_page_id_groups']),
        'human_verified_sources':0,'parent_page_or_worker_independence_audited':False}


def verify_private(private):
    tasks=read_jsonl(private/'adapted/tasks.jsonl')
    references={r['task_id']:r for r in read_jsonl(private/'adapted/candidate-references.jsonl')}
    assert len(tasks)==len(references)==600
    for task in tasks:
        state=initial_state(task);state.apply(public_solution(task))
        assert evaluate_execution(task,state,references[task['id']])['compliant_success']
    blanks=read_jsonl(private/'adapted/reviewer-packet/review-template.jsonl')
    assert len(blanks)==2400
    assert all(r['reviewer']=='' and r['human_verified'] is False and len(r['findings'])==4
               and all(f['status']=='' and f['evidence']==[] for f in r['findings']) for r in blanks)
    return tasks


def audit(archive=None,private=None):
    pool,adapted=read(ROOT/'pool-manifest.json'),read(ROOT/'adapter-manifest.json')
    source=read(REPO/'configs/wikisql-source.json')
    assert pool['archive']==source['archive'] and pool['revision']==source['revision']
    assert pool['repository']==source['repository'] and pool['parsed_members']==list(MEMBERS) and pool['selection_limits']==LIMITS
    assert pool['requested_candidates']==pool['selected_source_candidates']==3000
    assert pool['selection_seed']==20261023 and pool['upstream_heldout_json_parsed'] is False
    assert adapted['candidate_tasks']==adapted['provisional_page_groups']==600
    assert adapted['injected_views']==2400 and adapted['shared_project_templates']==1
    assert adapted['scope']=='train_development_only'
    assert adapted['source_pool_hash']==pool['coordinator_pool_hash']
    assert adapted['human_labels_created']==adapted['human_verified_project_tasks']==0
    assert all(adapted[k] is False for k in ('source_fidelity_review_complete','release_review_complete','formal_protocol_frozen'))
    rows=read_jsonl(ROOT/'lineage-public.jsonl')
    assert len(rows)==len({r['task_id'] for r in rows})==len({r['page_hash'] for r in rows})==len({r['table_payload_hash'] for r in rows})==600
    assert len({r['source_candidate_id'] for r in rows})==600
    for row in rows:
        assert 'private_view_mapping' not in row
        assert row['human_verified'] is row['original_question_fidelity_human_verified'] is False
        assert row['public_clarification_derived_from_upstream_sql_annotation'] is True
    assert rows[:12]==read_jsonl(ROOT.parent/'formal-m2d-wikisql-adaptation/lineage-public.jsonl')
    cap=read(ROOT/'capacity.json')
    assert cap['source_candidates']==3000 and cap['eligible_equality_records']==851
    assert cap['after_page_and_exact_payload_dedup']==724 and cap['excluded_by_selected_group_or_payload_overlap']==127
    prefix=read(ROOT/'prefix-consistency.json')
    old_pool=read(ROOT.parent/'formal-m2c-wikisql-source-intake/pool/manifest.json')
    old_adapt=read(ROOT.parent/'formal-m2d-wikisql-adaptation/adapter-manifest.json')
    assert prefix['source_pool_first_600_hash']==old_pool['coordinator_pool_hash']
    assert prefix['source_index_first_600_hash']==old_pool['public_index_sha256']
    for key,old_key in (('tasks_first_12_hash','tasks_hash'),('references_first_12_hash','references_hash'),('cases_first_48_hash','cases_hash'),('lineage_first_12_hash','lineage_hash')):
        assert prefix[key]==old_adapt[old_key]
    summary=read(ROOT/'scale-summary.json')
    assert summary['candidate_contracts']==600 and summary['new_candidate_contracts']==588
    assert summary['human_reviews_completed']==summary['new_model_calls']==0
    assert summary['shared_template_pairs_formula_only']==600*599//2
    assert summary['formal_minimum_tasks_satisfied'] is False and summary['formal_training_started'] is False
    assert read(ROOT/'runtime-identity.json')['source_normalized_sha256']==source_snapshot(REPO)
    package=read(ROOT/'reviewer-package.json')
    assert package['views']==package['records_per_reviewer']==2400 and package['judgments_per_reviewer']==9600
    assert package['human_reviews_completed']==0 and package['distributed'] is False
    assert package['source_fidelity_and_release_review_complete'] is False
    assert read(ROOT/'program-reference-consistency.json')=={'contracts_checked':600,'public_program_matches_separate_sqlite_candidate_reference':True,'human_truth_claim':False}
    quality=read(ROOT/'source-quality-summary.json')
    assert [quality[k] for k in ('selected_candidates','distinct_table_ids','distinct_exact_table_payloads','distinct_supplied_page_id_values','missing_page_id_candidates')]==[3000,3000,2988,1947,634]
    assert quality['parent_page_or_worker_independence_audited'] is False and quality['human_verified_sources']==0
    if private is not None:
        assert hashes(private)==read(ROOT/'private-file-sha256.json')
        assert prefixes(private)==prefix
        assert capacity(read_jsonl(private/'pool/coordinator-pool.jsonl'))==cap
        assert quality_summary(read_jsonl(private/'pool/coordinator-pool.jsonl'))==quality
        tasks=verify_private(private)
        assert digest(tasks)==adapted['tasks_hash']
        stripped=[{k:v for k,v in r.items() if k!='private_view_mapping'} for r in read_jsonl(private/'adapted/coordinator-lineage.jsonl')]
        assert stripped==rows
        for name in ('cases.jsonl','review-template.jsonl','README.md'):
            assert hashlib.sha256((private/'adapted/reviewer-packet'/name).read_bytes()).hexdigest()==package['files_sha256'][name]
    if archive is not None:
        with tempfile.TemporaryDirectory() as temporary:
            out=Path(temporary)
            assert build_pool(archive,source,out/'pool',3000,20261023)==pool
            assert build(out/'pool/coordinator-pool.jsonl',out/'pool/manifest.json',out/'adapted',600)==adapted
            assert hashes(out)==read(ROOT/'private-file-sha256.json')
            assert capacity(read_jsonl(out/'pool/coordinator-pool.jsonl'))==cap
            assert quality_summary(read_jsonl(out/'pool/coordinator-pool.jsonl'))==quality
            assert prefixes(out)==prefix
            verify_private(out)
    return {'scope':'unreviewed_single_template_train_candidate_scale','source_pool':3000,'candidate_contracts':600,
        'new_candidate_contracts':588,'injected_views':2400,'shared_templates':1,
        'private_files_and_program_references_checked':private is not None or archive is not None,
        'archive_rebuilt':archive is not None,'human_reviews_completed':0,'new_model_calls':0,
        'formal_minimum_tasks_satisfied':False,'formal_training_started':False,
        'warning':'Six hundred provisional page groups are not independently reviewed tasks. One shared template, injected views only; no sealed test/OOD, real labels or formal budget completion.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path);parser.add_argument('--private-root',type=Path)
    args=parser.parse_args();result=audit(args.archive,args.private_root)
    name='source-replay-verification.json' if args.archive else 'private-verification.json' if args.private_root else 'verification.json'
    (ROOT/name).write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(result,indent=2))
