# 正式协议冻结与六组训练入口

本指南落实 [idea.md](../idea.md) 的 M1/M3/M4 工程要求。冻结工具和训练矩阵已实现；正式数据、人工审核、功效分析及新任务闭环审核仍未完成，因此现在不能启动确认性 9B 训练。

正式协议现要求 schema_version=2，增加执行任务、独立参考、结构化人工核验、分析器选择及 k 消融绑定，见 [v2 执行协议说明](execution-protocol-binding.md)。旧 v1 仅保留工程兼容；下文文件名中的 v1 是历史命名示例，不代表可以用旧 schema 冻结正式运行。

六组训练完成后须执行[最佳权重绑定](execution-model-binding.md)，核验实际导出与验证最优参数相符，并按冻结设置选择分析器。随后按 [M5 隔离诊断指南](frozen-diagnostic-guide.md)生成、封存和一次性揭晓，再接 [M6 冻结四条件闭环](frozen-execution-guide.md)。这些工程工具不代表正式协议或实际评测已完成。

AutoDL 已建立独立源码检出 `/root/autodl-tmp/Jerry-formal-20261022`，准备检查时 commit 为 `1466bf358b5a770f8796081722b1e620d9d5ed0f`、工作区干净，使用既有 `/root/autodl-tmp/intentlab-venv/bin/python`。见[检出记录](../examples/results/formal-m1c-engineering/source-checkout.json)。该检出尚未冻结正式协议，也没有启动正式矩阵；以后部署新代码前仍须核查活动进程及版本。

后续该旧工作树出现其他改动，已保留原状。v2 代码另部署到 `/root/autodl-tmp/Jerry-formal-v2-20261022`；在 `02ba2d9` 干净检出中实际准备检查仍有 13 项缺失，见[部署记录](../examples/results/formal-m1h-execution-binding/deployment.json)和[准备报告](../examples/results/formal-m1h-execution-binding/readiness-clean-checkout.json)。这只证明代码部署及缺口核验，正式数据/审核/封存尚未完成；显卡占用由运行时独占保护另行核查。

## 1. 准备可审查协议

在 AutoDL 上使用已验证的 venv 和一个干净、已提交的 Git 源码检出。将 [协议草案](../configs/formal-protocol.draft.json) 复制到忽略的私有工作目录，再填写真实路径和开发阶段确定的参数；不要为了通过检查把缺失审核写成已完成。

草案中的 1,000 次更新、2,048 上下文和预算数值是待验证起点，不是已确定的正式参数。训练量必须覆盖至少一遍实际训练视图，最终长度和步数须根据新数据的长度、吞吐与开发结果确定。600/150/200/100 是当前源任务数量规划下界，功效分析若要求调整，应先修改方案并记录理由，再冻结。

```bash
mkdir -p runs/formal-private
cp configs/formal-protocol.draft.json runs/formal-private/protocol.final.json
```

协议必须包含：新任务与双审/仲裁文件、审核导出目录、原始分析模型和固定执行模型、训练参数、两个调度及三个种子、明确的少样本 case ID、A–E 和 P1–P4 条件、统一预算和任务级统计方法。

`statistics.analysis_plan` 现须明确 [M8 统计核心的方法和范围](research-statistics-guide.md)，包括固定种子汇总、源任务聚类、token 加权损失、检验假设和全部次要比较的 Holm 家族。该登记与计算核心不等于 M8 完成或科学假设已得到证明。

审核证据文件分别覆盖功效分析、长度与计算预算、语义近重复检查、来源与发布、测试封存、模型身份、新任务执行与独立 oracle、控制器消融。工具绑定这些文件的内容，不替代对其科学合理性和真实性的审核；人的身份声明也不等于程序证明了其为真人。

语义去重证据现须使用[结构化来源/模板审查](source-template-review-guide.md)，绑定实际案例、逐来源理由与全部候选对；正式协议拒绝空白模板、自动初筛结果及旧文本占位。冻结摘要可在训练阶段验证而不重新读取协调人的私有案例或审核文件。

其中 `controller_ablation_audit` 须为[结构化控制计划](controller-plan-guide.md)，引用完整 validation 固定 k 开发选择报告，并经两名独立人员审核。空白模板和 engineering 结果不能用于正式冻结；训练阶段不会重新打开这类私有审核材料。

M6 完成后使用 [M7 冻结运行入口](frozen-ablation-guide.md)，执行全部固定 k、动态 k 及权重控制；不能从 CLI 修改已冻结的条件。当前只完成微型模型工程验证，正式阶段依赖仍未满足。

## 2. 检查准备状态

```bash
/root/autodl-tmp/intentlab-venv/bin/python -m intentlab.protocol check --spec runs/formal-private/protocol.final.json --out runs/formal-private/readiness-v1.json
```

准备不足时返回 `ready=false` 和阻塞项，退出码为 2，不会加载模型或训练。目前的审核、数据与功效分析依赖确实尚未满足，不能把这类输出改为 ready。

检查不仅相信 manifest 的声明：它重新匹配审核输入、要求与证据，核对 train/validation 的完整行内容及 heldout 的公开输入和 gold。两位审核者须不同，分歧须有独立仲裁。少样本只能选择训练/开发案例；同任务、模板、规范化请求和 OOD 族的隔离沿用数据审核规则。

