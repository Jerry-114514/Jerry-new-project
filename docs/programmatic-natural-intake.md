# 真实执行轨迹的程序标签入口

2026-10-23。按用户已选的全程序标签路线，为既有自然轨迹导入器补充显式`--references`分支。旧的人审空白包分支保留用于复现，不再作为当前正式路线的人力依赖。

新入口先拒绝test/OOD，再读取开发任务的独立参考，核对执行清单的参考哈希、完整任务/策略覆盖、模型路径与actor声明，回放可信事件重建最终文件。原始运行按字节绑定，记录中的在线判断、最终指标和模型原文不作为gold；标签由离线规格标签器重新计算，静态参考独立复算。失败运行也保留。每次运行导出完整事件及隐藏历史两个视图，继承原source_task_id、模板和split，不增加独立源任务数。

```bash
python -m intentlab.trajectory_intake --tasks PRIVATE/tasks.jsonl --references PRIVATE/references.jsonl --execution PRIVATE/execution --out PRIVATE/new-programmatic-intake
```

输出为cases/provenance、程序标签、相应train/validation SFT及哈希清单，不产生人工署名、空白人审包或human_verified声明。输出目录拒绝覆盖；输入失败时不创建输出。此入口不证明模型身份、语义独立或参考普遍正确。完整生成/环境/模型资产仍需另外绑定。

## 已验证与尚未采集

9项轨迹入口测试覆盖原路径、新程序标签、空执行的失败保留、可见事件与隐藏历史的不同状态、在线假指标隔离、参考哈希不匹配和在打开无效参考前拒绝heldout。3项采集选择测试覆盖输入顺序不影响选择、缺少分层拒绝、heldout不进入选题和参考生成。本地全套235项测试中14项ML测试跳过，其余通过。首次新选择测试因测试夹具跨集合复制相同请求而被既有隔离规则拒绝，修正为真实不同模板夹具后通过；初次失败日志保留。

旧WikiSQL真实9B轨迹12次，按新入口回放得到24视图，包含原记录中2次error和10次finished；finished不等于任务正确。新增模型调用0、新独立来源0。该回放只证明新入口适配既有真实记录，未并入当前v3程序训练/验证，也不补足新批次自然轨迹要求。

新v3程序候选按split/family/字段是否缺失分层，每格选SHA256(task_id)最小的一份：32源任务，预期64视图。选题前未看新actor输出。字段齐全与blocked各半是覆盖采样，不能估计自然失败总体发生率。独立参考从这些公开开发合同重新求值，不打开全量参考/gold库。原始输入和参考保持私有，仅公开计划和哈希。

准备命令：

```bash
python scripts/prepare_natural_development.py --tasks PRIVATE/v3/tasks.jsonl --out PRIVATE/new-natural-selection
```

当前1800次基线比较结束且GPU空闲后，再按固定计划执行以下采集。**本报告发布时尚未执行**，不将计划当作采集结果；不得同时启动第二个GPU任务。

```bash
python -m intentlab.execution --tasks PRIVATE/new-natural-selection/tasks.jsonl --references PRIVATE/new-natural-selection/references.jsonl --out PRIVATE/new-natural-execution --actor-model /root/autodl-tmp/models/Qwen3.5-9B --device cuda --policies none --max-repairs 0 --max-tool-steps 3 --actor-envelope extract --analyzer-mode rule --context-limit 13312 --max-new-tokens 1536 --token-budget 24576
```

extract接口会保留原始生成及投影信息，不能将投影后的可执行动作称原始严格接口成功。none策略不修复，规则分析器和离线评估只记录结果，不向actor提供隐藏参考。采集结束再回放并程序标注；数据合并、训练/验证权重、长度、计算预算和协议均需更新后冻结。训练视图只用训练来源，验证视图只用验证来源，测试/OOD不进入本入口。

公开证据见[M2l](../examples/results/formal-m2l-programmatic-natural/README.md)。正式M2/M3及六组9B训练仍未完成。
