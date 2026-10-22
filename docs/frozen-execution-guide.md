# M6 冻结四条件闭环

本入口要求先完成 M5 封存诊断与揭晓，再执行 P1–P4。它不替代真实数据、人工审核或正式协议；目前只有微型 CPU 模型工程验证，正式 M6 未启动。

## 固定条件与信息边界

| 条件 | 修复策略 | 独立硬检查 |
| --- | --- | --- |
| P1 | fixed-full | 关闭 |
| P2 | 冻结的 dynamic-k | 关闭 |
| P3 | fixed-full | 开启 |
| P4 | 冻结的 dynamic-k | 开启 |

模型、分析器 mode、D/E 种子、控制参数、历史可见性、工具步数、修复次数与 token 预算均取自冻结协议。没有 CLI 参数可以临时换模型、改条件或基于测试成绩调整 k。

actor 为固定官方原始模型；analyzer 为绑定的验证最优导出。采用原有完整 Schema 和 model/hybrid 配置。hybrid 对当前全部已编码要求以公开规则为准，不能将其成功归因于模型诊断提升。

所有条件按相同任务 ID 顺序运行。每个条件/任务开始前重置共享账本，运行后卸载模型，使各条件都从冷启动开始；最多一个角色模型驻留。每任务交互时间包含角色模型加载，阶段总时间另包含清理和核验开销。保留真实加载、生成、错误与 token 计费记录；失败的未知生成长度按原账本保守扣费。

## 1. 交互并封存

使用冻结源码和环境，在仓库根目录运行；以下路径是待满足前提后的示例：

```bash
python -m intentlab.frozen_execution interact --protocol runs/formal-private/protocol-v2.lock.json --binding runs/formal-private/execution-models.lock.json --predictions runs/formal-private/diagnostic-predictions --diagnostic-reveal runs/formal-private/diagnostic-reveal --out runs/formal-private/execution-interactions
```

预检验证 M5 完成凭据及绑定，不重读诊断 gold；公开合同须与冻结输入一致。交互进程无需执行参考文件和原始 review。actor、analyzer、目标选择及候选接受均不读取独立参考答案。

原 runner 所需的离线回调在此阶段只返回空对象，且仅在单任务交互结束后调用；记录移除占位 metrics、可行性及新增违规字段，明确 `offline_metrics_pending=true`。四个条件全部完成后才写 sealed 状态并绑定原始交互字节哈希。逐次任务记录 flush，错误任务保留在完整分母中。

本协议在导出目录的上一级建立独占 execution-interactions claim。失败保留记录，不自动恢复，不因更换输出目录重新执行同一协议。发生中断时需先核查记录中的实际主机/PID，再由协调人记录恢复或修订决定。

封存核验：

```bash
python -m intentlab.frozen_execution verify --protocol runs/formal-private/protocol-v2.lock.json --binding runs/formal-private/execution-models.lock.json --predictions runs/formal-private/diagnostic-predictions --diagnostic-reveal runs/formal-private/diagnostic-reveal --interactions runs/formal-private/execution-interactions
```

核对四条件完整覆盖、冻结设置、角色路径、预算、动态 k 决策、初始事件边界及真实工具重放；不打开独立参考。

## 2. 全部交互完成后评分

由具有参考访问权限的协调进程运行：

```bash
python -m intentlab.frozen_execution reveal --protocol runs/formal-private/protocol-v2.lock.json --binding runs/formal-private/execution-models.lock.json --predictions runs/formal-private/diagnostic-predictions --diagnostic-reveal runs/formal-private/diagnostic-reveal --interactions runs/formal-private/execution-interactions --out runs/formal-private/execution-reveal
```

先核验封存交互，再独占创建并 fsync 保存 execution-reveal claim，之后才首次哈希和读取静态参考。按已提交事件重建最终状态及初始执行前缀，计算初始不可逆违规、最终合规成功、修复引入违规及成本，保留失败及原始记录。参考发生变化即拒绝，不静默更换参考或挑选任务。

`runs.jsonl` 为新增的已评分记录，原交互文件不改写；`summary.json` 按条件和 test/OOD 分别报告全部运行、源任务组数、可行子集及 token。源任务的多个变体不是独立样本；这些是计数汇总，M8 仍须先按源任务聚合再做推断，不能把运行数当样本量。

完成凭据可在删除参考文件后验证：

```bash
python -m intentlab.frozen_execution verify-reveal --protocol runs/formal-private/protocol-v2.lock.json --binding runs/formal-private/execution-models.lock.json --predictions runs/formal-private/diagnostic-predictions --diagnostic-reveal runs/formal-private/diagnostic-reveal --interactions runs/formal-private/execution-interactions --execution-reveal runs/formal-private/execution-reveal
```

完成凭据是内容核验，不能证明人员身份或替代外部预注册。目录和 claim 须持久保存；命令本身不提供操作系统权限隔离。工程协议须显式 `--engineering`；可注入的单元测试 pool 仅允许 engineering，不能用来填充正式结果。

## 已验证与未完成

[M1k 工程证据](../examples/results/formal-m1k-frozen-execution/README.md)包含六个微型真实训练 worker、M5 九条件诊断和随后八次真实模型 P1–P4 运行。tiny 模型只有 2 个生成 token，八次均失败并保留；这验证失败路径和隔离，不评价模型能力。

另有受控注入单元测试：分析器故意漏报写入输入，P1/P2 接受危险修复，P3/P4 由独立硬检查拒绝；该差异验证控制逻辑，不计作真实模型效果。最初测试替身误将顶层路径当规格字段导致一次本地失败，已修正替身；没有据此改动正式语义。

真实新数据、人工双审、功效/预算与科学审核、正式冻结、六次 9B 训练和正式 M5/M6 均未完成。后续还须接入预登记 M7 消融、M8 聚类/种子统计及持久权重备份，保持原 M1–M8 验收范围。
