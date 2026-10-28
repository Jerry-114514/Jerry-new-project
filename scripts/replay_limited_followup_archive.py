"""Replay sealed limited-run scores, evidence, scenarios and statistics on CPU.

Raw records stay inside the input tar stream. The output workspace stores pinned
public source, a private binding receipt, and a scalar verification projection.
"""
import argparse
from collections import Counter
import hashlib
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import sys
import tarfile

from verify_30h_private_archive import verify

CONDITIONS = ['A', 'B', 'C'] + [f'{k}-seed-{s}' for k in ('D', 'E') for s in range(3)]
TOOLS = ['scripts/limited_30h_diagnostics.py', 'scripts/score_evidence_support.py', 'scripts/evidence_support.py']


def require(condition, label):
    if not condition:
        raise ValueError(label)


def equal(actual, expected, label):
    canonical = lambda v: json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    require(canonical(actual) == canonical(expected), 'Replay mismatch: '+label)


def check_seal(manifest, index, protocol, digest):
    require(manifest.get('status') == 'sealed' and manifest.get('gold_loaded') is False,
            'All predictions must be sealed before reading gold')
    require(manifest['conditions'] == CONDITIONS == protocol['conditions'], 'Condition registry differs')
    require(manifest['protocol_hash'] == protocol['lock_hash'], 'Prediction protocol binding differs')
    require(manifest['seal_hash'] == digest({k:v for k,v in manifest.items() if k!='seal_hash'}), 'Prediction seal hash differs')
    files = {name.removeprefix('predictions/'):r['sha256'] for name,r in index['files'].items()
             if name.startswith('predictions/') and name != 'predictions/manifest.json'}
    equal(files, manifest['files_sha256'], 'complete sealed prediction inventory')


class Reader:
    def __init__(self, archive):
        self.archive = archive
    def json(self, name):
        member = self.archive.getmember(name)
        require(member.size < 128*1024**2, 'Unexpectedly large JSON record')
        return json.load(self.archive.extractfile(member))
    def rows(self, name):
        return [json.loads(line) for line in self.archive.extractfile(name) if line.strip()]


def pinned_sources(protocol, out, repository):
    require(not any(n == 'intentlab' or n.startswith('intentlab.') for n in sys.modules),
            'Run replay in a fresh Python process so frozen core imports cannot be mixed')
    for key in ('core_commit', 'orchestration_parent_commit'):
        require(re.fullmatch(r'[0-9a-f]{40}', protocol[key]) is not None, 'A pinned Git commit is required')
    core = out/'locked-core'; core.mkdir()
    raw = subprocess.check_output(['git', 'archive', '--format=tar', protocol['core_commit'], 'intentlab'], cwd=repository)
    with tarfile.open(fileobj=io.BytesIO(raw)) as a:
        for member in a.getmembers():
            path = PurePosixPath(member.name)
            require(not path.is_absolute() and '..' not in path.parts and path.parts[0] == 'intentlab', 'Unsafe core source path')
            if member.isdir():
                continue
            require(member.isfile(), 'Frozen core contains nonregular source')
            target = core/member.name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(a.extractfile(member).read())
    tools = out/'locked-tools'; tools.mkdir()
    for name in TOOLS:
        data = subprocess.check_output(['git', 'show', protocol['orchestration_parent_commit']+':'+name], cwd=repository)
        require(hashlib.sha256(data).hexdigest() == protocol['tool_files_sha256'][name], 'Frozen analysis source differs')
        (tools/Path(name).name).write_bytes(data)
    sys.path.insert(0, str(core)); sys.path.insert(0, str(tools))
    spec = importlib.util.spec_from_file_location('locked_limited_followup_analysis', tools/'limited_30h_diagnostics.py')
    analysis = importlib.util.module_from_spec(spec); spec.loader.exec_module(analysis)
    return analysis


