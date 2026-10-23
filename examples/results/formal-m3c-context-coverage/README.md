# M3c：新来源提示长度、显存失败与压缩候选

104 个开发视图、零样本、完整证据、不读标签。tokenizer 与当前推理/训练共用 `prompt_ids`。原提示范围 727–4,691 tokens；预留 512 输出时，2048/3072/4096 上下文分别有 73/31/6 个视图不足，另有 56/13/3 个连一个输出 token 都无法分配。

一项离线格式提案将证据目录中重复的值改为空值，只保留全部合法引用键及明确查找说明；完整 public 及输出 Schema 未变。104 个视图均能确定性重建原目录。候选提示范围 660–2,710 tokens，预留 512 后 2048/3072/4096 分别有 39/1/0 个不足。没有改默认提示，没有进行新格式推理或训练，也未证明模型行为保持。

同一原始 9B、NF4/BF16、rank16/alpha32、微批次1/累积2的合成硬件压力：4096 长度失败，日志为 Triton/CUDA out of memory，只有 run_config，没有成功结果；3328 长度完成两次更新，allocated 峰值约 24.38 GiB、reserved 约 26.40 GiB。训练测试读取禁用，合成 test 故意无效。目标是无关硬件字符串，不是任务标签，适配器不能用作实验端点。没有测 48/80GB 硬件，不将此推断为容量保证。

`runtime-identity.json` 与 `summary.json` 仅描述最初 tokenizer 测量阶段，故 GPU/训练测量字段为 false；后续 GPU 证据另见 `hardware-summary.json`、两份 attempt、日志与训练记录。`official-assets-after-run.json` 对硬件尝试后的全部 13 项原始资产再核验。

只发布长度、提示哈希、环境、命令、日志及无任务内容的合成压力数据；私有请求/表格/模型原文不在本目录。`measure-driver.py`、`compact-driver.py`、两个 stress driver 和 capture driver 是本次实际脚本，含实例路径及批次输出；不得直接重跑覆盖旧批次。

默认 `audit.py` 核对算术、哈希、两次硬件状态及范围声明；另给 `--model PATH --injected PATH --natural-root DIR` 时，用真实 tokenizer 和私有公开材料重算原/候选提示长度，核验每条哈希、证据目录重建及合成序列长度，不做新推理或训练。

正式预算仍未批准，少样本 B 与真实审核后的 SFT 目标均未测量；正式六次训练未启动。解释与下一步见[预算报告](../../../docs/context-coverage-budget.md)。
