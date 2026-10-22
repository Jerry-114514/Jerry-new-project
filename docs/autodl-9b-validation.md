# AutoDL RTX 5090：Qwen3.5-9B 微调误差验证

本轮从官方 Qwen3.5-9B 原始权重初始化。模型 revision 为 `c202236235762e1c871ad0ccb60c8ee5ba337b9a`；下载后按官方 LFS SHA256 核验四个权重分片。模型身份也与 [Jerry-vibe-coding 的模型锁](https://github.com/Jerry-114514/Jerry-vibe-coding/blob/fa8945ecc4310edd26e1b9d59dd66c34832e0955/docs/results/protocol-v2-20261016/9b-model.lock.json)一致。

旧仓库包含多模态训练适配器、冻结数据与恢复索引，作为环境和兼容性参考。本轮不加载旧适配器，不将旧项目的评测数据引入当前训练。此选择由用户确认。

## 验证问题与控制

分别检验验证集目标 token 交叉熵是否下降、保留样本的要求状态误判是否减少，以及无效 JSON 是否减少。训练损失下降本身不能证明误判率下降。

先以相同步数、学习率、数据次序和 seed 比较余弦与 Plateau 两种成熟调度。当前是单 seed、小预算 pilot；不能据此宣称显著优势或普遍稳定性。基础模型与微调适配器在相同 BF16 推理精度下评测，避免把训练量化与评测精度混淆。训练日志中的 QLoRA 验证损失另行保留。

采用模型自身的聊天模板，训练和推理共用同一前缀，并关闭 thinking。提示词和 padding 不参与监督。评测保留模型原始输出，不强制将隐藏历史的判断改成 unknown 后再计分。无效结构、重复要求 ID 和不存在的证据索引计为错误；证据索引存在不代表语义引用已经正确。

216 条训练、56 条验证、48 条测试视图按任务操作族隔离。这些是代码生成的开发和 smoke 数据，同任务的多个视图不属于独立样本。模型选择只使用验证损失；所有既定对照均报告，不能看测试结果后挑选较好的 seed 或追加某一组训练预算。

## 运行

在独立虚拟环境安装 `requirements-gpu-5090.txt`，保留实例已验证的 CUDA PyTorch。基础权重放在配置指定的本地目录。

```bash
python -m intentlab.neural --config configs/qwen35-9b-5090-pilot.json --out runs/qwen35-single
python -m scripts.gpu_pilot --model /root/autodl-tmp/models/Qwen3.5-9B \
  --out runs/qwen35-5090-pilot --steps 24 --seeds 0 --diagnostic-limit 0
```

第二条命令执行两种调度，余弦组在原计划中途停止并从检查点继续；该操作验证 CUDA 恢复能够完成，不自动证明与连续 CUDA 训练逐位一致。检查点、适配器和原始日志留在实例数据盘；整理后的配置、指标及必要原始生成记录同步 GitHub。

结果包括同精度验证/测试损失、状态准确率、三类状态召回率、完整样本准确率、无效输出率、实际耗时和显存。闭环另比较 fixed-full 与 dynamic；其执行端仍是脚本 actor，因此不能直接推广为真实自主 agent 的改进。

## 环境边界

实例已核验为 RTX 5090，32607 MiB，PyTorch 2.8.0+cu128，CUDA 张量运算通过。Transformers 5.20.2 提供 Qwen3.5 文本模型映射；本轮只训练文字诊断任务。没有图像输入，不能声称改善多模态定位性能。旧项目的训练耗时不能直接作为本轮耗时，须以新日志为准。
