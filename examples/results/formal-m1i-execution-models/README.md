# M1i：最佳导出参数与执行模型绑定工程证据

2026-10-22，engineering 范围。AutoDL 全部 **128 项测试通过**；本地 118 项通过、10 项因无 ML 依赖跳过。不是正式六次 9B 训练，也不代表 M5/M6 已完成。

- 六个真实微型 CPU 训练 worker，三种子 × 两调度；包括一次中断恢复，共七次 worker 启动。三对暴露量各一致：每组 4 个样本、208 个监督 token。
- 训练和模型绑定前删除执行任务、参考、人工审核及 heldout gold；仍完成训练、最佳权重核验、模型绑定与再验证。工程身份均为合成单元测试声明，真实人工审核为 0。
- 对全参数和 LoRA 导出实际逐张量核验；独立测试以恒定模拟验证分数强制首次最优，真实梯度继续变化，确认导出为最佳参数且不同于最后参数。改动导出张量被拒绝；BF16 标量指纹保留类型和形状。
- 未完成矩阵、修改冻结种子、未声明 engineering、改动已绑定资产均被拒绝。六组选择证明及选中模型资产身份保存于 `matrix/execution-model-lock.json`。

`tests-autodl.log` 为最终完整测试；`tests-selection-initial.log` 是此前三项定向检查，不与最终 128 项相加。`runtime-identity.json` 保存远程实际来源指纹和环境；`source-comparison.json` 另对照本地归档时源码，列出差异，不把远程未复制的配置文件当作已验证。核心实现及测试源码一致。

`matrix/` 归档原始配置、结果、日志及绑定记录；临时模型二进制未归档，不能重新逐张量核验。`verification.json` 只重算已保存记录、选择步数和哈希之间的一致性，明确 `model_weights_reverified=false`。哈希不等于持久模型备份。

复核命令：

```bash
python scripts/audit_execution_binding_evidence.py --root examples/results/formal-m1i-execution-models
```

实际正式新数据、双审及仲裁、功效与预算、科学审核、正式协议封存仍未完成；不能据这些工程结果启动确认性训练或声称研究效果。后续须补 M5 封存预测/一次性揭晓，再接 M6 冻结四条件执行，保持原 M1–M8 范围。
