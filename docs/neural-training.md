# 神经语言模型训练、恢复与执行接入

日期：2026-10-21

## 已验证的能力和边界

本项目现在提供真正的因果语言模型训练循环，不再只依赖逻辑回归演示。训练支持全参数、LoRA 和有条件的 CUDA QLoRA 分支；支持提示词损失屏蔽、按目标 token 归一化、梯度累积、梯度裁剪、预热余弦和平台调度、检查点保存及恢复。

本轮实际在 CPU 上验证的是随机初始化的微型 GPT-2，约 19 万参数；另验证了该模型的 LoRA 适配器。它是训练与接入的基础设施测试，不是有用的预训练模型，更不是 3B/7B 效果或 RTX 5090 吞吐实验。QLoRA 分支需要合适的 CUDA 环境、bitsandbytes 和用户选定的预训练模型，目前未在 5090 上实测。

## 安装

推荐使用单独的 Python 环境。在 CPU 上复现本轮验证：

```bash
python -m venv .venv
# 激活环境后执行：
python -m pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r requirements-ml.txt
```

Windows 可用 `.venv\Scripts\Activate.ps1` 激活，Linux 可用 `source .venv/bin/activate`。如果使用 CUDA，请先按目标显卡与驱动安装合适的 PyTorch CUDA wheel，而不是上面的 CPU wheel。训练器在请求 CUDA 但不可用时会明确报错。

`requirements-ml.txt` 锁定本轮验证的主要依赖。CI 将轻量核心测试与可选神经模型测试分开，未安装 ML 依赖时会明确跳过后者。

## 数据准备

```bash
python -m intentlab.sft_data --out data/sft
```

得到 216 条训练样本、56 条验证样本和 48 条 smoke 测试样本。输入为原始请求、公开规格、文件快照与可见工具事件；输出为四项要求的结构化判定及证据索引。提示词不含 fixture 的 `oracle`，监督标签由独立最终评估生成；历史不可见时，不能为历史性要求强行提供“已满足”监督。

同一任务的所有变异和证据视图保持在同一集合，按操作族切分。数据仍然是少量代码生成模板，不是人工审查的独立真实基准。测试集合在这里仅验证接口和恢复，不用于宣称效果。

代码中的来源抽取只支持本项目请求模板，返回精确的原文区间，遇到不支持的语法报错。不能将它当作任意自然语言要求理解器。

## 跑通真正的训练与恢复

```bash
python -m intentlab.neural --model tiny --steps 12 --eval-every 4 --out runs/neural-cosine
python -m intentlab.neural --model tiny --schedule plateau --steps 12 --eval-every 4 --out runs/neural-plateau
python -m intentlab.neural --model tiny --mode lora --steps 12 --out runs/neural-lora
```

默认只取每个集合的前 8 条样本以快速验证。正式训练使用 `--limit 0` 并提供充足且核验过的数据。

模拟中断时，保留原计划总步数，只改变停止位置：

```bash
python -m intentlab.neural --steps 12 --eval-every 4 --stop-after 6 --out runs/resume-check
python -m intentlab.neural --steps 12 --eval-every 4 --resume runs/resume-check/latest.pt --out runs/resume-check
```

恢复必须使用同一配置、数据和基础模型身份。检查点包含可训练权重、优化器、调度器、训练步数、已见 token、最佳权重、Python/Torch 随机状态及适用时的 CUDA 随机状态。数据或配置不同会拒绝恢复。本地预训练基础权重还会计算文件内容指纹，远程模型需要明确 revision。

最新检查点与最佳模型分开：`latest.pt` 用于恢复，`model/` 保存验证集选择的最佳模型或适配器，测试损失在最终选择后计算。提示词与 padding 标签均为 `-100`；梯度累积按整组监督目标 token 数归一化，而不是不等长微批次均值的简单平均。

超过上下文长度的样本直接报错，不会静默截掉用户禁止事项或目标输出。输出目录绑定配置，防止不同模式的模型文件混在一起。检查点通过临时文件再替换保存；`.pt` 默认不上传 GitHub，可以按命令重新生成。

## 一键基础设施审计

```bash
python -m intentlab.neural_audit --steps 12 --out runs/neural-audit
```

该命令实际执行：

1. 两种调度各进行连续训练与中断续训。
2. 比较最终可训练张量是否逐位一致、验证历史是否一致。
3. 训练、保存、重新加载 LoRA，并实际生成文本。
4. 加载训练后的语言模型，作为分析器运行两个 held-out smoke 任务。
5. 保存模型实际生成文本、JSON 判定错误、prompt 指纹、token 用量和最终执行评估。

微型模型可能无法生成合规 JSON。无效 JSON、虚构证据索引或不完整要求列表转为未知并记录错误，不自动回退到规则分析器伪装成模型成功。成功调用模型与模型正确完成诊断是两个指标。

本轮审计结果见 `examples/results/neural-smoke/audit.json`。两种调度的 CPU 恢复结果逐位一致；LoRA 重载与生成通过；实际语言模型推理的无效 JSON 被如实记录。该确定性结论仅限于当前 CPU 配置，不能自动推广为 CUDA 上跨机器逐位一致。

## 在执行闭环中使用模型

```bash
python -m intentlab run --model-path runs/neural-cosine/model --model-role analyzer --split test --limit 2 --repeats 1 --max-new-tokens 64 --token-budget 4096 --out runs/local-analyzer
```

`--model-role actor` 使用模型生成工具提议，`both` 同时使用模型执行与分析。微型演示模型没有为工具提议训练，不能期待它完成任务；不合法提议会被拒绝或记录失败。实际任务应换用合适的预训练或微调模型。

本地生成在调用前根据已使用 token、prompt 长度、上下文剩余和生成上限计算预算，prompt 不能容纳时不发起生成。记录实际输入/输出 token 和模型调用数；每个任务单独重置，actor 与 analyzer 共用同一预算。没有声称这种实现自动保证不同模型的运行时间公平。

加载本地模型默认不联网；普通适配器还需要本地可用的基础模型。本轮微型 LoRA 保存了带随机种子的基础模型重建配方，不需要下载基础模型。不要将此机制用于替代真实预训练基础权重。

## 单张 5090 的 QLoRA 配置入口

先安装与目标 CUDA 环境兼容的 bitsandbytes，然后把 `configs/qlora-5090.json` 中的 `model` 改为实际本地模型目录或带 revision 的模型 ID，并按可用数据和预算确认步数：

```bash
python -m pip install bitsandbytes
python -m intentlab.neural --config configs/qlora-5090.json --out runs/qlora-5090
```

显式 CLI 参数覆盖 JSON 配置。示例模型字段是占位符，不是已经下载或验证的模型选择。该配置不是 5090 性能保证；需先短跑确认显存、梯度、token 长度、每步耗时及恢复行为，再增加训练量。下载缓存位于该次输出目录下，默认训练产物不进入 Git。

## 与研究指南的关系

调度器仍采用成熟方法，不能据此宣称学习率算法创新。动态纠偏已经支持依赖闭包扩展与保留全量复检，并增加 `fixed-full` 强对照；要求图目前是显式规则，不是学习得到的通用图。

可通过 `--risk-model` 使用轻量分类器对已确认违规的修复目标排序，评分不覆盖硬约束判定。真实大模型质量、任意自然语言要求解析、人工标注可信度及完整四组研究实验仍需后续研究，而不是由本次 smoke 自动证明。
