# 单模板训练候选扩充与剩余数据缺口

2026-10-23。本轮推进M2候选规模，不证明独立来源或正式训练已经就绪。

## 已完成

使用同一固定WikiSQL上游train归档、相同结构限制和seed 20261023，将来源池从600条扩到3000条。没有解析上游dev/test JSON，没有依据模型表现选择题目。原600条来源为新池前缀，原12份适配合同及48个注入视图也保持不变。

| 项目 | 实际数量 |
| --- | ---: |
| 来源候选 | 3000 |
| 满足现有ASCII等值适配 | 851 |
| 按已选页面/精确表内容排除 | 127 |
| 剩余结构可用候选 | 724 |
| 确定性选取合同总量 | 600，含旧12、新588 |
| 注入视图总量 | 2400，含旧48、新2352 |
| 共同项目模板 | 1 |
| 新模型调用、人工标签 | 均为0 |

每份合同提供完整、缺交付物、写后恢复以及隐藏历史观察等四种注入视图。它们不是自然错误，也不增加独立任务数。原12份合同的24个自然视图另行保存，与新批次共享来源。

600份公开程序输出均与另一实现的参数化SQLite候选参考一致。这是程序实现一致性，不能证明适配要求忠实于原题或参考已人工正确。项目任务仍是从上游SQL标注明确写入筛选/投影条件的研究者合同，不是原WikiSQL自然语言转SQL评测。

3000来源有3000个表ID，但仅2988个精确表内容、1947个已提供page_id值，另634条缺少page_id。选中600份合同排除了缺失page_id及已选页面/精确内容重叠；这仍不能证明不同页面在语义、作者或内容谱系上独立。

## 标注与来源审查预算

私有空白包为 `runs/annotation-reviewers-wikisql-training-600-20261023.zip`。每位初审人提交2400条案例、9600项要求判断；两人合计4800条记录、19200项判断。实际工时须先试标测量；第三人分歧仲裁工作量尚不能确定。

旧48个注入视图已包含在新包，不重复统计或重复发放；同源自然视图仍用独立批次号保存。每个视图的来源、模板与划分保持一致，不能把自然/注入观察分到不同集合增加样本量。

本包只含公开输入、要求、规格、观察与空白标签；没有候选参考、原始SQL对象、故障映射、模型输出或自动判断。当前未分发，人工审核0，来源保真与授权审核待完成。通用流程见[人工标注说明](human-annotation-workflow.md)。

现有两两风险初筛下，600份共同模板合同有 `600×599/2=179700` 个组合。本轮只记录这个工作量公式，没有生成或批准179700对人工判断。应先结合实际人力安排来源核验、模板覆盖和语义审查流程，不能以批量空表或自动勾选独立代替审查。

## 正式目标仍缺什么

600只是候选合同数量，不等于600个已审核独立训练任务。一个模板的扩充不能补齐多模板训练覆盖、150–200开发任务、新的200测试/100 OOD、自然错误来源及实际双审。公开WikiSQL来源不得包装为新的隔离test/OOD。

原104视图上的提示压缩和3328硬件压力不能自动外推到这2400视图；仍须测量全部新材料的提示及审核后监督目标、少样本B和正式资源预算。正式协议、数据导出和六组训练继续保持未完成。

## 重建与复核

以下审计不修改原批次、不运行模型；私有内容仅写临时协调人目录后回收，公开输出是摘要。默认只核对元数据。

```bash
python examples/results/formal-m2g-training-scale/audit.py
python examples/results/formal-m2g-training-scale/audit.py --archive /private/data.tar.bz2
python examples/results/formal-m2g-training-scale/audit.py --private-root /private/training-scale
```

需要另建私有批次时，可复用既有CLI，保持输出位于被忽略的runs目录，禁止覆盖旧版本：

```bash
python scripts/intake_wikisql.py --archive /private/data.tar.bz2 --source-spec configs/wikisql-source.json --out runs/new-scale/pool --limit 3000 --seed 20261023
python scripts/adapt_wikisql_equality.py --pool runs/new-scale/pool/coordinator-pool.jsonl --pool-manifest runs/new-scale/pool/manifest.json --out runs/new-scale/adapted --limit 600
```

证据见 [M2g目录](../examples/results/formal-m2g-training-scale/README.md)。原题、表格、参考和完整案例不上传GitHub，来源元数据及可重建程序同步保存。
