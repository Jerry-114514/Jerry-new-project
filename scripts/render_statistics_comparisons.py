"""Render all registered comparisons from hash-bound statistics, without inference.

This is a presentation step. It does not verify upstream experiments, recompute
statistics, certify scientific assumptions, or authorize publication of inputs.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def read(path):
    def bad_constant(_):
        raise ValueError('Nonfinite JSON value')
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique_object, parse_constant=bad_constant)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':')).encode()).hexdigest()


def registry():
    result = []
    for split in ('test', 'ood'):
        for rq in ('RQ1', 'RQ2', 'RQ3', 'RQ4'):
            result.append({'id': f'{rq}/{split}', 'rq': rq, 'split': split,
                           'family': 'primary' if (rq, split) == ('RQ1', 'test') else 'secondary'})
        for k in (1, 2, 3):
            result.append({'id': f'M7/dynamic-vs-fixed-k-{k}/{split}', 'rq': 'M7', 'split': split,
                           'family': 'secondary', 'left': f'fixed-k-{k}', 'right': 'dynamic-k'})
        for name in ('remove_hard_weight', 'remove_unknown_weight'):
            result.append({'id': f'M7/{name}/{split}', 'rq': 'M7', 'split': split,
                           'family': 'secondary', 'left': 'dynamic-k', 'right': 'dynamic-k-' + name})
    return result


def number(value, nullable=False, probability=False):
    if value is None and nullable:
        return
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('Expected a finite numeric aggregate')
    if probability and not 0 <= value <= 1:
        raise ValueError('Invalid p-value')


def validate(report, manifest, allow_engineering=False):
    scope = 'engineering' if allow_engineering else 'formal'
    if manifest.get('kind') != 'frozen_statistics_analysis' or manifest.get('status') != 'completed' \
            or manifest.get('scope') != scope or manifest.get('m8_complete') is not False \
            or manifest.get('gold_or_references_reopened') is not False \
            or manifest.get('receipt_hash') != digest({k: v for k, v in manifest.items() if k != 'receipt_hash'}):
        raise ValueError('Incomplete or mismatched statistics manifest')
    if report.get('kind') != 'source_task_research_statistics' or report.get('scope') != scope \
            or report.get('schema_version') not in ((2, 3) if allow_engineering else (3,)) \
            or report.get('protocol_hash') != manifest['protocol_hash'] \
            or report.get('analysis_stage_receipt') != 'manifest.json' \
            or report.get('m8_complete') is not False or report.get('secondary_family_size') != 17:
        raise ValueError('Unexpected statistics report or comparison family')
    if report['schema_version'] == 3 and (report['analysis_plan'].get('schema_version') != 2
                                         or report['analysis_plan'].get('bootstrap_stratification') != 'operation_family_fixed_source_counts'):
        raise ValueError('Expected the frozen stratified analysis plan')
    definitions = registry()
    if set(report['comparisons']) != {row['id'] for row in definitions}:
        raise ValueError('All 18 registered comparisons must be retained')
    for definition in definitions:
        row = report['comparisons'][definition['id']]
        if row['definition'] != definition or row['secondary_family_size'] != (17 if definition['family'] == 'secondary' else None):
            raise ValueError('Comparison definition or multiplicity changed')
        if type(row['source_task_groups']) is not int or row['source_task_groups'] < 1:
            raise ValueError('Invalid source-task denominator')
        for name in ('left', 'right', 'right_minus_left'):
            number(row[name])
        if not math.isclose(row['right'] - row['left'], row['right_minus_left'], abs_tol=1e-12, rel_tol=1e-12):
            raise ValueError('Effect direction inconsistent with reported means')
        interval = row['percentile_95_interval']
        if interval is not None:
            if not isinstance(interval, list) or len(interval) != 2:
                raise ValueError('Invalid interval')
            for bound in interval:
                number(bound)
            if interval[0] > interval[1]:
                raise ValueError('Inverted interval')
        hypothesis = row['hypothesis_test']
        if hypothesis['method'] != 'two_sided_cluster_sign_flip':
            raise ValueError('Unexpected hypothesis test')
        if hypothesis['mode'] not in ('insufficient_clusters', 'insufficient_stratum_clusters',
                                      'exact_sign_assignments', 'monte_carlo_conservative_plus_one'):
            raise ValueError('Unknown test status; review before rendering')
        number(hypothesis['p_value'], nullable=True, probability=True)
        number(row['holm_adjusted_p_value'], nullable=True, probability=True)
        if definition['family'] == 'primary' and row['holm_adjusted_p_value'] is not None:
            raise ValueError('Primary comparison must not use secondary adjustment')
        if hypothesis['p_value'] is None and row['holm_adjusted_p_value'] is not None:
            raise ValueError('Undefined p-value cannot acquire an adjusted value')
        expected_seeds = 3 if definition['rq'] in ('RQ1', 'RQ4') else 1
        if row['fixed_training_seeds'] != expected_seeds or len(row['per_seed']) != expected_seeds \
                or [s['seed_index'] for s in row['per_seed']] != list(range(expected_seeds)):
            raise ValueError('All fixed training seeds must be retained')
        number(row['seed_effect_sample_sd'], nullable=True)
        for seed in row['per_seed']:
            for key in ('left', 'right', 'right_minus_left'):
                number(seed[key])
    return definitions


def display(value):
    # 17 significant digits preserve binary float round trips; no p<... rewriting.
    if value is None:
        return 'null'
    return format(value, '.17g')


def markdown(report, definitions):
    lines = ['# 预登记统计比较表', '',
             '范围：' + report['scope'] + '。本表仅排版已保存统计，不重算区间或p值，不是M8完成凭据。', '',
             '所有效应均为右条件减左条件，概率指标使用0–1尺度。RQ1为D−B状态错误率，'
             'RQ2为P3−P1新增硬违规率，RQ3为P4−P3合规成功率，RQ4为E−D目标token加权交叉熵。'
             'M7比较的左右条件见表。RQ1/RQ2/RQ4负值、RQ3/M7正值分别表示对应右条件的点估计方向；不自动判定方法优越。', '',
             '唯一主比较为RQ1/test；其余17项保留完整Holm家族。null保持未定义，不能改写为0或“无差异”。'
             '退化区间不证明零风险。区间条件于固定训练模型，三个种子的标准差不是训练种子总体置信区间。', '',
             '|比较|家族|左条件|右条件|源任务数|左均值|右均值|右−左|95%区间|原始p|Holm p|检验状态|',
             '|---|---|---|---|---:|---:|---:|---:|---|---:|---:|---|']
    pairs = {'RQ1': ('B', 'D'), 'RQ2': ('P1', 'P3'), 'RQ3': ('P3', 'P4'), 'RQ4': ('D', 'E')}
    for definition in definitions:
        row = report['comparisons'][definition['id']]
        left, right = pairs[definition['rq']] if definition['rq'] != 'M7' else (definition['left'], definition['right'])
        interval = row['percentile_95_interval']
        ci = 'null' if interval is None else '[' + ', '.join(display(v) for v in interval) + ']'
        values = [definition['id'], definition['family'], left, right, str(row['source_task_groups']),
                  *[display(row[k]) for k in ('left', 'right', 'right_minus_left')], ci,
                  display(row['hypothesis_test']['p_value']), display(row['holm_adjusted_p_value']),
                  row['hypothesis_test']['mode']]
        lines.append('|' + '|'.join(values) + '|')
    lines.extend(['', '## 固定种子逐项结果', '', '|比较|种子索引|左均值|右均值|右−左|效应样本标准差|',
                  '|---|---:|---:|---:|---:|---:|'])
    for definition in definitions:
        row = report['comparisons'][definition['id']]
        for seed in row['per_seed']:
            lines.append('|' + '|'.join([definition['id'], str(seed['seed_index']),
                         *[display(seed[k]) for k in ('left', 'right', 'right_minus_left')],
                         display(row['seed_effect_sample_sd'])]) + '|')
    lines.extend(['', '本表不包含逐例任务标识、题目、gold、模型输出或参考答案；也不授权公开输入文件。'
                  '完整报告仍须解释共享生成器、跨划分近邻、源任务依赖、符号翻转交换性和功效局限，'
                  '并补充格式/状态/证据、候选机会、共同可行子集、错误、调用/token、时间与显存等结果。'
                  '上游冻结验证、独立算术复算、数据质量及资产发布须分别验收。', ''])
    return '\n'.join(lines)


def render(directory, expected_manifest, expected_report, out, allow_engineering=False):
    directory, out = Path(directory), Path(out)
    if sha(directory / 'manifest.json') != expected_manifest or sha(directory / 'report.json') != expected_report:
        raise ValueError('Input differs from externally supplied trusted SHA256')
    manifest, report = read(directory / 'manifest.json'), read(directory / 'report.json')
    if manifest['files_sha256'] != {'report.json': expected_report}:
        raise ValueError('Unexpected statistics member hashes')
    definitions = validate(report, manifest, allow_engineering)
    text = markdown(report, definitions)
    # Recheck inputs before writing; existing output and failed directories remain.
    if sha(directory / 'manifest.json') != expected_manifest or sha(directory / 'report.json') != expected_report:
        raise ValueError('Input changed while rendering')
    out.mkdir(parents=True, exist_ok=False)
    target = out / 'STATISTICS.md'
    target.write_text(text, encoding='utf-8', newline='\n')
    receipt = {'kind': 'statistics_comparisons_presentation', 'scope': report['scope'],
               'manifest_sha256': expected_manifest, 'report_sha256': expected_report,
               'markdown_sha256': sha(target), 'comparisons': len(definitions), 'secondary_family_size': 17,
               'statistics_recomputed': False, 'upstream_experiments_verified': False,
               'scientific_assumptions_certified': False, 'm8_complete': False}
    (out / 'presentation-receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--statistics', required=True, type=Path)
    parser.add_argument('--expected-manifest-sha256', required=True)
    parser.add_argument('--expected-report-sha256', required=True)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--allow-engineering', action='store_true')
    args = parser.parse_args()
    print(json.dumps(render(args.statistics, args.expected_manifest_sha256, args.expected_report_sha256,
                            args.out, args.allow_engineering)))


if __name__ == '__main__':
    main()
