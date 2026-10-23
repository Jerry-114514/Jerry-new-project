# Jerry-new-project

面向多步骤 Agent 的要求追踪、证据诊断和修复退化控制实验工具。当前最小实现支持 Python 3.11+，核心与轻量训练不依赖第三方包或 GPU。

## 快速运行

```bash
python -m unittest discover -s tests -v
python -m intentlab build-data --out runs/data
python -m intentlab run --out runs/demo
python -m intentlab train-baseline --data runs/data/diagnostic_views.jsonl --out runs/training
```

- [实现与复现指南](docs/implementation-guide.md)：架构、协议、边界和后续接入。
- [数据说明](data/README.md)：40 个合成任务、160 条轨迹、320 个诊断视图及切分。
- [本轮实际演示报告](examples/results/complete-evidence/REPORT.md)：脚本化执行器功能验证，不代表真实 LLM 收益。
- [隐藏历史演示报告](examples/results/redacted-evidence/REPORT.md)：补证动作与成本记录。
- [轻量训练结果](examples/results/training/summary.json)：6 次 CPU 逻辑回归训练；不是 QLoRA 或学习率算法创新。

本项目已跑通受控环境、独立评估、固定/动态修复及真实模型训练。任意自然语言泛化、强基线比较和正式研究收益仍需后续验证。

2026-10-22 已在 AutoDL RTX 5090 上完成官方 Qwen3.5-9B 的 QLoRA 先导实验及 CUDA 断点恢复。当前训练/验证阶段显存保留峰值约 26.6 GiB；归一化状态判断错误由 51/192 降至 Plateau 组的 7/192，该分析为事后分解，只有 6 个合成测试任务。另修复了模型门禁放行输入覆盖的问题，加入独立修复硬约束检查，46 项测试通过。[实测报告](docs/qwen35-5090-pilot-report.md) · [主实验原始记录](examples/results/qwen35-5090-pilot-v2/summary.json) · [硬约束补充验证](examples/results/qwen35-hard-guard/summary.json)

新增：已跑通真实微型因果语言模型和 LoRA 训练、逐位一致的 CPU 断点恢复、本地语言模型分析器接入、token 预算及模板原文抽取。微型模型的 JSON 失败按实际记录，不代表大模型研究收益。[神经模型训练指南](docs/neural-training.md) · [实际神经模型审计结果](examples/results/neural-smoke/audit.json)

[搭建验证清单](docs/build-verification.md)逐项列出代码入口、40 项完整测试、可重放数据与尚未进行的正式研究实验。

## 研究文档

- [600份单模板训练候选扩充](docs/training-candidate-scale.md)：3000来源中确定性取600份未审核合同、2400注入视图，包含原12份；程序参考一致性通过，来源、模板覆盖及人审仍缺。
- [2400视图完整输入长度](docs/training-length-budget.md)：压缩候选在3328上下文仍有31例不能预留512输出，最长需4202；不能外推旧104视图的长度覆盖。
- [标注负担修订提案](docs/annotation-workload-revision-proposal.md)：保留两路线选择历史；用户现已选择完全程序标签，不再安排每人9600项或320项审计。
- [程序标签实施指南](docs/programmatic-label-guide.md)：用户已选择完全程序标签，idea更新2.0；2400训练视图已导出，正式协议工程迁移、对抗覆盖和新划分仍待完成，不声称人工验证。
- [顺序违规与程序标签对抗检查](docs/contract-fault-coverage.md)：600份原train合同新增7200故障视图，补齐1800顺序违规；六类声明的检查器变异均被识别，仍是单模板开发候选池。
- [监督位置logits显存优化](docs/supervised-logits-memory.md)：保持因果损失和输入完整，5090上4608/512合成序列两更新通过，reserved约17.99GiB；非正式训练。
- [压缩提示的真实模型开发对照](docs/compact-prompt-development-report.md)：208次调用完成，格式通过99/104与103/104、计费token减少31.68%；有40项状态分歧，无人工真值，不报告准确率。
- [新来源提示与显存预算](docs/context-coverage-budget.md)：104 个实际提示暴露 2048 草案缺口；4096 合成压力显存不足、3328 通过，另有保留全部公开数据的离线提示压缩提案，尚未用于模型实验。
- [跨批来源覆盖及协调人审核](docs/combined-source-coverage.md)：104 视图合并为 32 合同、24 个声明来源，78 对风险待审；固定既往公开资产目录，原文保持私有。
- [外部来源合同的自然轨迹采集](docs/wikisql-natural-collection.md)：保留旧两题、补采十题，共 12 次真实执行、24 个未标注视图；候选参考下合规 7/12，含两次接口失败，逐调用回放通过。
- [WikiSQL 显式合同开发适配](docs/wikisql-equality-adaptation.md)：12 份私有候选合同、48 个注入视图及两题真实 9B 冒烟验证；尚无人工审核，不代表原题求解或正式方法收益。
- [WikiSQL 外部来源候选池](docs/wikisql-source-intake.md)：固定上游 train、600 条待适配来源及可重算索引；不计入正式任务或人工标签，不用作新隔离测试。
- [新自然轨迹上的 A/C 基线开发检查](docs/schema-baseline-development.md)：原始 9B 的实际 Schema 输出、公开规则对照和可重算 token 账本；不含人工准确率或微调结论。
- [来源、模板与近重复审查](docs/source-template-review-guide.md)：跨新旧候选的风险清单、保守分组、人工审查模板及正式冻结内容校验；自动初筛不等于独立来源证明。
- [新训练候选的上下文与 5090 压力检查](docs/context-budget-development.md)：24 个实际提示长度，以及精确 1024/2048 序列的短 QLoRA 硬件探测；不等于正式预算或质量结论。
- [自然轨迹训练候选与标注接入](docs/training-trajectory-intake-guide.md)：12 个训练变体、四个保守模板簇，实际原始 9B 执行及不含自动标签的双视图标注包；尚无人审核，不用于正式测试。
- [候选审计与统计阶段验证](docs/candidate-statistics-guide.md)：完整提案与决策错误分开记录，误拦截分母为空时保留 null，共同可行子集配对，并核验统计阶段上游凭据及重算结果。
- [正式实验目标与验收依据](idea.md)：M1–M8 的范围、数据隔离与正式实验要求；进度见[执行记录](docs/formal-experiment-status.md)。
- [人工标注流程说明](docs/human-annotation-workflow.md)：人员分工、盲包发放、三状态与证据、双人独立初审、第三人仲裁及交付验收。
- [实验规划指南：基于误差曲线的学习率调整与证据驱动纠偏](docs/experimental-planning-guide.md)：最新实验指南，明确动态控制规则、四组对照、数据隔离、单卡预算与验收要求。
- [Agent 误差分析与纠偏：稳定成果产出导向的研究方案](docs/agent-error-analysis-stable-output-plan.md)：区分可控交付与待验证收益，增加诊断实验、评分验证、条件性保持分析和成果验收标准。
- [面向多步骤 Agent 的用户要求保真与证据驱动纠偏：研究建议报告](docs/agent-intent-fidelity-research-proposal.md)：研究定位、候选问题、先导实验、评估指标与参考文献。
