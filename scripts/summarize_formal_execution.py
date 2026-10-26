"""Recompute aggregate M6 evidence from an externally hash-bound sealed archive.

Reads sealed interactions and offline scores, never gold, reference files or
models. This descriptive projection does not replace frozen verification or M8.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tarfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.core import digest
from intentlab.execution_auxiliary import candidate_summary, common_feasibility

CONDITIONS = {'P1': {'policy': 'fixed-full', 'hard_guard': False},
              'P2': {'policy': 'dynamic-k', 'hard_guard': False},
              'P3': {'policy': 'fixed-full', 'hard_guard': True},
              'P4': {'policy': 'dynamic-k', 'hard_guard': True}}
SPLITS = ('test', 'ood')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fraction(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'rate': numerator / denominator if denominator else None}


def project(archive, expected_sha):
    if len(expected_sha) != 64 or any(c not in '0123456789abcdef' for c in expected_sha) or sha(archive) != expected_sha:
        raise ValueError('Archive differs from the externally recorded SHA256')
    with tarfile.open(archive, 'r:') as handle:
        members = handle.getmembers()
        if len(members) != len({m.name for m in members}) or any(not m.isfile() for m in members):
            raise ValueError('Duplicate or nonregular archive member')
        for member in members:
            name = PurePosixPath(member.name)
            if name.is_absolute() or '..' in name.parts or str(name) != member.name or '\\' in member.name or ':' in member.name:
                raise ValueError('Unsafe archive member')
        def read(name):
            return json.load(handle.extractfile(name))
        def rows(name):
            return [json.loads(line) for line in handle.extractfile(name) if line.strip()]
        supervisor = read('supervisor-status.json')
        if supervisor['kind'] != 'frozen_m6_execution_supervisor' or supervisor['status'] != 'completed' or supervisor['m6_complete'] is not True \
                or [r['action'] for r in supervisor['stages']] != ['interact', 'verify', 'reveal', 'verify-reveal'] \
                or any(r['status'] != 'completed' or r['exit_code'] != 0 for r in supervisor['stages']):
            raise ValueError('All four completed M6 stages are required')
        helper_hashes = {}
        root = Path(__file__).resolve().parents[1]
        for path in ('intentlab/core.py', 'intentlab/execution_auxiliary.py'):
            frozen = subprocess.check_output(['git', 'show', supervisor['runtime_commit'] + ':' + path], cwd=root)
            if (root / path).read_text(encoding='utf-8') != frozen.decode('utf-8'):
                raise ValueError('Projection helper differs from the declared frozen source')
            helper_hashes[path] = hashlib.sha256(frozen).hexdigest()
        manifests = {}
        for directory, kind, state, seal in [('interactions', 'frozen_execution_interactions', 'sealed', 'seal_hash'),
                                            ('reveal', 'frozen_execution_reveal', 'completed', 'receipt_hash')]:
            manifest = read(directory + '/manifest.json')
            if manifest['kind'] != kind or manifest['status'] != state or manifest['scope'] != 'formal' \
                    or manifest['protocol_hash'] != supervisor['protocol_hash'] or manifest['model_binding_hash'] != supervisor['binding_hash'] \
                    or manifest[seal] != digest({k: v for k, v in manifest.items() if k != seal}):
                raise ValueError('Changed or incomplete formal manifest')
            prefix = directory + '/'
            actual = {}
            for member in members:
                if member.name.startswith(prefix) and member.name != prefix + 'manifest.json':
                    with handle.extractfile(member) as stream:
                        actual[member.name[len(prefix):]] = hashlib.file_digest(stream, 'sha256').hexdigest()
            if actual != manifest['files_sha256']:
                raise ValueError('Sealed member population or bytes changed')
            manifests[directory] = manifest
        interaction, reveal = manifests['interactions'], manifests['reveal']
        if interaction['conditions'] != CONDITIONS or interaction['injected_pool'] is not False \
                or interaction['offline_references_opened'] is not False or reveal['references_accessed_after_claim'] is not True \
                or reveal['interaction_seal_hash'] != interaction['seal_hash'] or reveal['receipt_hash'] != supervisor['execution_receipt_hash']:
            raise ValueError('Condition, isolation or upstream seal mismatch')
        raw, scored, stored = rows('interactions/interactions.jsonl'), rows('reveal/runs.jsonl'), read('reveal/summary.json')
    if len(raw) != len(scored) or len(scored) != 1200 or len(interaction['ordered_task_ids']) != 300:
        raise ValueError('Exactly 1200 paired records and 300 task contracts required')
    added = {'metrics', 'initial_metrics', 'feasible_at_repair_start', 'repair_introduced_hard_violations',
             'candidate_audit', 'offline_metrics_pending'}
    identities, seen = {}, set()
    for before, after in zip(raw, scored):
        if before['offline_metrics_pending'] is not True or after['offline_metrics_pending'] is not False \
                or {k: v for k, v in before.items() if k not in added} != {k: v for k, v in after.items() if k not in added}:
            raise ValueError('Scoring modified sealed interactions')
        key = (after['condition'], after['task_id'])
        identity = (after['source_task_id'], after['split'], after['family'])
        if key in seen or after['condition'] not in CONDITIONS or after['split'] not in SPLITS:
            raise ValueError('Duplicate or unexpected interaction')
        seen.add(key)
        if after['task_id'] in identities and identities[after['task_id']] != identity:
            raise ValueError('Task grouping changed between conditions')
        identities[after['task_id']] = identity
        if type(after['metrics']['compliant_success']) is not bool or type(after['feasible_at_repair_start']) is not bool \
                or not isinstance(after['repair_introduced_hard_violations'], list) or not isinstance(after['analyzer_errors'], list):
            raise ValueError('Explicit boolean truth, attribution and error records required')
    if set(identities) != set(interaction['ordered_task_ids']) or seen != {(c, t) for c in CONDITIONS for t in identities} \
            or len({v[0] for v in identities.values()}) != 300:
        raise ValueError('Complete identical source population required in every condition')
    aggregates = {}
    for condition in CONDITIONS:
        aggregates[condition] = {}
        for split, expected_count in (('test', 200), ('ood', 100)):
            group = [r for r in scored if r['condition'] == condition and r['split'] == split]
            feasible = [r for r in group if r['feasible_at_repair_start']]
            if len(group) != expected_count:
                raise ValueError('Frozen split size differs')
            counts = {'runs': len(group), 'source_task_groups': len({r['source_task_id'] for r in group}),
                'compliant_successes': sum(r['metrics']['compliant_success'] for r in group),
                'errors': sum(r['status'] == 'error' for r in group), 'feasible_runs': len(feasible),
                'initially_irreversible_runs': len(group) - len(feasible),
                'feasible_compliant_successes': sum(r['metrics']['compliant_success'] for r in feasible),
                'repair_introduced_violation_runs': sum(bool(r['repair_introduced_hard_violations']) for r in group),
                'charged_tokens': sum(r['model_pool']['shared_token_ledger']['charged_tokens'] for r in group)}
            if counts != stored[condition]['splits'][split] or stored[condition]['raw_audit']['verified'] is not True:
                raise ValueError('Recomputed counts differ from frozen summary or its audit')
            candidates = candidate_summary(group)
            candidates.pop('per_source_eligible_counts')  # Never export task identities.
            totals = {k: sum(r['cost'][k] for r in group) for k in group[0]['cost']}
            if any(type(v) is not int or v < 0 for v in totals.values()):
                raise ValueError('Nonnegative integer cost counters required')
            ledger_totals = {k: sum(r['model_pool']['shared_token_ledger'][k] for r in group)
                             for k in ('calls', 'charged_tokens', 'denied_calls', 'failed_reservations',
                                       'known_prompt_tokens', 'known_completion_tokens')}
            seconds = sum(r['interaction_seconds'] for r in group)
            if not math.isfinite(seconds) or seconds < 0:
                raise ValueError('Invalid interaction timing')
            aggregates[condition][split] = {'frozen_counts_recomputed': counts,
                'compliant_success': fraction(counts['compliant_successes'], len(group)),
                'repair_introduced_violation': fraction(counts['repair_introduced_violation_runs'], len(group)),
                'initially_feasible_success': fraction(counts['feasible_compliant_successes'], len(feasible)),
                'candidate_opportunities': candidates, 'cost_totals': totals, 'token_ledger_totals': ledger_totals,
                'generation_count': sum(len(r['model_pool']['generations']) for r in group),
                'analyzer_error_runs': sum(bool(r['analyzer_errors']) for r in group),
                'analyzer_error_events': sum(len(r['analyzer_errors']) for r in group),
                'accepted_repair_attempts': sum(c['accepted'] is True for r in group for c in r['candidate_audit']['candidates']),
                'repair_source_groups': len({r['source_task_id'] for r in group if r['candidate_audit']['candidates']}),
                'error_types': dict(Counter(h['error_type'] for r in group for h in r['history'] if h['phase'] == 'error')),
                'candidate_reason_categories': dict(Counter(c['reason'].split(':', 1)[0]
                    for r in group for c in r['candidate_audit']['candidates'])),
                'interaction_seconds_sum': seconds}
    comparisons, common = {}, {}
    for split in SPLITS:
        a, b = aggregates['P1'][split], aggregates['P3'][split]
        c, d = aggregates['P3'][split], aggregates['P4'][split]
        comparisons[split] = {'RQ2_P3_minus_P1_new_violation_rate': b['repair_introduced_violation']['rate'] - a['repair_introduced_violation']['rate'],
            'RQ3_P4_minus_P3_success_rate': d['compliant_success']['rate'] - c['compliant_success']['rate'],
            'P4_minus_P3_charged_tokens': d['frozen_counts_recomputed']['charged_tokens'] - c['frozen_counts_recomputed']['charged_tokens']}
        common['RQ2/' + split] = common_feasibility(scored, 'P1', 'P3', split, 'new_violation')
        common['RQ3/' + split] = common_feasibility(scored, 'P3', 'P4', split)
    final = {(r['condition'], r['task_id']): r['final_state'] for r in scored}
    identical = all(final[(c, tid)] == final[('P1', tid)] for c in CONDITIONS for tid in identities)
    return {'kind': 'aggregate_formal_m6_execution_projection', 'schema_version': 1, 'scope': 'formal',
        'archive_sha256': expected_sha, 'archive_bytes': Path(archive).stat().st_size,
        'runtime_commit': supervisor['runtime_commit'], 'protocol_hash': supervisor['protocol_hash'],
        'binding_hash': supervisor['binding_hash'], 'execution_receipt_hash': reveal['receipt_hash'],
        'interaction_seal_hash': interaction['seal_hash'], 'projection_script_sha256': sha(__file__),
        'frozen_helper_sha256': helper_hashes, 'interaction_records': len(raw), 'scored_records': len(scored),
        'source_task_groups': len(identities), 'scoring_preserved_all_interaction_fields': True,
        'all_final_states_identical_across_conditions': identical, 'aggregates': aggregates,
        'descriptive_comparisons': comparisons, 'common_initial_feasibility': common,
        'condition_timings': interaction['condition_timings'],
        'supervised_stage_seconds': supervisor['finished_unix'] - supervisor['started_unix'],
        'm6_experiment_complete': True, 'm8_complete': False, 'raw_gold_or_references_opened_for_projection': False,
        'hypothesis_tests_added': 0, 'inference_peak_gpu_memory_available': False,
        'limitations': ['Source groups are paired across four conditions; 1200 records are not 1200 independent tasks.',
            'Descriptive arithmetic only; frozen M8 source/family statistics and Holm correction remain pending.',
            'No eligible compliant repair candidate yields a null false-block rate, not zero.',
            'Zero observed committed regressions does not establish zero risk or guard benefit.',
            'This projection does not replay oracle truth, certify semantic independence or replace frozen model verification.',
            'M6 inference peak GPU memory was not recorded in generation usage; training peaks are not substituted.']}


def report(summary):
    a = summary['aggregates']
    lines = ['# M6四组真实模型闭环结果', '',
        '四组各300个合同，共1200条交互和1200条评分；原冻结四阶段均正常完成，实际异机备份由独立凭据核验。下面只重算描述性指标，不生成新的确认性检验。', '',
        '## 成功、失败与新增硬违规', '',
        '|条件|集合|合规成功/全部|错误运行|初始不可逆违规|修复新增硬违规|计费token|',
        '|---|---|---:|---:|---:|---:|---:|']
    for condition in CONDITIONS:
        for split in SPLITS:
            v = a[condition][split]['frozen_counts_recomputed']
            lines.append(f"|{condition}|{split}|{v['compliant_successes']}/{v['runs']}|{v['errors']}|{v['initially_irreversible_runs']}|{v['repair_introduced_violation_runs']}|{v['charged_tokens']}|")
    lines += ['', '错误和不可逆初始违规均保留在全任务结果中；finished不表示合规成功。初始可行子集及两条件共同可行子集另见summary.json，属于描述性辅助分析，不替代主比较分母。', '',
        '## 修复机会与误拦截分母', '',
        '|条件|修复尝试|完整/不完整候选|完整且合规候选|独立硬检查拒绝|已接受新增硬违规候选|',
        '|---|---:|---:|---:|---:|---:|']
    for condition in CONDITIONS:
        values = [a[condition][s] for s in SPLITS]
        c = {k: sum(v['candidate_opportunities']['counts'][k] for v in values) for k in values[0]['candidate_opportunities']['counts']}
        lines.append(f"|{condition}|{c['attempts']}|{c['complete_proposals']}/{c['incomplete_proposals']}|{c['complete_compliant_candidates']}|{sum(v['cost_totals']['hard_rejections'] for v in values)}|{c['accepted_new_hard_violation_candidates']}|")
    attempts = sum(a[c][s]['candidate_opportunities']['counts']['attempts'] for c in CONDITIONS for s in SPLITS)
    accepted = sum(a[c][s]['accepted_repair_attempts'] for c in CONDITIONS for s in SPLITS)
    eligible = sum(a[c][s]['candidate_opportunities']['counts']['complete_compliant_candidates'] for c in CONDITIONS for s in SPLITS)
    complete = sum(a[c][s]['candidate_opportunities']['counts']['complete_proposals'] for c in CONDITIONS for s in SPLITS)
    hard_rejections = sum(a[c][s]['cost_totals']['hard_rejections'] for c in ('P3', 'P4') for s in SPLITS)
    interpretation = []
    if attempts and not accepted:
        interpretation.append('本轮四条件的全部修复尝试均未被接受。')
    if complete and not eligible:
        interpretation.append('完整候选均不合规；误拦截率的合规候选分母为0，应报告null，不能称误拦截率为0%。')
    if hard_rejections and not accepted:
        interpretation.append('P3/P4的独立硬检查实际触发拒绝，但关闭硬检查的P1/P2同样未接受完整候选。')
    interpretation.append('候选机会与已提交违规的描述不证明零风险或硬检查普遍有效/无效；各条件仍须按完整分母解释。')
    lines += ['', ''.join(interpretation), '',
        '## 描述性比较与成本', '',
        '|集合|RQ2新增违规率P3-P1|RQ3成功率P4-P3|P4-P3计费token|', '|---|---:|---:|---:|']
    for split in SPLITS:
        c = summary['descriptive_comparisons'][split]
        lines.append(f"|{split}|{c['RQ2_P3_minus_P1_new_violation_rate']:+.6f}|{c['RQ3_P4_minus_P3_success_rate']:+.6f}|{c['P4_minus_P3_charged_tokens']:+d}|")
    lines += ['', f"四条件最终文件/事件状态逐任务完全相同：{summary['all_final_states_identical_across_conditions']}。该比较不把各条件不同的提示token或拒绝理由当成不同的最终任务状态。", '',
        '|条件|含加载与释放耗时（小时）|', '|---|---:|']
    for condition in CONDITIONS:
        seconds = summary['condition_timings'][condition]['seconds_including_loading_and_release']
        lines.append(f'|{condition}|{seconds / 3600:.4f}|')
    lines += ['', f"M6监督阶段总耗时约{summary['supervised_stage_seconds']/3600:.4f}小时。计费token使用原共同账本，失败与保守计费保持；不将其等同于AutoDL实际账单。模型调用、错误类型、候选拒绝类别及初始可行分母保存在summary.json。", '',
        '## 复算与解释边界', '',
        f"归档SHA256：`{summary['archive_sha256']}`；评分收据：`{summary['execution_receipt_hash']}`。脚本检查外部归档SHA、封存成员、四阶段退出、相同任务群、评分未改动原交互字段，并与冻结summary逐项核对计数。候选及共同可行辅助计算使用与声明冻结源码逐文本核对的函数；不读取gold或参考文件，不加载模型。", '',
        '完整协议/模型绑定及轨迹重放已由原冻结入口完成；本汇总不替代这些验证，不证明语义独立、严格IID或开放业务安全。M2近重复与共享生成器限制保留。', '',
        'M6生成记录没有保存推理峰值显存，不能挪用M4训练峰值。正式源任务/操作族统计、固定17项次要比较Holm校正、M7完整结果、全部资产及最终报告由M8继续验收。本报告不宣称M8完成或统计显著性。', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise FileExistsError('Choose a fresh output directory')
    summary = project(args.archive, args.expected_sha256)
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8', newline='\n')
    (args.out / 'REPORT.md').write_text(report(summary), encoding='utf-8', newline='\n')
    checksums = {name: sha(args.out / name) for name in ('summary.json', 'REPORT.md')}
    (args.out / 'checksums.json').write_text(json.dumps(checksums, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'descriptive_comparisons': summary['descriptive_comparisons'], 'm8_complete': False}))


if __name__ == '__main__':
    main()
