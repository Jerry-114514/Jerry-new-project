# 训练后最佳权重绑定

本说明对应 M1/M4 到 M5 的工程交接。它不代表正式训练或隔离评测已完成；真实人工审核仍为 0。

## 核验内容

训练器在每次检查点中保存验证损失、验证目标 token 数、最佳步数和最佳可训练参数。最小验证损失相同时选择首次出现的步数，与训练器原有严格 `<` 更新规则一致；测试损失不参与选择。验证目标 token 数发生变化时拒绝比较。

完成训练后，将恢复的最佳参数与实际导出的 safetensors 逐张量比较名称、类型、形状和数值，并记录参数内容指纹及导出文件 SHA256。参数指纹保留 BF16 类型和标量形状。全参数导出允许额外的非训练缓冲及权重别名；LoRA/QLoRA 导出必须恰好覆盖支持的可训练适配器参数，未知参数映射拒绝处理。

结果文件中的 `selection`、`model/selection.json`、`latest.pt` 的最佳状态和实际导出须相符。最终训练步数不能替代最佳步数。旧结果缺少证明时，不自动认定合格；保留原结果作为历史证据。

## 训练完成后的命令

在与冻结协议相符的 AutoDL 源码、环境和模型目录中执行，输出文件必须尚不存在：

```bash
python -m intentlab.execution_models bind --protocol runs/formal-private/protocol-v2.lock.json --matrix runs/formal-private/matrix --out runs/formal-private/execution-models.lock.json
python -m intentlab.execution_models verify --protocol runs/formal-private/protocol-v2.lock.json --binding runs/formal-private/execution-models.lock.json
```

绑定前要求六组训练均完成，配置恰好符合冻结计划，三对种子的暴露量一致，矩阵尚未进行 heldout 评估，结果/检查点/模型资产哈希完整匹配。所有六组的最佳导出均核验，随后严格按冻结的 D/E 条件及种子选择闭环分析器，不能根据测试成绩换模型。actor 保持原冻结身份；正式分析器还必须是以冻结官方原始模型为基础的 LoRA 适配器。递归绑定导出目录中的 tokenizer 等辅助资产。

工程合成协议须显式增加 `--engineering`，不能冒充正式协议。该阶段使用训练验证模式，不打开原始人工 review、执行任务/参考或 heldout gold；后续正式诊断生成和揭晓仍需独立入口及审计。

## 实际验证与限制

工程测试用真实微型 CPU Transformer 完成六组配对训练及一次中断恢复。训练与绑定前删除执行任务、参考、审核和 heldout gold；绑定仍应成功。未完成矩阵、偏离冻结种子、改动模型资产均应拒绝。

另用真实全参数和 LoRA 训练，固定模拟验证分数以制造首次最优但继续更新参数的情形，核验最佳与最后参数不同、导出等于最佳；修改实际导出张量后拒绝。该分数专用于测试选择机制，不计科研效果。BF16 标量指纹单独核验。

原始日志及矩阵证据保存在 [M1i 工程证据](../examples/results/formal-m1i-execution-models/README.md)。微型权重来自临时测试目录，未作为持久模型备份发布；归档的 JSON 和哈希不能让离线使用者重新逐张量验证已经删除的二进制。

正式 M5 的九条件封存预测、一次性揭晓与目标 token 加权损失入口见 [M5 指南](frozen-diagnostic-guide.md)，随后接 [M6 冻结闭环](frozen-execution-guide.md)；目前都只做工程验证。真实新数据、人工双审、功效/预算证据及正式冻结未完成前，不启动六次正式 9B 训练。
