"""Descriptive M7 projection from completed, externally hash-bound archives.

No model, gold or reference loading; no additional hypothesis tests. Interrupted
attempts remain separate costs, never additional independent observations.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from postformal_evidence_support import BoundArchive, completed_m7
from summarize_formal_execution import fraction, sha
from intentlab.execution_auxiliary import candidate_summary, common_feasibility


def project(path, expected, protocol, binding, interrupted=None, interrupted_sha=None):
    root = Path(__file__).resolve().parents[1]
    with BoundArchive(path, expected) as archive:
        interaction, reveal = completed_m7(archive, protocol, binding)
        status = archive.json('supervisor-status.json')
        helper_hashes = {}
        for name in ('intentlab/core.py', 'intentlab/execution_auxiliary.py'):
            frozen = subprocess.check_output(['git', 'show', status['runtime_commit'] + ':' + name], cwd=root)
            if (root / name).read_text(encoding='utf-8') != frozen.decode():
                raise ValueError('Projection helper differs from frozen runtime')
            helper_hashes[name] = hashlib.sha256(frozen).hexdigest()
        raw = archive.rows('interactions/interactions.jsonl')
        scored = archive.rows('reveal/runs.jsonl')
        stored = archive.json('reveal/summary.json')
        raw_bytes = archive.raw('interactions/interactions.jsonl')
    conditions = interaction['conditions']
    if len(interaction['ordered_task_ids']) != 300 or any(c['hard_guard'] is not True for c in conditions.values()):
        raise ValueError('Expected complete population and hard checks in every M7 condition')
    identities, seen = {}, set()
    added = {'metrics', 'initial_metrics', 'feasible_at_repair_start', 'repair_introduced_hard_violations',
             'candidate_audit', 'offline_metrics_pending'}
    for before, after in zip(raw, scored):
        if before['offline_metrics_pending'] is not True or after['offline_metrics_pending'] is not False \
                or {k:v for k,v in before.items() if k not in added} != {k:v for k,v in after.items() if k not in added}:
            raise ValueError('Scoring changed an interaction')
        key = after['condition'], after['task_id']
        identity = after['source_task_id'], after['split'], after['family']
        if key in seen or key[0] not in conditions or identity[1] not in ('test', 'ood'):
            raise ValueError('Duplicate or unexpected condition/task')
        if key[1] in identities and identities[key[1]] != identity:
            raise ValueError('Source grouping differs between conditions')
        seen.add(key); identities[key[1]] = identity
    if set(identities) != set(interaction['ordered_task_ids']) or len({v[0] for v in identities.values()}) != 300 \
            or seen != {(c,t) for c in conditions for t in identities}:
        raise ValueError('Expected the same 300 source tasks in all six conditions')
    aggregates = {}
    for condition in conditions:
        aggregates[condition] = {}
        for split, size in (('test',200),('ood',100)):
            rows = [r for r in scored if r['condition']==condition and r['split']==split]
            if len(rows)!=size or any(type(r['feasible_at_repair_start']) is not bool for r in rows):
                raise ValueError('Split population or feasibility invalid')
            feasible = [r for r in rows if r['feasible_at_repair_start']]
            counts = {'runs':size,'source_task_groups':len({r['source_task_id'] for r in rows}),
                'compliant_successes':sum(r['metrics']['compliant_success'] for r in rows),
                'errors':sum(r['status']=='error' for r in rows),'feasible_runs':len(feasible),
                'initially_irreversible_runs':size-len(feasible),
                'feasible_compliant_successes':sum(r['metrics']['compliant_success'] for r in feasible),
                'repair_introduced_violation_runs':sum(bool(r['repair_introduced_hard_violations']) for r in rows),
                'charged_tokens':sum(r['model_pool']['shared_token_ledger']['charged_tokens'] for r in rows)}
            if counts != stored[condition]['splits'][split] or stored[condition]['raw_audit']['verified'] is not True:
                raise ValueError('Counts differ from the original sealed summary')
            candidates = candidate_summary(rows); candidates.pop('per_source_eligible_counts')
            cost = {k:sum(r['cost'][k] for r in rows) for k in rows[0]['cost']}
            seconds = sum(r['interaction_seconds'] for r in rows)
            if any(type(v) is not int or v<0 for v in cost.values()) or not math.isfinite(seconds) or seconds<0:
                raise ValueError('Invalid cost or timing')
            aggregates[condition][split] = {'counts':counts,'candidate_opportunities':candidates,
                'initially_feasible_success':fraction(counts['feasible_compliant_successes'],len(feasible)),
                'cost_totals':cost,'token_ledger_totals':{k:sum(r['model_pool']['shared_token_ledger'][k] for r in rows)
                    for k in ('calls','charged_tokens','denied_calls','failed_reservations','known_prompt_tokens','known_completion_tokens')},
                'accepted_repair_attempts':sum(c['accepted'] is True for r in rows for c in r['candidate_audit']['candidates']),
                'repair_intensity_distributions':{key:dict(Counter(str(h['intensity_decision'][key])
                    for r in rows for h in r['history'] if h['phase']=='repair'))
                    for key in ('requested_k','selected_root_count','expanded_target_count')},
                'candidate_reasons':dict(Counter(c['reason'].split(':',1)[0] for r in rows for c in r['candidate_audit']['candidates'])),
                'interaction_seconds_sum':seconds}
    recovery_cost = None
    if 'recovery' in interaction:
        recovery = interaction['recovery']
        if interrupted is None or interrupted_sha != recovery['interrupted_attempt_archive_sha256']:
            raise ValueError('Recovered M7 requires its separately preserved interrupted archive')
        with BoundArchive(interrupted,interrupted_sha) as old:
            old_raw = old.raw('interactions/interactions.jsonl')
            old_rows = old.rows('interactions/interactions.jsonl')
        prefix = b''.join(old_raw.splitlines(keepends=True)[:900])
        if hashlib.sha256(prefix).hexdigest()!=recovery['retained_prefix_sha256'] or not raw_bytes.startswith(prefix) \
                or len(old_rows)!=939 or any(r['condition']!='dynamic-k' for r in old_rows[900:]):
            raise ValueError('Retained prefix or preserved interrupted population changed')
        recovery_cost = {'archive_sha256':interrupted_sha,'original_records':939,'prefix_records_retained':900,
            'partial_records_preserved_separately':39,'additional_charged_tokens':sum(
                r['model_pool']['shared_token_ledger']['charged_tokens'] for r in old_rows[900:]),
            'partial_records_counted_in_primary_population':False,'retained_prefix_byte_identical':True}
    final = {(r['condition'],r['task_id']):r['final_state'] for r in scored}
    targets = {(r['condition'],r['task_id']):[
        {k:h['intensity_decision'][k] for k in ('roots','target')}
        for h in r['history'] if h['phase']=='repair'] for r in scored}
    primary_tokens = sum(v['counts']['charged_tokens'] for a in aggregates.values() for v in a.values())
    return {'kind':'aggregate_formal_m7_projection','protocol_hash':protocol,'binding_hash':binding,
        'archive_sha256':expected,'archive_bytes':Path(path).stat().st_size,'ablation_receipt_hash':reveal['receipt_hash'],
        'runtime_commit':status['runtime_commit'],'script_sha256':sha(__file__),'helper_sha256':helper_hashes,
        'interaction_records':len(raw),'scored_records':len(scored),'source_task_groups':300,
        'conditions':conditions,'aggregates':aggregates,'common_initial_feasibility':{
            c+'/'+s:common_feasibility(scored,c,'dynamic-k',s) for c in conditions if c!='dynamic-k' for s in ('test','ood')},
        'all_final_states_identical_across_conditions':all(final[(c,t)]==final[('dynamic-k',t)] for c in conditions for t in identities),
        'all_effective_repair_targets_identical_across_conditions':all(targets[(c,t)]==targets[('dynamic-k',t)] for c in conditions for t in identities),
        'all_actual_repair_attempts_selected_one_root':all(h['intensity_decision']['selected_root_count']==1
            for r in scored for h in r['history'] if h['phase']=='repair'),
        'condition_timings':interaction['condition_timings'],'recovery_cost':recovery_cost,
        'primary_population_charged_tokens':primary_tokens,
        'total_charged_tokens_including_interrupted_attempt':primary_tokens+(recovery_cost['additional_charged_tokens'] if recovery_cost else 0),
        'hypothesis_tests_added':0,'raw_gold_or_reference_files_opened':False,
        'inference_peak_gpu_memory_available':False,'m8_complete':False}


def report(d):
    lines=['# M7六条件消融：完整成本与候选审计','','描述性复算，不新增确认性检验。全部1800条结果保留；各条件为同一300源任务的配对执行。','',
        '|条件|集合|成功/全部|错误|初始不可逆|计费token|修复尝试|完整候选|合规候选|接受|',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for c,groups in d['aggregates'].items():
        for split,v in groups.items():
            n=v['counts'];a=v['candidate_opportunities']['counts']
            lines.append(f"|{c}|{split}|{n['compliant_successes']}/{n['runs']}|{n['errors']}|{n['initially_irreversible_runs']}|{n['charged_tokens']}|{a['attempts']}|{a['complete_proposals']}|{a['complete_compliant_candidates']}|{v['accepted_repair_attempts']}|")
    lines+=['','初始可行和两条件共同可行分母、调用账本、候选拒绝类别及条件耗时见summary.json。无合规候选时误拦截率为null。初始提案并不受修复硬检查保护；各组仍保留共同接受规则，不能将零新增已提交违规当作无检查安全性证明。',
        '',f"主总体计费token：{d['primary_population_charged_tokens']}；含中断尝试总计：{d['total_charged_tokens_including_interrupted_attempt']}。这是token账本，不是AutoDL实际账单。",
        '', '中断前已完成三组固定k的900条原始字节保持。被中断动态组的39条单独保留并计入额外成本，随后整个动态条件重新执行，不将其计为新增独立任务。条件耗时不含全部中断、停机或备份等待时间；部分权重传输与运行重叠，不能将其差异当作纯策略速度效应。',
        '', 'requested_k、实际selected_root_count与依赖扩展后的expanded_target_count分别统计在summary.json中。请求上限不同不保证实际修复目标不同；应据这些机会分母解释零增益，不把控制器参数不同自动等同于有效干预不同。',
        '',f"六条件最终文件/事件状态逐任务相同：{d['all_final_states_identical_across_conditions']}。成功率、轨迹相同只描述本批执行，不能证明方法一般等效。正式比较区间和p值另见注册统计表。",
        '',f"实际修复根要求及依赖扩展目标的逐任务序列相同：{d['all_effective_repair_targets_identical_across_conditions']}；各次实际尝试均只选中一个根要求：{d['all_actual_repair_attempts_selected_one_root']}。应依据实际干预分离程度解释requested_k的变化。目标未分离时，不能据此检验多根修复场景下动态强度的收益或宣称控制器一般无效。",
        '', '未记录M7正式推理峰值显存，不以训练或恢复探针补填。共享生成器、跨划分近邻、候选稀少和参考程序局限保留。本汇总不证明M2数据独立性，不等于公共复现或M8完成。','']
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('archive','out','interrupted-archive'):p.add_argument('--'+name,type=Path,required=name!='interrupted-archive')
    for name in ('expected-sha256','protocol-hash','binding-hash','interrupted-sha256'):p.add_argument('--'+name,required=name!='interrupted-sha256')
    a=p.parse_args()
    if a.out.exists():raise FileExistsError('Use a fresh output directory')
    d=project(a.archive,a.expected_sha256,a.protocol_hash,a.binding_hash,a.interrupted_archive,a.interrupted_sha256)
    a.out.mkdir(parents=True,exist_ok=False)
    (a.out/'summary.json').write_text(json.dumps(d,indent=2,sort_keys=True,allow_nan=False)+'\n',encoding='utf-8',newline='\n')
    (a.out/'REPORT.md').write_text(report(d),encoding='utf-8',newline='\n')
    (a.out/'checksums.json').write_text(json.dumps({n:sha(a.out/n) for n in ('summary.json','REPORT.md')},indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'status':'completed','records':d['interaction_records'],'charged_tokens':d['total_charged_tokens_including_interrupted_attempt'],'m8_complete':False}))


if __name__=='__main__':main()
