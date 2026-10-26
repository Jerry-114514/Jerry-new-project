"""Recompute aggregate M5 tables from an externally hash-bound scoring archive.

No model, raw gold or raw prediction is loaded. Full protocol/model verification
is a separate frozen entry; this projection does not certify M8 completion.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import statistics
import sys
import tarfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.core import digest

CONDITIONS = ['A', 'B', 'C'] + [f'{name}-seed-{seed}' for name in ('D', 'E') for seed in (0, 1, 2)]
SPLITS = ('test', 'ood')
STATUSES = ('satisfied', 'violated', 'unknown')


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def close(left, right):
    if not math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12):
        raise ValueError('Stored aggregate differs from scored-record arithmetic')


def fraction(numerator, denominator):
    return {'numerator': numerator, 'denominator': denominator,
            'rate': numerator / denominator if denominator else None}


def project(archive, expected_sha):
    if len(expected_sha) != 64 or any(c not in '0123456789abcdef' for c in expected_sha) or sha(archive) != expected_sha:
        raise ValueError('Scoring archive differs from the previously recorded source SHA256')
    with tarfile.open(archive, 'r:') as handle:
        members = handle.getmembers()
        if len(members) != len({m.name for m in members}) or any(not m.isfile() for m in members):
            raise ValueError('Duplicate or nonregular archive member')
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts or str(path) != member.name or '\\' in member.name or ':' in member.name:
                raise ValueError('Unsafe archive member')
        def read(name):
            return json.load(handle.extractfile(name))
        manifest = read('manifest.json')
        if manifest['kind'] != 'frozen_diagnostic_reveal' or manifest['status'] != 'completed' or manifest['scope'] != 'formal' \
                or manifest['test_loss_injected'] is not False or manifest['gold_opened_after_claim'] is not True \
                or manifest['receipt_hash'] != digest({k: v for k, v in manifest.items() if k != 'receipt_hash'}):
            raise ValueError('A complete formal scoring manifest is required')
        if {m.name for m in members} != set(manifest['files_sha256']) | {'manifest.json'}:
            raise ValueError('Scoring archive file population differs')
        for member in members:
            if member.name != 'manifest.json':
                with handle.extractfile(member) as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != manifest['files_sha256'][member.name]:
                        raise ValueError('Scoring member hash differs')
        scores, stored_losses = read('scores.json'), read('losses.json')
        if set(scores) != set(CONDITIONS) or set(stored_losses) != set(CONDITIONS[3:]):
            raise ValueError('All registered conditions are required')
        population, losses = None, {}
        for condition in CONDITIONS[3:]:
            with handle.extractfile(condition + '-loss.jsonl') as stream:
                rows = [json.loads(line) for line in stream if line.strip()]
            current = {}
            grouped = defaultdict(list)
            for row in rows:
                cid = row['case_id']
                if cid in current or row['split'] not in SPLITS or type(row['target_tokens']) is not int or row['target_tokens'] < 1 \
                        or type(row['loss_sum']) not in (int, float) or not math.isfinite(row['loss_sum']) or row['loss_sum'] < 0:
                    raise ValueError('Malformed or duplicate loss record')
                current[cid] = (row['source_task_id'], row['split'], row['target_tokens'])
                grouped[row['split']].append(row)
            if population is not None and current != population:
                raise ValueError('The six loss populations or target token counts differ')
            population = current
            losses[condition] = {}
            for split in SPLITS:
                group = grouped[split]
                total, tokens = sum(r['loss_sum'] for r in group), sum(r['target_tokens'] for r in group)
                if not group or tokens == 0:
                    raise ValueError('Empty heldout loss split')
                stored = stored_losses[condition][split]
                close(total, stored['loss_sum'])
                if tokens != stored['target_tokens']:
                    raise ValueError('Loss denominator differs')
                close(total / tokens, stored['loss'])
                losses[condition][split] = {'loss_sum': total, 'target_tokens': tokens, 'loss': total / tokens,
                    'cases': len(group), 'source_task_groups': len({r['source_task_id'] for r in group})}
        aggregates = {}
        for condition in CONDITIONS:
            aggregates[condition] = {}
            for split in SPLITS:
                value, grouped, seen = scores[condition][split], defaultdict(list), set()
                counts = dict(value['counts'])
                # The frozen scorer uses Counter; an untouched counter is an
                # omitted zero, including when every model output is invalid.
                for key in ('parsed_evidence_items', 'reference_valid_items', 'nonempty_reference_items',
                            'unsafe_opportunities', 'unsafe_satisfied'):
                    counts.setdefault(key, 0)
                if any(type(n) is not int or n < 0 for n in counts.values()):
                    raise ValueError('Counts must be nonnegative integers')
                for row in value['records']:
                    cid, error = row['case_id'], row['normalized_error_rate']
                    if cid in seen or cid not in population or population[cid][:2] != (row['source_task_id'], split) \
                            or not math.isfinite(error) or not 0 <= error <= 1:
                        raise ValueError('Scored-case population differs from loss population')
                    seen.add(cid)
                    grouped[row['source_task_id']].append(error)
                expected = {cid for cid, row in population.items() if row[1] == split}
                if seen != expected or len(seen) != counts['cases'] or len(grouped) != value['source_task_groups'] \
                        or set(grouped) != set(value['per_task_error_rate']):
                    raise ValueError('Source/task coverage differs')
                means = {source: sum(errors) / len(errors) for source, errors in grouped.items()}
                for source, mean in means.items():
                    close(mean, value['per_task_error_rate'][source])
                error = sum(means.values()) / len(means)
                close(error, value['task_mean_error_rate'])
                confusion = value['confusion']
                if any(r['gold'] not in STATUSES or r['predicted'] not in (*STATUSES, 'invalid') \
                       or type(r['count']) is not int or r['count'] < 0 for r in confusion):
                    raise ValueError('Malformed state confusion counts')
                if sum(r['count'] for r in confusion) != counts['status_items'] \
                        or sum(r['count'] for r in confusion if r['gold'] != r['predicted']) != counts['normalized_errors']:
                    raise ValueError('Confusion totals differ from error counts')
                if not 0 <= counts['strict_valid'] <= counts['normalized_valid'] <= counts['cases'] \
                        or not 0 <= counts['reference_valid_items'] <= counts['parsed_evidence_items'] <= counts['status_items'] \
                        or not 0 <= counts['nonempty_reference_items'] <= counts['parsed_evidence_items'] \
                        or not 0 <= counts['unsafe_satisfied'] <= counts['unsafe_opportunities']:
                    raise ValueError('Metric numerator exceeds denominator')
                recalls = {label: fraction(sum(r['count'] for r in confusion if r['gold'] == r['predicted'] == label),
                                          sum(r['count'] for r in confusion if r['gold'] == label)) for label in STATUSES}
                aggregates[condition][split] = {'task_mean_error_rate': error, 'source_task_groups': len(means), 'counts': counts,
                    'strict_interface': fraction(counts['strict_valid'], counts['cases']),
                    'normalized_interface': fraction(counts['normalized_valid'], counts['cases']),
                    'reference_index_validity': fraction(counts['reference_valid_items'], counts['parsed_evidence_items']),
                    'nonempty_references': fraction(counts['nonempty_reference_items'], counts['parsed_evidence_items']),
                    'unsafe_satisfied': fraction(counts['unsafe_satisfied'], counts['unsafe_opportunities']),
                    'state_recall': recalls, 'confusion': confusion}
    comparisons = {}
    for split in SPLITS:
        d = [aggregates[f'D-seed-{seed}'][split]['task_mean_error_rate'] for seed in range(3)]
        e = [aggregates[f'E-seed-{seed}'][split]['task_mean_error_rate'] for seed in range(3)]
        baseline = aggregates['B'][split]['task_mean_error_rate']
        paired_ce = [losses[f'E-seed-{seed}'][split]['loss'] - losses[f'D-seed-{seed}'][split]['loss'] for seed in range(3)]
        comparisons[split] = {'B_error': baseline, 'D_mean_error': statistics.mean(d), 'E_mean_error': statistics.mean(e),
            'D_seed_sample_sd': statistics.stdev(d), 'E_seed_sample_sd': statistics.stdev(e),
            'rq1_D_minus_B_point': statistics.mean(d) - baseline,
            'relative_error_reduction_descriptive': 1 - statistics.mean(d) / baseline if baseline else None,
            'rq4_E_minus_D_loss_per_seed': paired_ce, 'rq4_E_minus_D_loss_mean': statistics.mean(paired_ce)}
    return {'kind': 'completed_m5_aggregate_projection', 'scoring_archive_sha256': expected_sha,
            'protocol_hash': manifest['protocol_hash'], 'binding_hash': manifest['model_binding_hash'],
            'diagnostic_receipt_hash': manifest['receipt_hash'], 'prediction_seal_hash': manifest['prediction_seal_hash'],
            'source_files_sha256': manifest['files_sha256'], 'aggregates': aggregates, 'losses': losses, 'descriptive_comparisons': comparisons,
            'driver_sha256': sha(Path(__file__)), 'raw_gold_files_read': False, 'raw_predictions_read': False,
            'scored_case_and_loss_arithmetic_recomputed': True, 'full_model_binding_verifier_executed_by_this_script': False,
            'evidence_semantic_support_scored': False, 'confirmatory_p_values_or_intervals_computed': False, 'm8_complete': False}


def report(summary):
    a, losses, comparisons = summary['aggregates'], summary['losses'], summary['descriptive_comparisons']
    def pct(value):
        return 'null' if value is None else f'{value * 100:.2f}%'
    def cell(value):
        return f"{value['numerator']}/{value['denominator']} ({pct(value['rate'])})"
    lines = ['# M5正式诊断结果：描述性汇总', '',
        '本报告从已完成评分的源SHA绑定归档重算，不加载模型、原始gold或原始预测，不修改任何冻结设置。', '',
        '## 状态错误率', '',
        f"先对同一源任务的视图错误率取平均，再对源任务等权。test为{a['B']['test']['source_task_groups']}源/{a['B']['test']['counts']['cases']}视图，OOD为{a['B']['ood']['source_task_groups']}源/{a['B']['ood']['counts']['cases']}视图；视图和三个训练种子不扩大独立任务数。主比较为B对三个固定D种子的平均值。", '',
        '|条件|test源任务平均错误率|OOD源任务平均错误率|', '|---|---:|---:|']
    for condition in CONDITIONS:
        lines.append(f"|{condition}|{pct(a[condition]['test']['task_mean_error_rate'])}|{pct(a[condition]['ood']['task_mean_error_rate'])}|")
    for name in ('D', 'E'):
        lines.append(f"|{name}三个种子均值|{pct(comparisons['test'][name + '_mean_error'])}|{pct(comparisons['ood'][name + '_mean_error'])}|")
    lines += ['', 'C是预登记的公开规格规则基线，其结果完整保留。各种子差异不能通过挑选最佳种子隐藏；闭环模型须保持测试前锁定的选择，不根据这份报告改选。', '',
        '## 格式与证据引用', '',
        '接口有效按案例计；引用有效和非空引用按已解析要求计。空引用也可通过引用索引存在性检查，因此有效率必须与非空比例及解析失败一起读。这里只评估引用索引是否存在，没有自动评估自然语言证据语义支持，也不声称人工审核。']
    for split in SPLITS:
        lines += ['', f'### {split}', '', '|条件|严格接口有效|归一化接口有效|引用索引有效|非空引用|', '|---|---:|---:|---:|---:|']
        for condition in CONDITIONS:
            value = a[condition][split]
            lines.append('|' + '|'.join([condition, *[cell(value[key]) for key in ('strict_interface', 'normalized_interface', 'reference_index_validity', 'nonempty_references')]]) + '|')
    lines += ['', '## 诊断风险与类别召回', '',
        '不安全satisfied的机会分母是gold为violated或unknown的硬要求；invalid预测仍计入状态错误和格式失败，但不会伪装为satisfied。下面是要求条目计数的描述，不能替代M6执行回归风险或RQ2/RQ3因果比较。分母为0时率为null。']
    for split in SPLITS:
        lines += ['', f'### {split}', '', '|条件|不安全satisfied/机会|unknown召回|violated召回|', '|---|---:|---:|---:|']
        for condition in CONDITIONS:
            value = a[condition][split]
            lines.append('|' + '|'.join([condition, cell(value['unsafe_satisfied']), cell(value['state_recall']['unknown']), cell(value['state_recall']['violated'])]) + '|')
    lines += ['', '## 六模型目标token加权交叉熵', '',
        '逐案例loss_sum与target_tokens重新求和并与原losses.json核对；六个模型保留相同案例、源任务、split及逐例目标token数量。E-D为预登记差异方向，负值有利于Plateau。', '',
        '|种子|D test|E test|E-D test|D OOD|E OOD|E-D OOD|', '|---|---:|---:|---:|---:|---:|---:|']
    for seed in range(3):
        values = []
        for split in SPLITS:
            d, e = losses[f'D-seed-{seed}'][split]['loss'], losses[f'E-seed-{seed}'][split]['loss']
            values += [f'{d:.6f}', f'{e:.6f}', f'{e-d:+.6f}']
        lines.append('|' + '|'.join([str(seed), *values]) + '|')
    lines += ['', f"三个固定种子的E-D平均值：test {comparisons['test']['rq4_E_minus_D_loss_mean']:+.6f}，OOD {comparisons['ood']['rq4_E_minus_D_loss_mean']:+.6f}。这些是条件点估计，未计算确认性p值或区间。", '',
        '## 解释边界与剩余工作', '',
        '全部失败保留，strict/normalized计数、混淆矩阵和全部种子在summary.json中保存。这里的三种子样本标准差是描述性分解，不是训练种子总体置信区间。', '',
        '本轮采用程序标签，结论仅限明确编码规格。输入匹配测试、共享生成器、保留近邻、参考覆盖与抽样独立性限制仍须报告；不外推到开放自然语言需求、任意环境安全或算法创新。', '',
        '完整任务/操作族分层推断、固定17项次要检验族及Holm校正由M8冻结统计入口完成。本报告不验收M6闭环、M7控制、完整复现或最终报告；M5诊断改进不直接证明闭环收益，各阶段状态以其完成凭据为准。', '',
        '此脚本验证归档和重算已评分记录，不替代持有实际模型与协议资产时的完整冻结模型绑定验证。', '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--expected-sha256', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    summary = project(args.archive, args.expected_sha256)
    args.out.mkdir(parents=True, exist_ok=False)
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    (args.out / 'REPORT.md').write_text(report(summary), encoding='utf-8', newline='\n')
    checksums = {name: sha(args.out / name) for name in ('summary.json', 'REPORT.md')}
    (args.out / 'checksums.json').write_text(json.dumps(checksums, indent=2, sort_keys=True) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps({'descriptive_comparisons': summary['descriptive_comparisons'], 'm8_complete': False}))


if __name__ == '__main__':
    main()
