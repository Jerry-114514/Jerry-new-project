# M3b：真实原始 9B 的零样本 Schema 开发基线

2026-10-23。仅为公开 train 数据上的开发检查，不是正式 M3/M5、人工真值或微调收益验证。执行代码 `6914f05`，检出在运行后保持干净，106 个源码/配置文件与本地匹配。该提交的全部核心及神经模型 CI 已通过；本轮未改生产代码，复用了已通过 182 项 AutoDL 测试的推理、解析与公开规则实现。

A 使用官方原始 Qwen3.5-9B 和完整 Schema，无少样本；24 视图全部生成，异常 0。严格/既定归一化均通过 **23/24**，引用查找检查通过 **23/24**。唯一失败为 Markdown 围栏，没有事后剥离或重试。实际用量 29,406 tokens，生成阶段 150.24 秒；不含先前加载和权重哈希，不是整体运行墙钟或训练时间。

23 个可解析视图的 92 项预测为 satisfied 80、unknown 8、violated 4，另 4 项不可解析。这是预测分布，不是准确率。24 个视图来自 12 次执行、四个未核验来源簇，不是 24 个独立任务。

C 复用公开规则入口，24 个输出均可解析且引用有效，0 模型调用；不读取独立参考或人工标签。C 状态为 satisfied 48、unknown 24、violated 24。A/C 在 92 项可比较预测中有 48 项分歧，另 4 项不可比较；该分歧不是错误率或规则正确率。所有 12 个 snapshot 视图中 A 的 R_INPUT 为 satisfied，保留为待人工核验的线索。

## 记录与复核

- `cases.jsonl`、`tasks.jsonl`：实际诊断视图与公开执行合同，没有私有参考或人工答案。
- `preflight-lengths.json`：此前实际官方 tokenizer 长度检查，逐例与本次账本核对。
- `inference/`：原始 A 输出、每例调用及完整 token 账本、运行清单；格式失败仍保留。
- `rule/`：C 输出及其无模型调用的公开规则记录；不能作为人工标准答案。
- `interface-report.json`：严格与归一化分别统计，全量分母、可见性分层、按要求状态及模型/规则分歧。
- `runtime-identity.json`：实际依赖、源码、运行后 13 项官方资产校验及前后权重指纹一致性。

```bash
python examples/results/formal-m3b-schema-baseline/audit.py
```

无需加载模型。复核重建各例提示、账本和上下文额度，检查实际输入 token 与预检一致，重算严格/归一化、引用查找、C 及状态分歧。C 临时重建只读取公开合同，不改变原始输出。没有重新运行 A 模型前向或改生成结果。

`audit.py --write-rule` 是一次性创建 C 目录的采集选项，已有目录时拒绝覆盖；复核不使用该选项。原始 A 的采集命令如下，复现时必须使用新的输出目录：

```bash
python -m intentlab.formal_inference --cases cases.jsonl \
  --model /root/autodl-tmp/models/Qwen3.5-9B --device cuda \
  --max-new-tokens 512 --token-budget 8192 --context-limit 2048 --out NEW_INFERENCE_DIRECTORY
```

本目录是协调人材料，初审者只能收到既有独立盲包，不应先看到预测、规则答案、分歧或方法信息。人工审核仍为 0，B 尚未运行，正式训练和语义准确率均未开始。详见[开发说明](../../../docs/schema-baseline-development.md)。
