# M6 冻结四条件闭环

2026-10-26更新。本轮使用已冻结的schema v3程序标签协议，不要求人工双标，不报告人工评估。M5完整评分、六份损失和最终验证已通过，评分归档已实际异机校验，见[M5验收](../examples/results/formal-m5d-diagnostic-results/README.md)。M6已进入P1–P4真实模型交互，见[启动回执](../examples/results/formal-m6a-execution-start/README.md)；启动不等于全部交互、离线评分或M6验收完成。以下冻结入口及预算、模型和条件保持不变。

## 固定条件与信息边界

| 条件 | 修复策略 | 独立硬检查 |
| --- | --- | --- |
| P1 | fixed-full | 关闭 |
| P2 | 冻结的 dynamic-k | 关闭 |
| P3 | fixed-full | 开启 |
| P4 | 冻结的 dynamic-k | 开启 |

模型、分析器 mode、D/E 种子、控制参数、历史可见性、工具步数、修复次数与 token 预算均取自冻结协议。没有 CLI 参数可以临时换模型、改条件或基于测试成绩调整 k。

actor为固定官方原始模型；本轮analyzer固定为D条件seed 0的验证最优导出，mode为model，不能临时切换为规则或hybrid。通用入口仍支持其他预先登记配置；hybrid对当前全部已编码要求以公开规则为准，不能将其成功归因于模型诊断提升。

所有条件按相同任务ID顺序运行。本轮锁定`shared-condition-v1`：每个条件从冷权重开始，条件内复用一个匹配底座及分析适配器，actor调用禁用分析适配器；条件结束释放。每任务重置共享账本及记录，不复用工具状态、提示、答案或KV信息。统一作用于P1–P4及全部M7条件，不能逐条件切换。详见[已登记装载规则](registered-model-residency.md)。

保留每任务真实加载、生成、错误与token计费；失败的未知生成长度保守扣费。条件时间包含加载、全部任务和释放，完整进程时间另包含入口预检及末尾核验。首任务承担冷加载，后续任务复用权重，不能把各任务耗时当作相同冷启动的独立样本。时间效率按完整条件描述，RQ3主指标仍为固定token预算下的合规成功率。

## 1. 交互并封存

使用冻结源码和环境，在仓库根目录运行；以下路径是待满足前提后的示例：

```bash
python -m intentlab.frozen_execution interact --protocol runs/formal-private/protocol-v3.lock.json --binding runs/formal-private/execution-models.lock.json --predictions runs/formal-private/diagnostic-predictions --diagnostic-reveal runs/formal-private/diagnostic-reveal --out runs/formal-private/execution-interactions
```

预检验证M5完成凭据及绑定，不重读诊断gold；公开合同须与冻结输入一致。交互进程不以执行参考或heldout标签作为输入；原人工review不是本轮程序标签流程的依赖。actor、analyzer、目标选择及候选接受均不读取独立参考答案。

原 runner 所需的离线回调在此阶段只返回空对象，且仅在单任务交互结束后调用；记录移除占位 metrics、可行性及新增违规字段，明确 `offline_metrics_pending=true`。四个条件全部完成后才写 sealed 状态并绑定原始交互字节哈希。逐次任务记录 flush，错误任务保留在完整分母中。

本协议在导出目录的上一级建立独占 execution-interactions claim。失败保留记录，不自动恢复，不因更换输出目录重新执行同一协议。发生中断时需先核查记录中的实际主机/PID，再由协调人记录恢复或修订决定。

封存核验：

```bash
python -m intentlab.frozen_execution verify --protocol runs/formal-private/protocol-v3.lock.json --binding runs/formal-private/execution-models.lock.json --predictions runs/formal-private/diagnostic-predictions --diagnostic-reveal runs/formal-private/diagnostic-reveal --interactions runs/formal-private/execution-interactions
```

核对四条件完整覆盖、冻结设置、角色路径、预算、动态 k 决策、初始事件边界及真实工具重放；不打开独立参考。

## 2. 全部交互完成后评分

由具有参考访问权限的协调进程运行：

```bash
python -m intentlab.frozen_execution reveal --protocol runs/formal-private/protocol-v3.lock.json --binding runs/formal-private/execution-models.lock.json --predictions runs/formal-private/diagnostic-predictions --diagnostic-reveal runs/formal-private/diagnostic-reveal --interactions runs/formal-private/execution-interactions --out runs/formal-private/execution-reveal
```

先核验封存交互，再独占创建并 fsync 保存 execution-reveal claim，之后才首次哈希和读取静态参考。按已提交事件重建最终状态及初始执行前缀，计算初始不可逆违规、最终合规成功、修复引入违规及成本，保留失败及原始记录。参考发生变化即拒绝，不静默更换参考或挑选任务。

`runs.jsonl` 为新增的已评分记录，原交互文件不改写；`summary.json` 按条件和 test/OOD 分别报告全部运行、源任务组数、可行子集及 token。源任务的多个变体不是独立样本；这些是计数汇总，M8 仍须先按源任务聚合再做推断，不能把运行数当样本量。

完成凭据可在删除参考文件后验证：

```bash
python -m intentlab.frozen_execution verify-reveal --protocol runs/formal-private/protocol-v3.lock.json --binding runs/formal-private/execution-models.lock.json --predictions runs/formal-private/diagnostic-predictions --diagnostic-reveal runs/formal-private/diagnostic-reveal --interactions runs/formal-private/execution-interactions --execution-reveal runs/formal-private/execution-reveal
```

完成凭据是内容核验，不能证明人员身份或替代外部预注册。目录和 claim 须持久保存；命令本身不提供操作系统权限隔离。工程协议须显式 `--engineering`；可注入的单元测试 pool 仅允许 engineering，不能用来填充正式结果。

## 已验证与未完成

[M1k 工程证据](../examples/results/formal-m1k-frozen-execution/README.md)包含六个微型真实训练 worker、M5 九条件诊断和随后八次真实模型 P1–P4 运行。tiny 模型只有 2 个生成 token，八次均失败并保留；这验证失败路径和隔离，不评价模型能力。

另有受控注入单元测试：分析器故意漏报写入输入，P1/P2 接受危险修复，P3/P4 由独立硬检查拒绝；该差异验证控制逻辑，不计作真实模型效果。最初测试替身误将顶层路径当规格字段导致一次本地失败，已修正替身；没有据此改动正式语义。

上述微型验证为历史工程证据，不计正式模型效果。本轮正式协议及预算已冻结、六次9B训练、模型备份和M5评测已完成，M6正在执行；M6最终验证、M7及M8正式统计、复现和最终发布仍待完成。数据独立性、近重复与程序标签的边界见[M1/M2核对](m1-m2-evidence-review.md)，保持原M1–M8验收范围。
