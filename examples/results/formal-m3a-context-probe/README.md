# M3a：上下文与合成硬件压力证据

2026-10-23。开发/合成硬件压力范围，不是正式训练或质量结果。执行器代码 `8ab602a`，实际源码快照与本地 104 个源码/配置文件一致；未改训练器。该提交的核心与神经模型 CI 已全部通过。本轮新增独立资源脚本，直接以真实 tokenizer 和实际 GPU 运行验证。

新训练候选 24 个零样本诊断提示为 **727–1,420 tokens**；草案 2048 上下文内全部可预留 512 tokens。未测真实少样本及审核后的监督目标。

两档合成 QLoRA 压力测试各完成两次更新，实际序列分别精确为 1024/2048 tokens，微批次1、累积2、rank16/alpha32、NF4/BF16。每例目标仅为无关的硬件测试字符串，不含任务标签。PyTorch reserved 峰值分别 **17.51/24.13 GiB**，allocated 分别 **16.82/20.18 GiB**；两者不能相加。整次进程墙钟分别 **35.21/36.99 秒**。这不保证其他负载、RAM、4096 tokens 或正式总耗时。

## 文件与复核

- `lengths.json`：逐视图实际输入 token 数、prompt 哈希和剩余生成额度，没有标签。
- `context_probe.py`：长度审计、精确分词后生成合成压力数据；默认只接受 train/validation。
- `data-1024/`、`data-2048/`：实际使用的数据和校验值；test 文件故意无效。
- `attempts.json`、`run_stress.py`：原始执行命令、两个进程的状态和墙钟。runner 是本次固定 AutoDL 路径的原始记录脚本，复现实验须使用新的输出目录，不能直接覆盖原目录。
- `train-*/result.json`、`run_config.json`、日志及导出配置/选择元数据：实际暴露量、曲线、梯度及显存。模型二进制未归档，不能作为长期模型备份。
- `runtime-identity.json`：Python/依赖、原始源码、脚本 SHA、运行后验证的 13 项官方模型资产。
- `failures.json`：训练前脚本命名与精确长度构造的两次准备失败及修正。未将它们伪装成模型训练失败；两次训练本身均通过。

无需 ML 依赖的结构与算术复核：

```bash
python examples/results/formal-m3a-context-probe/audit.py
```

使用实际本地官方 tokenizer，重新生成逐视图长度及压力数据并逐字节比较：

```bash
python examples/results/formal-m3a-context-probe/audit.py --model /root/autodl-tmp/models/Qwen3.5-9B
```

两种复核分别保存 `verification.json` 与 `tokenizer-verification.json`；后者已在 AutoDL 实际通过。无需为了复核再次进行梯度更新。

## 正式工作仍缺

人工审核数仍为 0。真实目标长度、强基线少样本、长历史、稳定吞吐和恢复、RAM、六组总预算及具名审核未完成，`formal_budget_approved=false`。无关目标的 loss 与适配器不作任何诊断质量结论，不用于正式端点。见[资源说明及冻结前清单](../../../docs/context-budget-development.md)。
