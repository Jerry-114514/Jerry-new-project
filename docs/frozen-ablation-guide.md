# M7 第一阶段冻结消融

本入口使用正式协议预先绑定的控制计划，在 M6 完成后运行全部执行强度对照。它不实现学习率“损失加风险反馈”控制器；该第二阶段探索及新未见测试要求仍按 idea.md 保留。当前只有合成工程数据的微型模型验证，正式 M7 未启动。

## 前置条件与固定范围

先完成 [开发选择与控制计划](controller-plan-guide.md)，在正式冻结前绑定所有固定 k 的 validation 运行、强固定 k 的选择及风险权重控制。随后依次完成六组训练、M5 封存诊断和 M6 封存闭环。M7 预检核验 M6 完成凭据，不重新打开开发选择文件、原始人工 review 或 gold。

默认 max_k=3 时共有六个条件：fixed-k=1、2、3，dynamic-k，dynamic-k 移除 hard 严重度权重，dynamic-k 移除 unknown 严重度权重。max_k 取冻结值，程序自动包含所有固定 k，不允许只挑 k=1 或省略不利条件。

所有条件开启独立硬检查，共用模型、公共输入、要求优先排序、依赖扩展、修复及工具步数、接受规则、上下文和共享 token 上限；每个条件/任务都冷启动。只改变所登记的根要求数量策略或对应严重度权重。根数量、依赖扩展后的目标数及每轮决策均保留。

强固定 k 从开发报告读取，不根据 M6 或 M7 测试成绩再选。权重移除保持独立硬检查开启，也不取消硬要求优先排序。若原 hard_weight=1 或 unknown_weight=0，参数没有变化的控制会列入 `upstream.parameter_noop_controls`，不得据此声称机制差异。即使参数有变化，观察中未出现相应风险状态也可能使实际 k 不变，须报告修复机会与暴露量。

## 1. 交互并封存全部控制

以下路径为满足正式前提后的示例；使用冻结的源码和 venv，输出目录须不存在：

```bash
python -m intentlab.frozen_ablation interact --protocol runs/formal-private/protocol-v2.lock.json --binding runs/formal-private/execution-models.lock.json --predictions runs/formal-private/diagnostic-predictions --diagnostic-reveal runs/formal-private/diagnostic-reveal --execution-interactions runs/formal-private/execution-interactions --execution-reveal runs/formal-private/execution-reveal --out runs/formal-private/ablation-interactions
```

该命令不接受临时的 k、权重、预算或模型覆盖。缺少绑定控制计划、M6 凭据不完整或属于另一协议时，在建立 M7 尝试记录前拒绝。模型阶段不打开独立执行参考，全部条件完成后才封存。每条记录 flush，失败保留在分母中，原始交互不含离线 metrics。

M7 与 M6 使用同一个交互/核验/离线评分引擎，减少各组无意的行为差异。M7 manifest 的 kind 和上游哈希单独标识，绑定 M6 完成凭据、控制计划及开发所选强固定条件。

## 2. 核验、揭晓和完成凭据

各子命令均带同一组基础参数：`--protocol`、`--binding`、`--predictions`、`--diagnostic-reveal`、`--execution-interactions`、`--execution-reveal`，含义与上例相同。

- `verify` 再加 `--interactions runs/formal-private/ablation-interactions`：检查全部条件和任务覆盖、设置、账本、角色身份、每轮 k 及工具重放，不读参考。
- `reveal` 再加上述 `--interactions` 和 `--out runs/formal-private/ablation-reveal`：先核验封存，独占创建并 fsync 保存 ablation-reveal claim，之后才读取冻结独立参考并评分。
- `verify-reveal` 再加上述 `--interactions` 和 `--ablation-reveal runs/formal-private/ablation-reveal`：参考删除后仍可核验完成凭据，不重新读取答案。

M7 使用独立的 ablation-interactions / ablation-reveal claim；不能借改输出目录重复揭晓同一协议，也不能把 M6 四条件记录当成 M7。中断或失败保留记录，不自动重启；先检查实际主机/PID，再由协调人记录恢复或修订决定。

输出保留完整原始模型调用、错误及计费；独立评分后的 runs.jsonl、分条件/split 的计数及轨迹审核另存。它们不是任务级显著性分析；M8 仍须按源任务聚合视图/变体，保留配对关系，报告强固定 k、全部固定控制、两种权重控制及多重比较范围。不能用运行数替代独立任务数。

## 工程证据与边界

[M1m 结果目录](../examples/results/formal-m1m-frozen-ablation/README.md)包含完整的开发选择→六组训练→M5→M6→M7 微型 CPU 流程。真实模型每次只生成两 token，M7 的十二次运行全部动作 JSON 失败，完整保留；它验证失败路径、阶段绑定和重放，不评估模型能力。

受控注入测试另验证每个固定 k 的实际请求数、独立硬检查、参考只在封存后访问，以及重算哈希也不能改变冻结条件。注入 pool 在正式作用域被拒绝。实际真实模型流程没有注入后端或评分函数。

工程协议须显式加 `--engineering`。原始工程合成 gold 可公开以重算，正式 gold 则必须依照封存权限处理。临时权重未归档，离线重放不等于重新执行模型前向或持久备份。真实新数据、人工审核、正式预算与冻结、六次正式 9B 训练及正式 M5–M7、M8 统计/备份均仍待完成。
