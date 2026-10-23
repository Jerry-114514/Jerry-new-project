import hashlib
import json
from pathlib import Path
import platform
import runpy
import subprocess
import sys
from zipfile import ZipFile,ZIP_DEFLATED

repo=Path.cwd();private=repo/'runs/wikisql-training-scale-20261023'
sys.path.insert(0,str(repo))
public=repo/'examples/results/formal-m2g-training-scale'
from intentlab.formal_data import read_jsonl,write_jsonl
from intentlab.protocol import source_snapshot
helper=runpy.run_path(str(public/'audit.py'))
def save(name,value):
    (public/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
save('pool-manifest.json',json.loads((private/'pool/manifest.json').read_text(encoding='utf-8')))
save('adapter-manifest.json',json.loads((private/'adapted/manifest.json').read_text(encoding='utf-8')))
save('capacity.json',helper['capacity'](read_jsonl(private/'pool/coordinator-pool.jsonl')))
save('prefix-consistency.json',helper['prefixes'](private))
save('private-file-sha256.json',helper['hashes'](private))
lineage=[{k:v for k,v in row.items() if k!='private_view_mapping'} for row in read_jsonl(private/'adapted/coordinator-lineage.jsonl')]
write_jsonl(public/'lineage-public.jsonl',lineage)
quality=json.loads((private/'source-quality.json').read_text(encoding='utf-8'))
save('source-quality-summary.json',{k:quality[k] for k in ('selected_candidates','distinct_table_ids','distinct_exact_table_payloads','distinct_supplied_page_id_values')}|
    {'missing_page_id_candidates':len(quality['missing_page_id_candidates']),
     'duplicate_supplied_page_id_groups':len(quality['duplicate_supplied_page_id_groups']),
     'human_verified_sources':0,'parent_page_or_worker_independence_audited':False})
save('scale-summary.json',{'scope':'single_template_train_development_only','source_pool':3000,'candidate_contracts':600,
    'existing_candidate_contracts_included':12,'new_candidate_contracts':588,'injected_views':2400,
    'existing_injected_views_included':48,'new_injected_views':2352,'shared_project_templates':1,
    'shared_template_pairs_formula_only':600*599//2,'pairwise_semantic_review_performed':False,
    'human_reviews_completed':0,'new_model_calls':0,'formal_minimum_tasks_satisfied':False,'formal_training_started':False,
    'warning':'No automatic scientific promotion: provisional page/payload dedup, one shared template, injected views, no new sealed test/OOD. Existing twelve contracts and their views are included, not additional samples.'})
save('runtime-identity.json',{'scope':'CPU_candidate_preparation_only','source_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
    'source_normalized_sha256':source_snapshot(repo),'python':platform.python_version(),
    'model_weights_loaded':False,'gpu_used':False,'human_reviews_completed':0})
tasks=helper['verify_private'](private)
save('program-reference-consistency.json',{'contracts_checked':len(tasks),'public_program_matches_separate_sqlite_candidate_reference':True,'human_truth_claim':False})
guide='''# 本批人工标注说明：600份训练开发候选

批次：wikisql-training-600-20261023。600份合同、2400个注入视图，共享一个项目模板。
原有12份合同与48个注入视图已包含，不能按600+12或2400+48计算。
每人填写2400条案例记录、9600项要求判断；两位初审人共4800条记录、19200项判断。
这不是已审核的独立任务数，也不是已测量的工时。当前未分发、无人审核。

全部为上游train衍生的显式项目文件要求，不复现原WikiSQL自然语言转SQL。
原题是背景，以public.requirements和公开execution_spec核验；发现歧义或矛盾交协调人登记。
来源独立性、适配及授权审核尚未完成，协调人须先核对材料与允许分发范围。
同源自然执行24视图另包保存，不能将同源视图当新增独立合同。

按请求、原始inputs、当前files、实际可见events逐项判断satisfied/violated/unknown。
events=null是历史缺失，[]是可见历史为空；不能补造事件或以输入恢复证明从未写入。
必交付物在完整路径清单中缺失，与历史不足分别判断，不假设后续修复。
known状态须非空实际证据；unknown可为空。证据引用为request、input:<完整路径>、
file:<存在路径>、snapshot_paths、event:<实际index>，不得引用隐藏或不存在的记录。

A/B由不同真人独立完成同版材料，提交前不看对方标签，不复制程序或模型标签。
不浏览参考、故障映射、模型原文和评分；本包不含这些材料。
真实核验后填写稳定reviewer ID和human_verified=true，不修改case_id、要求ID或公开材料。
有状态或证据分歧由不同于初审两人的第三人仲裁，保留理由及原始版本。
发放时登记批次和分工，分批不得重复统计旧48视图；先试标测量工时与一致性，再安排规模。
'''
packet=private/'adapted/reviewer-packet'
entries={p.name:p.read_bytes() for p in packet.iterdir() if p.is_file()}
assert set(entries)=={'README.md','cases.jsonl','review-template.jsonl'}
entries['本批标注说明.md']=guide.encode('utf-8')
archive=repo/'runs/annotation-reviewers-wikisql-training-600-20261023.zip'
with ZipFile(archive,'x',ZIP_DEFLATED) as zipped:
    for name,content in sorted(entries.items()):zipped.writestr(name,content)
save('reviewer-package.json',{'scope':'private_blank_single_template_training_candidates','views':2400,'records_per_reviewer':2400,
    'judgments_per_reviewer':9600,'initial_reviewers_required':2,'human_reviews_completed':0,'distributed':False,
    'source_fidelity_and_release_review_complete':False,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
    'files_sha256':{name:hashlib.sha256(content).hexdigest() for name,content in entries.items()}})
print(json.dumps({'candidate_contracts':600,'new_contracts':588,'views':2400,'judgments_per_reviewer':9600,'human_reviews_completed':0}))
