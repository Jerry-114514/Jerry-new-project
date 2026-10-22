# M5 隔离诊断：生成、封存、揭晓

本入口落实正式协议的诊断评测交接，不能替代真实数据、双人标注和正式冻结。当前所有端到端验证仍为合成工程数据与真实微型 CPU 模型，正式 M5 尚未启动。

## 运行前提

须先有 schema v2 正式协议锁、全部六组完成的配对训练矩阵，以及通过 [最佳权重绑定](execution-model-binding.md) 的模型锁。固定 A/B/C、D 各三个种子、E 各三个种子，共九个条件；不能从 CLI 改种子、模型、示例或预算。

- A：官方原始模型、完整要求和 Schema。
- B：同一原始模型，加入冻结顺序的已审核 train/validation 示例。
- C：公开执行规格驱动的规则分析器，不读取静态参考答案。
- D/E：全部六组验证集选择的导出，使用与 A 相同的零样本诊断接口。

生成用公开 test/OOD 视图及合同；B 的标签来自已冻结的开发导出。原始 review、仲裁、执行参考和 heldout gold 不需要部署给生成进程。公开 source cases 必须保留，以核对示例元数据；其中只有公开材料，不含审核答案。

每个正式 D/E 导出在实际加载前都检查适配器的基础模型路径，必须指向冻结的官方原始模型，拒绝其他基础权重及 tiny 重建配方。

## 1. 生成全部预测并封存

在冻结源码、环境和模型路径中执行；使用实际 Python venv，输出目录须不存在：

```bash
python -m intentlab.diagnostic_protocol generate --protocol runs/formal-private/protocol-v2.lock.json --binding runs/formal-private/execution-models.lock.json --out runs/formal-private/diagnostic-predictions
python -m intentlab.diagnostic_protocol verify --protocol runs/formal-private/protocol-v2.lock.json --binding runs/formal-private/execution-models.lock.json --predictions runs/formal-private/diagnostic-predictions
```

模型串行加载，遵守单 GPU 保护；所有模型条件使用冻结上下文、输出与 token 总预算，每个证据视图重置。每项生成失败保留空输出、错误及计费记录，后续仍在分母中。规则条件不调用模型，单独标识。

全部条件及全部案例完成后才写 `status=sealed`，绑定公开输入、示例、模型锁及全部原始输出/日志的 SHA256。生成失败的顶层记录保留为 failed；未完成或被改动的输出不能揭晓。

每个协议在导出目录的上一级建立独占 generation claim，保存主机、PID、时间及输出路径。改输出路径不会获得第二次生成机会。它是协作流程保护，不是防篡改注册服务或操作系统权限隔离；协调人须持久保存该目录。

## 2. 一次性揭晓与离线损失

预测封存后，由获准访问答案的协调进程运行：

```bash
python -m intentlab.diagnostic_protocol reveal --protocol runs/formal-private/protocol-v2.lock.json --binding runs/formal-private/execution-models.lock.json --predictions runs/formal-private/diagnostic-predictions --out runs/formal-private/diagnostic-reveal
```

程序先验证预测封存，再以独占创建及 fsync 保存 reveal claim，然后才读取正式 test/OOD gold，核对冻结哈希并评分。不能在揭晓后改提示或选择权重。

输出包括全部条件分 split 的严格/归一化接口、状态和证据索引指标；每个种子的 B 对 D 任务级配对 bootstrap；六组逐案例 `loss_sum`、`target_tokens`、源任务 ID 和 split，及目标 token 加权总损失。证据的语义支持仍需独立审核，不能由引用存在性证明。

六组损失均用导出的最佳参数、相同未量化基础推理精度：CUDA BF16 前向、FP32 求和交叉熵，CPU FP32。逐案例核验六组目标 token 数相同，包含 EOS，不截断超长样本，不用这些损失更新训练器。生成 token 预算和离线 teacher-forcing 损失是不同计量，不能混加。

损失记录逐例 flush；失败保留已完成记录和 failed 清单，不静默丢弃案例、补跑或重选模型。完成后形成带内容哈希的 M5 receipt。现有输出只提供每种子的任务条件置信区间；M8 的种子综合、RQ4 按任务聚类推断、多重比较 Holm 报告仍须补齐，不能据初步区间宣称完整统计验收。

## 3. 无须重新读取 gold 的完成核验

```bash
python -m intentlab.diagnostic_protocol verify-reveal --protocol runs/formal-private/protocol-v2.lock.json --binding runs/formal-private/execution-models.lock.json --predictions runs/formal-private/diagnostic-predictions --reveal runs/formal-private/diagnostic-reveal
```

它核对协议、模型、封存预测、完成状态、六份损失文件及全部产物哈希，不再次打开 gold。该凭据供 [M6 四条件闭环入口](frozen-execution-guide.md)使用；目前仅完成工程验证，正式数据和模型评测尚未开始。

工程协议须增加 `--engineering`；可注入测试后端/测试损失的路径只在 engineering 使用，并在清单中显式标识，formal 拒绝。实际微型端到端测试使用真实模型及真实损失，没有注入后端或损失。

程序中断或失败后的 claim 保留，不自动重启。先核查记录中的实际主机/PID及进程状态，再由协调人记录恢复或协议修订决定；当前入口没有自动续跑。不得删除记录以抹去失败。正式测试材料和训练侧还需独立权限控制，本命令本身不提供物理隔离。

工程证据见 [M1j 结果目录](../examples/results/formal-m1j-diagnostic-protocol/README.md)。其中最初一次夹具遗漏了阶段交接所需的公开合同，入口正确拒绝，原失败日志保留；随后仅恢复公开合同，仍不提供参考、review 或 gold，完成生成后才恢复 gold 进行揭晓。