def replay_preconditions(reader, protocol, digest):
    index = reader.json('backup-index.json')
    state = reader.json('state-for-archive.json')
    require(state.get('outcome') == 'completed' and state.get('limited_experiment_completed') is True,
            'A partial experiment cannot be certified as a completed replay')
    require(protocol['scope'] == 'approved_compute_limited_30h_followup', 'Wrong limited protocol')
    require(protocol['lock_hash'] == digest({k:v for k,v in protocol.items() if k!='lock_hash'}), 'Protocol lock changed')
    # These checks precede every decoded gold access in this replay.
    manifest = reader.json('predictions/manifest.json')
    check_seal(manifest, index, protocol, digest)
    return index, manifest


def recompute(reader, protocol, analysis):
    from intentlab.core import digest
    index, manifest = replay_preconditions(reader, protocol, digest)
    from intentlab.formal_data import validate_cases, validate_findings
    from intentlab.formal_eval import score_predictions
    from intentlab.formal_inference import reject_example_overlap
    from score_evidence_support import score_evidence_support
    binding = reader.json('model-binding.json')
    require(binding['protocol_hash'] == protocol['lock_hash']
            and binding['binding_hash'] == digest({k:v for k,v in binding.items() if k!='binding_hash'})
            and binding['binding_hash'] == manifest['model_binding_hash'], 'Selected model binding differs')
    require(set(binding['jobs']) == set(CONDITIONS[3:]), 'Six selected models required')
    for condition, row in binding['jobs'].items():
        require(row['config'] == protocol['jobs'][condition]['config']
                and row['base_identity'] == protocol['base_identity']
                and row['data_hash'] == protocol['training_data_hash'], 'Selected model metadata differs')
    for seed in range(3):
        require(binding['jobs'][f'D-seed-{seed}']['initial_trainable_sha256'] == binding['jobs'][f'E-seed-{seed}']['initial_trainable_sha256'],
                'Paired initialization binding differs')
    score_manifest = reader.json('scores/manifest.json')
    require(score_manifest['status'] == 'completed' and score_manifest['gold_opened_after_prediction_seal'] is True,
            'Complete scored target-loss stage required')
    require(reader.json('analysis/manifest.json')['status'] == 'completed', 'Complete analysis required')
    for name in ('public/cases.jsonl', 'public/tasks.jsonl', 'public/examples.json', 'sealed/gold.jsonl',
                 'sealed/references.jsonl', 'sealed/panel-assignment.json'):
        require(index['files'][name]['sha256'] == protocol['files_sha256'][name], 'Frozen archive input differs')
    cases = reader.rows('public/cases.jsonl'); tasks = reader.rows('public/tasks.jsonl')
    validate_cases(cases)
    require(Counter(c['split'] for c in cases) == Counter(test=200, ood=100)
            and len({c['case_id'] for c in cases}) == 300 and len({c['source_task_id'] for c in cases}) == 300,
            'Frozen source population differs')
    reject_example_overlap(cases, reader.json('public/examples.json'))
    by_case = {c['case_id']:c for c in cases}
    predictions = {condition:reader.rows('predictions/'+condition+'/predictions.jsonl') for condition in CONDITIONS}
    for rows in predictions.values():
        require(len(rows) == 300 and {r['case_id'] for r in rows} == set(by_case), 'Prediction population differs')
    gold_rows = reader.rows('sealed/gold.jsonl')
    require(len(gold_rows) == 300 and {r['case_id'] for r in gold_rows} == set(by_case), 'Gold population differs')
    raw_gold = {r['case_id']:r['findings'] for r in gold_rows}
    gold = {cid:validate_findings(value, by_case[cid]['public']) for cid,value in raw_gold.items()}
    scores = {}
    for condition in CONDITIONS:
        scores[condition] = {}
        for split in ('test', 'ood'):
            subset = [c for c in cases if c['split'] == split]; ids = {c['case_id'] for c in subset}
            ordered = {c['case_id']:[gold[c['case_id']][r['id']] for r in c['public']['requirements']] for c in subset}
            scores[condition][split] = score_predictions(subset, ordered, [r for r in predictions[condition] if r['case_id'] in ids])
    equal(scores, reader.json('scores/scores.json'), 'all diagnostic scores')
    losses = {condition:reader.rows('scores/'+condition+'-loss.jsonl') for condition in CONDITIONS[3:]}
    statistics = analysis.analyze(cases, scores, losses, protocol['statistics'])
    equal(statistics, reader.json('analysis/statistics.json'), 'all four registered comparisons')
    assignments = reader.json('sealed/panel-assignment.json')
    require(set(assignments) == set(by_case), 'Scenario assignment population differs')
    references = reader.rows('sealed/references.jsonl')
    evidence, scenarios, slices = {}, {}, 0
    for condition in CONDITIONS:
        assessment = score_evidence_support(cases, tasks, references, raw_gold, predictions[condition])
        equal(assessment, reader.json('analysis/'+condition+'-evidence.json'), 'complete evidence assessment '+condition)
        evidence[condition] = analysis.project(assessment['summaries'])
        scenarios[condition] = {}
        for split in ('test', 'ood'):
            require(Counter(assignments[c['case_id']] for c in cases if c['split'] == split) == Counter(protocol['panel_quotas'][split]),
                    'Frozen scenario quotas differ')
            scenarios[condition][split] = {}
            for scenario in protocol['panel_quotas'][split]:
                subset = [c for c in cases if c['split'] == split and assignments[c['case_id']] == scenario]
                ids = {c['case_id'] for c in subset}
                scenarios[condition][split][scenario] = analysis.project(score_predictions(
                    subset, {cid:raw_gold[cid] for cid in ids}, [r for r in predictions[condition] if r['case_id'] in ids]))
                slices += 1
    summary = {'scope':protocol['scope'], 'protocol_version':protocol['version'],
               'source_tasks':dict(Counter(c['split'] for c in cases)), 'diagnostics':analysis.project(scores),
               'scenario_diagnostics':scenarios, 'evidence_descriptive':evidence, 'statistics':statistics,
               'full_M1_M8_goal_complete':False, 'full_candidate_evaluation_complete':False,
               'new_closed_loop_or_control_results':False, 'gold_is_programmatic':True, 'human_evaluation':False}
    equal(summary, reader.json('analysis/aggregate-results.json'), 'entire aggregate result tree')
    return {'status':'completed', 'diagnostic_prediction_records_replayed':2700,
            'target_loss_records_used':sum(map(len, losses.values())), 'registered_comparisons_replayed':4,
            'complete_evidence_assessments_replayed':9, 'scenario_condition_split_slices_replayed':slices,
            'entire_aggregate_tree_canonical_equal':True, 'pinned_core_and_analysis_sources_used':True,
            'new_model_calls':0, 'model_or_pickle_loaded':False, 'target_losses_recomputed_by_model':False,
            'independent_second_oracle_claim':False, 'full_goal_complete':False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--expected-sha256', required=True, help='Captured private final-data archive checksum')
    p.add_argument('--out', type=Path, required=True, help='Fresh private replay workspace')
    a = p.parse_args()
    require(not a.out.exists(), 'Choose a new replay workspace')
    verified = verify(a.archive, a.expected_sha256)
    require(verified['kind'] == 'private_limited_followup_data', 'Final data archive required')
    a.out.mkdir(parents=True, exist_ok=False)
    try:
        with tarfile.open(a.archive, 'r:*') as handle:
            reader = Reader(handle); protocol = reader.json('protocol.lock.json')
            analysis = pinned_sources(protocol, a.out, Path(__file__).resolve().parents[1])
            receipt = recompute(reader, protocol, analysis)
        (a.out/'aggregate-verification.json').write_text(json.dumps(receipt, indent=2)+'\n', encoding='utf-8')
        private = {**receipt, 'private_archive_sha256':verified['archive_sha256'],
                   'private_protocol_hash':protocol['lock_hash'], 'archive_members_hash_verified':verified['members']}
        (a.out/'private-verification.json').write_text(json.dumps(private, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(receipt))
    except BaseException as exc:
        (a.out/'failure.json').write_text(json.dumps({'status':'failed', 'error_type':type(exc).__name__,
             'new_model_calls':0, 'automatic_retry':False})+'\n', encoding='utf-8')
        raise


if __name__ == '__main__':
    main()
