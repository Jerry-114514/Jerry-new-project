# 搭建与运行验证记录

日期：2026-10-22

## 交付范围

本轮落实“按实验方案先实现搭建、把代码跑通并上传必要数据”的开发任务。验证对象是实验基础设施和可执行入口，不是研究假设、论文创新或大模型效果。

| 实现要求 | 当前代码或数据 | 实际验证 |
| --- | --- | --- |
| 原始要求与来源 | `requirements.py`、SFT 的来源区间 | 支持语法的区间与原文逐字匹配，不支持时明确失败 |
| 可追踪执行与隔离修复 | `core.py`、`runner.py` | 被拒绝候选不提交，写入后恢复仍保留历史违规 |
| 分析与评分 | `analysis.py`、可选风险模型 | 满足、违反、未知分开；学习评分不覆盖硬约束 |
| 固定及动态对照 | none、fixed、fixed-full、dynamic | 640 次脚本运行，固定完整修复作为强对照；未制造默认动态优势 |
| 依赖修复范围 | `planner.py` | 局部修改破坏报告时被拒绝，依赖组修复与完整修复可通过 |
| 独立结果评价 | `oracle.py` | 不调用执行器求解；必需检查不可空真，报告描述实际输出 |
| 数据与重放 | 40 任务、160 轨迹、320 诊断视图 | 640 次运行、160 诊断轨迹和神经模型运行记录均可重放 |
| 监督语言模型训练 | `neural.py`、320 条 SFT 文本对 | 真实微型因果 LM 梯度更新、目标屏蔽和损失汇总 |
| 动态学习率 | 预热余弦、平台调度 | 控制器窗口、下界、冷却、恢复；注入验证曲线时实际优化器 LR 降低 |
| 断点恢复 | `latest.pt` 生成入口 | 两种调度下，中断续训与连续训练的 CPU 张量逐位一致 |
| LoRA 与推理 | `neural_audit.py`、样例模型 | 适配器实际训练、保存、重载和生成；本地模型作为分析器被调用 |
| 模型错误和成本 | `model_backend.py` | 无效 JSON 与虚构证据不伪装成成功；本地输入输出 token 有界并记录 |
| 上传内容 | 代码、配置、合成数据、日志和微型模型 | 不上传环境依赖缓存、临时 `.pt`、原始 PDF 或任何密钥 |

本地包含可选 ML 依赖的完整测试共 **40 项通过**。未安装可选 ML 依赖时，神经测试会明确跳过；这不能替代完整训练验证。GitHub 工作流分别验证核心的 Python 3.11/3.14 和 CPU 神经模型路径。

## 复现入口

```bash
python -m unittest discover -s tests -v
python -m intentlab build-data --out runs/data
python -m intentlab run --out runs/complete
python -m intentlab run --redact-events --out runs/redacted
python -m intentlab.sft_data --out runs/sft
```

安装可选 ML 依赖后执行真正的神经模型审计：

```bash
python -m intentlab.neural_audit --data runs/sft --out runs/neural-audit
```

安装步骤和模型接入见[神经训练指南](neural-training.md)，核心命令见[实现指南](implementation-guide.md)。必要数据说明见[数据说明](../data/README.md)。

## 结果边界

- 默认脚本故障是人为构造的，重复轨迹不构成独立模型样本。
- 神经 smoke 使用随机初始化的微型模型，其无效 JSON 已保存；不声称诊断能力达标。
- 本轮自然验证曲线不一定触发平台衰减。用于验证衰减接线的受控曲线单独留在测试中，不作为真实效应结果。
- QLoRA 实现和 5090 配置入口已经提供，但未在 5090 上实测。正式训练需要兼容 CUDA 环境、预训练模型与核验数据。
- 任意自然语言理解、人工标注质量、新颖性、研究显著性和真实部署收益不由本次工程验证证明。
