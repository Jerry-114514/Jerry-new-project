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

本轮已经跑通受控环境、独立评估、固定/动态修复及轻量训练。真实 LLM 接入、自然语言要求抽取和 5090 上的大模型训练仍需后续验证。

## 研究文档

- [实验规划指南：基于误差曲线的学习率调整与证据驱动纠偏](docs/experimental-planning-guide.md)：最新实验指南，明确动态控制规则、四组对照、数据隔离、单卡预算与验收要求。
- [Agent 误差分析与纠偏：稳定成果产出导向的研究方案](docs/agent-error-analysis-stable-output-plan.md)：区分可控交付与待验证收益，增加诊断实验、评分验证、条件性保持分析和成果验收标准。
- [面向多步骤 Agent 的用户要求保真与证据驱动纠偏：研究建议报告](docs/agent-intent-fidelity-research-proposal.md)：研究定位、候选问题、先导实验、评估指标与参考文献。
