# 新领域真实执行开发记录

本目录保存开发工程结果，不是正式基准或新一轮 9B 微调。模型为官方原始 Qwen3.5-9B，执行和分析均使用同一原始权重，静态参考尚未人工审核。

最终四条件共 32 次运行，每条件 8 次、合规成功均为 2/8；实际只有 8 个源任务。未观察到动态策略或硬检查开关的收益，也没有候选修复和新增硬违规。详见[开发报告](../../../docs/execution-development-report.md)。

| 路径 | 内容 |
| --- | --- |
| `final/guard-on` | 最终开启独立检查的 fixed-full/dynamic，每策略 8 次 |
| `final/guard-off` | 最终关闭独立检查的相同两策略，每策略 8 次 |
| `inputs` | 8 个公开开发源任务的执行变体及另存静态参考 |
| `annotation/packet` | 去重后的 8 个真实观察、空白审核表及独立审核说明；只把这个子目录给审核者 |
| `annotation/private-provenance.json` | 审核者不应查看的审计来源映射；不是操作系统隐私保护 |
| `error-decomposition.json` | 一组 8 源任务上的原始状态错误 11/32、在线门禁后 13/32 等描述性分解 |
| `replay-audit.json` | 最终 32 次及开发历史 64 次，共 96 次事件、结果、归因和预算重算 |
| `runtime-identity.json` | 最终交互模块、环境和数据内容哈希；不是预先冻结协议 |
| `model-assets.json` | 当前实例的 13 个官方固定版本资产校验 |
| `tests.log` | AutoDL 98 项测试全部通过 |
| `verification.json` | 最终运行模块与仓库内容匹配、原始文件校验及汇总 |

`development-history/v1` 保留裸动作/包格式失败；v2 保留字段校验后过早停止；v3 保留额外回显字段导致的严格包失败；v4 保留首次可执行包提取及重复补证问题修正前的记录。早期迭代没有完整独立源码冻结，原始轨迹可事后重放，但不能当作正式质量对照或保证逐字重现其模型生成。

最终交互用到的 34 个模块内容均与当前发布源码匹配。独立离线审计模块及报告脚本在模型运行后加入，它们没有参与模型决策。对原始输出的状态词不做修正，事件只由工具产生；分析器结果和 oracle 指标未进入盲标注包。

复核指标可在对应源码版本运行：

```bash
python -m intentlab.execution_audit --tasks examples/results/formal-m1d-development/inputs/tasks.jsonl --references examples/results/formal-m1d-development/inputs/offline-references.jsonl --runs examples/results/formal-m1d-development/final/guard-on examples/results/formal-m1d-development/final/guard-off --out runs/execution-replay.json
python scripts/summarize_execution_development.py
```

审核完成数仍为 0；这些已经公开的开发源任务及其变体不进入新的确认性测试集。正式训练、独立测试及新数据四组闭环仍需完成 [idea.md](../../../idea.md) 的全部依赖。
