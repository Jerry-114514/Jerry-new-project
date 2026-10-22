# 强固定 k 的开发选择与消融登记

本工具补齐 M7 前置登记，不等于已经运行 M7。第一阶段仍是余弦/Plateau 主训练与执行纠偏；学习率“损失加风险反馈”控制器按 idea.md 留作后续探索，若查看正式测试后新增控制器，须用新的未见测试集确认。

## 1. 用真实验证运行选择强固定 k

在正式协议冻结前，准备与已审核 validation 合同完全对应的开发执行任务及独立静态参考。只允许 validation，不接受 train/test/OOD。使用明确记录权重身份的开发模型或开发 pilot；它们可能与随后正式训练的分析器不同，须披露差异和开发成本，不能承诺所选 k 在新模型上仍然最优。

```bash
python -m intentlab.controller_plan --tasks runs/formal-private/development/tasks.jsonl --references runs/formal-private/development/references.jsonl --settings runs/formal-private/protocol.final.json --actor-model /path/to/development-actor --analyzer-model /path/to/development-analyzer --device cuda --out runs/formal-private/development/fixed-k-selection
```

程序实际运行 fixed-k=1…max_k，独立硬检查全部开启；角色模型、分析器 mode、上下文、token 上限、工具步数、修复次数及其他参数一致。使用开发预算，不与正式测试结果混合。角色模型资产在全部运行前后分别哈希；发生变化即拒绝。哈希采集和开发试验费用也需计入总预算，不能只计正式训练。

全部失败运行仍在分母中。每个源任务先对其变体取平均，再按源任务等权计算合规成功率；选择规则依次为：

1. 验证源任务平均合规成功率最高。
2. 并列时，源任务平均计费 token 最少。
3. 再并列时，较小 k。

不能因为一种 k 的任务变体多就提高其权重，也不能根据 test/OOD 或后续正式结果重选。输出保留每个 k 的原始运行、模型身份、真实错误、预算、逐工具重放核验及 `selection.json`。报告是开发选择证据，不是外部注册时间戳或人工身份认证。

## 2. 填写消融计划并独立审核

复制 [空白计划](../configs/controller-plan.draft.json)到私有目录，将 `selection_report.path` 填成实际报告的绝对路径，并填实际 SHA256。两名不同的真实审核者核验开发样本隔离、参考、模型与预算、失败覆盖、选 k 计算及控制范围后，填写稳定人员 ID、审核理由并确认 `human_verified=true`。空白模板保持 false，程序不替人生成审核声明。

将协议中的 `evidence.controller_ablation_audit` 指向这份 JSON。已发布的合成单元署名不是真实人员，engineering 报告不能被正式冻结器采纳。

登记第一阶段的完整执行控制集：

| 控制 | 改变内容 | 保持一致 |
| --- | --- | --- |
| fixed-k=1…max_k | 每轮固定根要求数量 | 硬检查、排序、依赖扩展、预算、接受规则 |
| dynamic-k | 使用冻结严重度阈值选择根数量 | 同上 |
| dynamic-k-remove_hard_weight | 严重度计算中 hard_weight 改为 1 | 其他权重、阈值及硬检查 |
| dynamic-k-remove_unknown_weight | 严重度计算中 unknown_weight 改为 0 | 其他权重、阈值及硬检查 |

所选强固定 k 必须包含在完整固定 k 集合中；最终不能只报告 k=1 对照。k 仍按根要求计数，依赖扩展后的目标数另记。移除严重度权重没有关闭独立硬检查或取消硬要求优先排序；这些是启发式严重度的敏感性控制，**不是学习率风险反馈消融**。若原权重已经为 1 或 0，对应控制退化为相同条件，应如实标记，不据此声称机制差异。

## 3. 冻结时核验

schema v2 的正式冻结现在要求结构化计划。旧文本说明仅保留工程兼容，不能以一句“已审核”代替开发选择记录。

冻结器逐项核验全部 validation 合同、每个固定 k、原始工具及独立参考评分、共同预算、选择规则、模型前后资产身份、报告 SHA256 及两名审核者声明，然后将完整计划、选 k 汇总及两份文件的路径/哈希写入 `controller_binding`。

训练验证不重新打开开发选择或审核文件；协调人的 `verify --phase all` 才重新检查和重放。真实微型工程测试在冻结后删除报告、计划、review 和测试 gold，六组训练及后续 M5/M6 仍可完成；这不代表正式数据已准备。

正式主训练的六组、M5/M6 与该第一阶段执行控制仍需按原顺序完成。M7 的冻结运行入口和最终任务级统计尚待接入，不能把计划映射或开发选择报告当作消融结果。

工程证据与负结果见 [M1l 结果目录](../examples/results/formal-m1l-controller-plan/README.md)。微型模型只有两 token 的生成长度，三个 k 均失败；按既定并列规则选择 k=1。它只验证流程，不能得出 k=1 最有效或真实模型无效的结论。
