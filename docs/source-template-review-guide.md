# 来源、模板与近重复审查

2026-10-23。本流程补充 M2 的数据质量工作。自动结果是审查线索，不是独立来源证明、人工审核或正式准备完成证据。

## 本轮发现

对旧开发包 8 个视图与新训练包 24 个视图进行公开输入比对：32 个视图合并观察后对应 20 份任务合同，声明的 source_task_id 共 12 个。新训练的三个领域变体仍各自归于同一操作模板簇，不把不同快照/历史算作独立任务。

初筛得到 **12 对跨 train/validation 的同操作合同**，均由 shared_coded_operation_risk_only 标记。它们不是已判定的语义重复，也不表示已有正式测试泄漏；两批均为公开开发资产。需要审查来源和生成谱系后，才能决定是否允许作为相互独立的训练/验证组。不能将新四簇直接与旧八题相加为 12 个已核验独立样本。

本轮只扫描这两份公开案例文件，没有覆盖旧 40 个 fixture 的全部变体、所有外部来源或模型预训练数据；未标记不等于排除了近重复。正式审查须补齐既往公开资产清单。

## 协调人生成清单

```bash
python -m intentlab.source_triage --cases OLD_CASES.jsonl NEW_CASES.jsonl --out runs/source-triage-v1
```

默认拒绝 test/OOD。正式数据构建期间，协调人可显式使用 `--private`，输出必须位于 `runs/formal-private/`；私有合同、来源映射和案例不得上传公开仓库。该路径规则不替代系统访问隔离。

工具先按原始输入、要求、执行规格及来源/模板/划分元数据合并观察视图，再检查相同公开合同、规范化请求、声明来源/模板重叠、已编码操作及操作要求的词集合 Jaccard。默认阈值 0.8 是候选检索规则，不是经校准的重复概率；未使用语义嵌入或模型判断。共同禁止事项与报告样板不作为主要操作文本。

- `contracts.jsonl`：逐份公开合同及其视图、批次和来源声明。
- `candidate-pairs.jsonl`：候选合同对、触发原因及跨划分标记。
- `coordinator-cases.jsonl`：按 case_id 排序的完整候选元数据，不含自动标签。
- `pair-review-template.jsonl`：分工和审查笔记用空表，不是正式批准文件。
- `semantic-review-template.json`：绑定该 coordinator-cases 的正式审查空模板。若全局分组/隔离已不合法，只输出 unavailable 原因，须先纠正数据。

重复输入批次、多个证据视图和原始字段/数字变体不会自动增加独立性计数。声明 source_task_id 本身仍需证据支持。

## 人工审查与纠正

审核者核查每个 source_groups 的原始来源、生成/改写谱系、模板和操作族，填写 independence_rationale 与 provenance_evidence。prior_public_inventory_reference 应列出实际审阅的已公开数据版本、文件与范围，并如实填写 limitations；不能只依据自动清单声明所有历史资产已查清。

对 semantic-review-template 中每个 pair_reviews 填写 decision 与 rationale。只有有证据支持的 independent_sources 才能通过；缺少记录、空理由和未解决状态均拒绝。相同公开合同不能通过勾选独立来覆盖。发现同来源/模板或证据不足时，应合组、排除或调整划分，再对新版本重新生成审查材料。

修订只能产生带版本和原案例映射的派生数据；保留实际模型原始输出、执行任务与旧来源声明。更新派生案例、相应执行合同和审核/导出绑定，并重新检查一致性。不能悄悄改写旧运行的 source_task_id，使其看起来来自新独立任务。

审核还须覆盖未标记的来源关系和语义近重复；共享操作可能是真正不同的任务，低词重叠也可能是改写。程序只验证声明与覆盖，不证明审核者身份或统计独立性。

## 正式冻结要求

正式草案的 semantic_dedup_review 现指向 `runs/formal-private/evidence/semantic-source-review.json`。审核者实际完成后才能填写 reviewer、human_verified，以及来源、语义、划分和先前公开资产的审核声明。模板中默认均为空/false，不能由程序代填。

协调人可用以下 Python 接口单独检查填写结果：

```python
import json
from pathlib import Path
from intentlab.formal_data import read_jsonl
from intentlab.source_triage import validate_semantic_review

validate_semantic_review(
    read_jsonl("runs/formal-private/cases.jsonl"),
    json.loads(Path("runs/formal-private/evidence/semantic-source-review.json").read_text(encoding="utf-8")),
)
```

正式 check/freeze 会核对完整字段、当前 cases_hash、重算初筛哈希、全部来源组与候选对。冻结绑定原始案例文件 SHA、审查文件 SHA 和验证摘要。训练阶段只核对冻结摘要，不打开这些协调人材料；all 阶段再验证文件和内容。旧文本说明或自动初筛报告不能替代结构化人审证据，工程协议保留原兼容行为。

本轮真实来源审查与标注均为 0。相关模板及清单只是准备材料，M2、M3 和正式六次训练仍未完成。