## 3. 锁定模型和协议

[官方资产索引](../configs/qwen35-official-assets.json) 来自前期保存的官方固定 revision 元数据，包含四个基础权重分片及 tokenizer/config/chat template 等资产的 LFS SHA256 或 Git blob SHA1。独立校验命令如下：

```bash
/root/autodl-tmp/intentlab-venv/bin/python -m intentlab.protocol model-check --model /root/autodl-tmp/models/Qwen3.5-9B --out runs/formal-private/model-assets-v1.json
/root/autodl-tmp/intentlab-venv/bin/python -m intentlab.protocol freeze --spec runs/formal-private/protocol.final.json --out runs/formal-private/protocol-v1.lock.json
```

正式锁定会验证两种角色都来自批准的官方原始 9B revision，拒绝历史适配器作为初始权重。记录完整资产的 SHA256，包含 `chat_template.jinja`，并锁定当前干净 Git commit、运行代码/配置、Python 和指定依赖版本、数据、证据文件及全部协议设置。

锁定文件使用独占创建，不能覆盖。修改数据、模型、tokenizer、代码、依赖或协议后，应形成有理由记录的新版本；不能覆盖原记录来追改测试后方案。内容哈希不等于第三方预注册时间戳；正式预注册或公开封存仍须单独完成。

## 4. 只校验训练可见资料

```bash
/root/autodl-tmp/intentlab-venv/bin/python -m intentlab.protocol verify --lock runs/formal-private/protocol-v1.lock.json --phase training
```

该模式核对源码、固定模型、tokenizer、依赖以及 train/validation 文件，不打开测试 gold 或原始人工标注。`--phase all` 则重新校验全部封存资料，只供协调/离线审计使用。训练器始终启用 `defer_test=true`，也不会自动导出测试损失。

训练矩阵每个子进程开始前重新检查冻结内容。它不依赖“测试集没有发生变化”的口头声明，也不需要读取测试标签来决定训练行为。

## 5. 串行运行六组主训练

```bash
/root/autodl-tmp/intentlab-venv/bin/python -m intentlab.matrix --lock runs/formal-private/protocol-v1.lock.json --out runs/formal-training-v1
```

执行顺序为 seed 0 的 cosine/plateau、seed 1 的 cosine/plateau、seed 2 的 cosine/plateau。每组使用独立进程，退出后再启动下一组，适用于单张显卡。两组同一种子共享基础权重、数据顺序、更新数、样本量和监督目标 token 预算。

`matrix.json` 保存每组状态、进程 PID、主机、退出码、尝试历史、结果和导出资产哈希；每次调用保留原始日志和中间结果副本。组内按验证损失选择模型。全部完成后核对配对训练量，并检查导出模型和恢复检查点确实存在、未被更换。

权重指纹、模型保存、验证和进程启动都产生开销；速度结论必须同时报告完整墙钟，不能只引用训练循环秒数。

## 6. 中断与续训

```bash
/root/autodl-tmp/intentlab-venv/bin/python -m intentlab.matrix --lock runs/formal-private/protocol-v1.lock.json --out runs/formal-training-v1 --resume
```

已有矩阵不会因为状态写着 running 就重新启动。续训显式使用原配置、检查点及被冻结的总步数；已完成组先核验结果和模型，再跳过。失败/中断且没有检查点时拒绝悄悄从头开始，必须先审查失败并决定后续方案。

控制进程使用独占锁。训练 worker 在自己的 PID 被保存并得到本次启动确认前不会导入 ML 或训练，从而避免“子进程已启动、PID 未记录”期间的重复启动风险。生成失败、进程异常和中断均保留，不会被当作缺失而删除。

只有确认旧控制进程及其已记录训练子进程都不存在时，才可执行锁恢复：

```bash
/root/autodl-tmp/intentlab-venv/bin/python -m intentlab.matrix --out runs/formal-training-v1 --recover-lock
```

锁来自另一主机、进程仍在运行或无法确认状态时会拒绝恢复。原锁归档后还需显式 `--resume`；恢复锁本身不启动训练。调试性 `--stop-after-updates` 只用于验证恢复，不改变协议中的训练总步数。

## 7. 已取得的工程证据与剩余工作

本轮 AutoDL 环境全部 79 项测试通过。微型真实模型完成六组训练及一次中断续训，三个种子的两种调度在基础身份、数据指纹、样本暴露、输入 token 和监督 token 上一致。测试在冻结后删除原始审核文件和测试 gold，所有训练仍完成，证明训练路径不依赖这些文件。

这些数据和审核声明是明确标注的单元测试夹具，不是人工研究数据；协议 scope 为 engineering，矩阵要求显式 `--engineering`，不能冒充正式训练。相关状态、尝试记录、原始日志和结果见[工程证据](../examples/results/formal-m1c-engineering/)。

另已在 AutoDL 对官方 9B 当前文件重新校验 13 项资产，四个权重分片和 tokenizer/config/chat template 均匹配固定版本的索引。

剩余工作仍包括：新领域可执行任务与独立 oracle、动态纠偏强度及消融、扩大并审核数据、开发功效与资源测量、实际强提示少样本选择、完整协议封存、六组正式 9B 训练、独立评估、真实闭环和最终统计。工具可运行不等于这些里程碑已经完成。
