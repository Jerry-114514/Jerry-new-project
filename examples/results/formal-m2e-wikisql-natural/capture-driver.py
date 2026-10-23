import hashlib
import json
from pathlib import Path
import shutil
import sys
from zipfile import ZipFile, ZIP_DEFLATED

source = Path('/root/autodl-tmp/Jerry-formal-v2-20261022')
sys.path.insert(0, str(source))
from intentlab.formal_data import read_jsonl, write_jsonl, annotation_packet
from intentlab.report import summarize
from intentlab.protocol import model_snapshot, verify_official_assets

root = Path('/root/autodl-tmp/wikisql-natural-collection-20261023')
assert json.loads((root / 'execution-exit.json').read_text())['returncode'] == 0
assert json.loads((root / 'execution/manifest.json').read_text())['status'] == 'completed'
private = root / 'private-export'
private.mkdir(exist_ok=False)
adapted = Path('/root/autodl-tmp/wikisql-adapter-validation-20261023/source/runs/private-adaptation-v1')
for name in ('tasks.jsonl', 'candidate-references.jsonl'):
    shutil.copyfile(adapted / name, private / name)
original = Path('/root/autodl-tmp/wikisql-adapter-validation-20261023/source/runs/private-execution-smoke')
for batch, prefix, execution in (('first-two','first-two',original),('remaining-ten','remaining',root/'execution')):
    folder = private / batch
    folder.mkdir()
    shutil.copyfile(root / (prefix + '-tasks.jsonl'), folder / 'tasks.jsonl')
    shutil.copytree(execution, folder / 'execution')
    shutil.copytree(root / ('intake-' + batch), folder / 'intake')
cases = read_jsonl(private / 'first-two/intake/coordinator-cases.jsonl') + read_jsonl(private / 'remaining-ten/intake/coordinator-cases.jsonl')
assert len(cases) == len({c['case_id'] for c in cases}) == 24
annotation_packet(cases, private / 'reviewer-packet')
readme = private / 'reviewer-packet/README.md'
readme.write_text(readme.read_text(), encoding='utf-8', newline='\n')
guide = '''# 本批人工标注说明：外部来源自然执行轨迹

批次：wikisql-natural-20261023。24 个视图，来自 12 次真实模型执行。
每位审核者提交 24 条记录、96 项要求判断；两人共 48 条、192 项。
同一执行的可见历史视图与快照视图相关，共享来源；不能当独立样本。
本包不同于 48 个注入视图批次，不按两个批次之和计算独立任务数。

研究者已将上游 SQL 条件改为公开显式文件要求；原题是背景，
按 public.requirements 与公开 execution_spec 核验。疑似矛盾交协调人登记。
来源适配、独立性和授权审核尚未完成；协调人应在分发前完成核对。

先读请求、原始 inputs，再读当前 files 与可见 events。events=null 是缺历史，
events=[] 是可见历史为空。不能引用隐藏事件，不能以输入相同证明从未写入。
必交付物在完整路径清单中缺失，与历史不足分别判断，不假设后续修复。
每项独立填写 satisfied/violated/unknown；前两者须有实际非空证据。
证据格式为 request、input:<完整路径>、file:<存在路径>、snapshot_paths、event:<实际index>。
不要修改 case_id、要求 ID、hard 属性或公开材料。遇到歧义记录并交协调人。

A/B 由不同真实人员独立完成同版整包，提交前不看对方结果，分别保存 reviews-A/B.jsonl。
不得复制程序或模型标签；不浏览仓库评分、模型原文、参考答案及协调人映射。
真实核验后才填写稳定 reviewer ID 和 human_verified=true。状态或证据有分歧，
由不同于两位初审人的第三人仲裁，保留理由与原始版本。当前实际审核人数与条数均为 0。
'''
(private / 'reviewer-packet/本批标注说明.md').write_text(guide, encoding='utf-8', newline='\n')
public = root / 'public-evidence'
public.mkdir(exist_ok=False)
records = read_jsonl(private / 'first-two/execution/runs.jsonl') + read_jsonl(private / 'remaining-ten/execution/runs.jsonl')
assert len(records) == len({r['task_id'] for r in records}) == 12
summary = {'scope':'unreviewed_train_initial_attempts', 'previous_runs':2,'new_runs':10,'runs':12,
    'natural_views':24,'shared_templates':1,'candidate_reference_compliant_runs':sum(r['metrics']['compliant_success'] for r in records),
    'program_exceptions':sum(r['status']=='error' for r in records),'actor_calls':sum(r['cost']['actor_calls'] for r in records),
    'human_accuracy':None,'formal_M6_complete':False,'human_reviews_completed':0,
    'warning':'Unreviewed explicit-contract adaptation; one shared template, not original WikiSQL NL-to-SQL accuracy or independent human benchmark. No repair or formal treatment comparison.'}
def save(name, data):
    (public / name).write_text(json.dumps(data, indent=2, ensure_ascii=False)+'\n',encoding='utf-8',newline='\n')
save('collection-summary.json',summary)
save('execution-summary.json',summarize(records))
for batch in ('first-two','remaining-ten'):
    shutil.copyfile(private / batch / 'intake/manifest.json',public / (batch + '-intake-manifest.json'))
shutil.copyfile(root / 'launch.json',public / 'launch.json')
shutil.copyfile(root / 'execution.log',public / 'execution.log')
save('official-assets-after-run.json',verify_official_assets(model_snapshot('/root/autodl-tmp/models/Qwen3.5-9B'),source))
files = {p.relative_to(private).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in private.rglob('*') if p.is_file()}
save('private-file-sha256.json',files)
review = root / 'annotation-reviewers-wikisql-natural-20261023.zip'
with ZipFile(review,'w',ZIP_DEFLATED) as z:
    for p in sorted((private/'reviewer-packet').iterdir()):z.write(p,p.name)
save('reviewer-package.json',{'kind':'private_blank_natural_trajectory_packet','views':24,'records_per_reviewer':24,
    'judgments_per_reviewer':96,'initial_reviewers_required':2,'human_reviews_completed':0,'distributed':False,
    'source_fidelity_and_release_review_complete':False,'sha256':hashlib.sha256(review.read_bytes()).hexdigest(),
    'files_sha256':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in (private/'reviewer-packet').iterdir()}})
with ZipFile(root/'private.zip','w',ZIP_DEFLATED) as z:
    for p in private.rglob('*'):
        if p.is_file():z.write(p,p.relative_to(private))
with ZipFile(root/'public.zip','w',ZIP_DEFLATED) as z:
    for p in public.iterdir():z.write(p,p.name)
print(json.dumps(summary),flush=True)
