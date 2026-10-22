# 单轮修复数量 k：开发实现与正式消融准备

日期：2026-10-22。依据 `idea.md` 第六节。当前是工程开发方案，未冻结正式协议，未完成 M7。既有 `dynamic` 策略及已发布结果保留原义；新增策略名为 `fixed-k` 和 `dynamic-k`，不能混用。

## k 的定义和公共信息边界

k 是一轮选择的**违规根要求数量上限**，不是动作数、实际 token 或依赖扩展后的要求数。两个新策略使用相同的根要求排序（硬约束优先，其次要求 ID），均只选择分析器判为 violated 的要求，然后执行相同的公开依赖图传递闭包。unknown 参与严重程度计算，但不会冒充已证实违规而直接成为修复根。

依赖扩展后的目标数可能超过 k，甚至使不同 k 得到相同目标。因此记录 `requested_k`、`selected_root_count`、`roots`、`target` 和 `expanded_target_count`，分析时不能只看名义 k。

目前的严重程度为确定性启发式，不是学习得到的风险概率：

`severity = Σ[要求权重 × 状态权重] / Σ[要求权重]`

开发配置中硬要求权重为 2，其余为 1；violated、unknown、satisfied 的状态权重分别为 1、0.5、0。`dynamic-k` 根据严重程度达到的阈值数量选择 `k = 1 + count(severity >= threshold)`，阈值为 0.25、0.5，最大 k 为 3。边界包含等号；实际根数还受违规要求数限制。`fixed-k` 使用同一配置中的固定值，不依严重程度调整数量。

配置必须显式提供，见 [开发配置](../configs/intensity.development.json)。拒绝 NaN、无穷、布尔数值、倒序阈值、不完整判断和被更改的公开硬约束属性。控制器不读取离线真值、最终指标或学习风险分数，也不根据拒绝次数改变映射。

两组共用最大修复轮数、工具步骤上限、硬 token 账本、候选克隆、独立硬检查和分析器接受门控。历史隐藏且存在 unknown 时，两组采取相同的一次补证逻辑；历史已可见时不会重复读取。控制器只选择目标，不保证模型会按目标正确修复，也不绕过硬检查。分析器把错误误判为 satisfied 时，两种 k 都可能完全没有触发机会。

## 运行和重算

以下命令只允许 train/validation 开发材料；不接触正式 test/OOD。输出目录须不存在。固定执行模型与分析模型均需明确指定，其他预算与现有开发协议相同。

```bash
python -m intentlab.execution --tasks runs/inputs/tasks.jsonl --references runs/inputs/offline-references.jsonl --out runs/intensity-model --actor-model /root/autodl-tmp/models/Qwen3.5-9B --analyzer-model /root/autodl-tmp/models/Qwen3.5-9B --device cuda --policies fixed-k dynamic-k --intensity-config configs/intensity.development.json --max-tool-steps 3 --max-repairs 3 --context-limit 4096 --max-new-tokens 512 --token-budget 16384 --actor-envelope extract
python -m intentlab.execution_audit --tasks runs/inputs/tasks.jsonl --references runs/inputs/offline-references.jsonl --runs runs/intensity-model --out runs/intensity-replay.json
```

重算器依据每次提议前的公开分析结果，核对完整配置、严重程度、根数、根 ID 与依赖闭包；拒绝的候选不会成为下一轮的已提交判断。工具重放、离线指标和共享预算仍分别核验。该检查证明记录内部可重算，不证明分析器语义正确或公开依赖图完备。

另有明确注入“初始只校验、缺少全部交付物”的规则执行器检查：

```bash
python scripts/audit_intensity_development.py --config configs/intensity.development.json --out runs/intensity-controlled
```

这是 ScriptedActor 工程控制，使用已有 8 个开发源任务；不是自然模型错误、人工审核或 token 效率实验。分别使用 `fixed_k=1,2,3` 的配置运行，不以增加重复次数冒充增加独立任务。实际结果及限制另见 [开发报告](repair-intensity-development-report.md)。

## 正式登记前仍需完成

1. 在独立、审核过的开发任务中评估严重程度与错误类型；覆盖单一违规、多项违规、依赖扩展重合、硬违规及大量 unknown，不能仅使用人为有利于联合修复的场景。
2. 提前登记固定 k=1、2、3 的同预算对照，并依据开发数据选出主要固定 k；固定排序、依赖扩展、补证、阈值和接受规则。实际公平配置与选择成本均须进入冻结文件，不能只在本指南中描述。
3. 将真实任务、静态参考和执行条件绑定正式冻结与测试揭晓审计。当前开发 CLI 拒绝 test/OOD；提供 JSON 配置不等于正式冻结。
4. 预先登记去掉严重程度反馈的固定 k 消融；若研究 unknown 权重或硬要求权重，需另行定义条件与搜索预算，不在看过测试结果后追加确认性比较。
5. 按源任务配对统计成功率、修复新增违规、拒绝率、根数/扩展数、调用和实际 token。必须报告零次修复机会及不同 k 目标实际相同的比例；没有作用机会时不能据此判定控制器优劣。

学习率控制与该修复数量控制分开。当前实现不包含风险反馈学习率、LODE 或新的学习率算法；六次正式训练、人工审核和正式消融仍未完成。
