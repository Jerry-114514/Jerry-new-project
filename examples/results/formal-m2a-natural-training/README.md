# M2a：实际 9B 自然轨迹训练候选

2026-10-23。全部为公开的合成 **train** 候选，无 test/OOD，不是正式基准或人工真值。12 个新编写的领域变体保守归为四个操作模板簇；与旧开发题语义重叠仍须审核，不宣称增加了 12 个独立来源或达到正式样本量。

## 实际运行

在单张 AutoDL RTX 5090 上，用官方原始 Qwen3.5-9B 执行 12 个任务，未加载旧适配器、未训练、未修复。执行代码为 `861c9a6`，运行后检出干净；基础权重与 tokenizer 共 13 项官方资产在运行后校验通过。后验资产检查不冒充正式冻结时的前置模型绑定。

```bash
python -m intentlab.execution --tasks tasks.jsonl --references offline-references.jsonl --out execution \
  --actor-model /root/autodl-tmp/models/Qwen3.5-9B --device cuda \
  --max-new-tokens 768 --token-budget 8192 --context-limit 4096 \
  --max-repairs 0 --max-tool-steps 3 --policies none --analyzer-mode rule
```

静态参考下完全合规 **5/12**，其余 **7/12 未完成要求**；程序异常数 0。21 次模型调用共计费 21,573 tokens（prompt 17,217，生成 4,356）；按任务记录的平均墙钟约 11.76 秒，包含首次加载分摊。全部 21 次响应均经过既有 extract 投影，严格响应合规计数 0。原始输出可能回显输入字段；提取后的可执行动作成功不等于原始 Schema 成功。

这些是自然模型尝试，题目和静态参考仍由模型编写，未获人工审核。没有诊断微调对照，不据 5/12 推断训练收益或新调度效果。

## 标注交付

`annotation-intake/reviewer-packet/` 含 **24 个视图、四个保守来源簇**及空白模板：同一运行分别给完整可信事件和仅快照视图，两者仍共享同一来源/模板。每名审核者需判断 96 项要求；双人合计 48 条审核记录、192 次判断，人工完成数 **0**。

协调人保存 `coordinator-cases.jsonl` 和 `coordinator-provenance.jsonl`。只把 reviewer-packet 发给两位审核者，不能同时发送整个结果目录、规则评分、参考或原始模型回答。公开训练材料不能用于未来盲测，不能保证审核者不会自行检索，因此正式审核仍需登记分发和独立性。

双审及仲裁按[人工流程](../../../docs/human-annotation-workflow.md)执行，批次数量以本报告为准。未审核前不能导出为已核验监督，也不能当作强基线少样本示例。

## 可复核证据

```bash
python examples/results/formal-m2a-natural-training/audit.py
```

复核逐次重建公开模型 prompt，核对 prompt_hash，再将原始回答重放经过相同解析器与工具，复现全部 21 次调用、12 次运行的动作、规则发现、成本计数和静态评分。随后从原始记录重建并逐字节比较 24 个未标注视图和协调人来源索引，不需重新加载模型。不将记录一致性当作证明模型身份或参考语义正确。

AutoDL 最终 **173 项测试全部通过**；本地 163 项通过、10 项缺少 ML 依赖跳过。六项新增检查覆盖：保守分组与静态参考一致性、失败保留、全覆盖与重复拒绝、test/OOD/脚本执行器拒绝、篡改回放/模型与缺失生成拒绝、空白盲包与不可覆盖输出。

最初 Windows 重放因换行和 manifest 中文件枚举顺序失败，记录在 `windows-replay-initial-failure.log`；原 manifest 保存在 `intake-manifest-before-portability-fix.json`。修复统一 LF 和排序序列化后，Windows/Linux 重放一致，完整测试重新运行。未改写任何原始模型回答、动作或结果。初次通过记录为 `tests-autodl-initial.log`，最终为 `tests-autodl.log`。

正式数据、独立新来源及语义去重、双人审核、功效与计算预算、冻结、六次正式训练和后续 M5–M8 仍未完成。本批次只补充训练候选和可审计的自然轨迹，不缩小 idea.md 的验收范围。
