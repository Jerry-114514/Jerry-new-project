# M1j：隔离诊断生成、封存与揭晓工程证据

2026-10-22，engineering 范围。全部验证使用合成单元任务、合成审核声明及真实微型 CPU Transformer，真实人工审核为 0，正式协议和六次 9B 训练均未启动。不能作为真实任务效果、样本量充分性或正式 M5 完成的证据。

本轮实现固定九条件 A/B/C、D 三种子、E 三种子。真实模型端到端流程中没有注入推理后端或测试损失；另有明确注入的单元测试验证错误与隔离边界，不把这些结果混称真实推理效果。

六组真实微型训练、一次中断恢复和最佳权重核验后，恢复公开合同供诊断使用；参考、review 和 gold 仍不存在。九条件生成完成并封存后才恢复 gold，计算全部状态指标及六组逐案例真实目标损失。再删除 gold，完成凭据仍可验证。

本次只有两个合成 heldout 视图（test/OOD 各一），共 18 条预测、12 条损失记录。模型只允许生成 2 tokens，因此接口失败是预期工程现象，不能据此评估模型能力或微调收益。token 加权损失用于验证计算与记录管线，不构成正式 RQ4 结果。

AutoDL 最终全部 **135 项测试通过**；本地 125 项通过、10 项因缺少 ML 依赖跳过。离线重放通过，另在独立临时副本中改动预测或工程 gold 均被拒绝，见 `audit-tamper-checks.json`。远程与归档时本地的全部 82 个冻结源码/配置文件指纹一致。

## 文件与验证范围

- `tests-autodl.log`：最终完整测试；`tests-local.log`：本地无 ML 环境检查及明确跳过项。
- `runtime-identity.json`、`source-comparison.json`：实际远程环境、测试来源指纹及本地对照；不将未执行的脚本当作模型实验。
- `matrix/`：六组配置、结果、日志、权重绑定记录。
- `matrix/diagnostic-predictions/`：九条件原始预测、调用错误/账本、封存哈希。
- `matrix/diagnostic-reveal/`：完整状态评分、逐例 loss_sum/target_tokens、加权总损失、每种子任务 bootstrap 和完成凭据。
- `matrix/diagnostic-inputs/`：本次真实使用的合成案例、示例及工程 gold，便于离线重算。它们不是正式封存数据，发布不影响未来独立正式测试；正式 gold 禁止走此工程归档路径。
- `verification.json`、`diagnostic-verification.json`：已保存结果、公开规则预测、评分、加权损失汇总及 bootstrap 的重算。临时权重二进制未归档，明确不声称重新计算了模型 logits 或提供持久备份。

离线复核：

```bash
python scripts/audit_diagnostic_evidence.py --root examples/results/formal-m1j-diagnostic-protocol
```

## 失败和修订历史

`history/` 保留全部本轮中间日志，不与最终测试数相加：

| 日志 | 结果与原因 |
| --- | --- |
| tests-initial.log | 定向 10 项，1 项错误；训练后未恢复诊断需要的公开合同，入口拒绝 |
| tests-second.log | 恢复公开合同后，定向 10 项通过 |
| tests-final.log | 增加完成凭据及删除 gold 后验证，全部 134 项通过 |
| tests-replayable.log | 全部 134 项中 1 项归档错误；写工程输入前未创建归档子目录，诊断流程本身已完成 |
| tests-complete.log | 修复归档目录后，全部 134 项通过 |

最终增加“每个正式适配器必须使用冻结基础模型”检查后再运行完整套件。一次性 claim 的失败保留规则没有被改为自动重启；上述都是彼此独立的合成临时单元实例，不是重复揭晓同一正式协议。

正式 M5 仍依赖真实新数据、人工双审、六次正式训练及协议封存。后续 M6 冻结四条件执行入口、M8 种子综合/RQ4 聚类推断/Holm 报告和持久权重备份仍须完成；原 M1–M8 目标未缩小。
