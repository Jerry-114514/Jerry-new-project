# 共享底座的可复算核验计划

2026-10-23，正式测试模型输出生成前制定。此前默认关闭的实现见[开发报告](shared-base-residency-development.md)。本次增加 `python -m intentlab.residency_probe`，让实际9B测量复用已检查的入口，而不是依靠手工比较截屏或墙钟估算。

入口只接受完全由train/validation组成的公开执行任务文件；包含test/OOD则拒绝，且不打开独立参考或gold。从任务ID排序中固定选前两条，每条按actor→analyzer→actor运行；两次actor提示完全相同，检查分析器调用后是否污染执行角色。所有提示来自现有LanguageModelActor与SchemaLanguageModelAnalyzer，未根据效果选择。两条输入、初始快照不等于全体真实修复历史，结论只覆盖本次工程核验。

依次执行以下模式，不搜索模式顺序或随机种子：

| 模式 | 角色切换 | 任务边界 | 实际检查项 |
| --- | --- | --- | --- |
| cold-task-reload | 原有按路径卸载/重载 | 每任务释放 | 六次调用、六次加载 |
| shared-condition-resident | 一个底座，actor禁用LoRA | 重置账本和记录，复用权重 | 六次调用、一次加载 |

每次生成保留完整返回token序列（含特殊token）、文本、prompt哈希和usage。比较全部六次调用及除elapsed_seconds之外的完整账本；除去时间不删除失败、调用角色或计费字段。两模式均计入实际装载、生成及最终释放时间，另报加载耗时与CUDA峰值allocated/reserved。前后比较全部角色资产字节SHA，不合资格、生成错误、输出或计费不一致、资产变化都写失败状态，不能自动换提示重跑到通过。逐调用文件与失败时的账本保存；既有输出目录拒绝覆盖。

工程9B核验固定使用官方原始底座、已有长历史两步压力实验的适配器、两条开发任务、每调用最多128新tokens、17408上下文、每任务49152共享tokens。总计12次调用，生成上限1536新tokens；该短输出检查不能保证正式1536-token输出或所有长历史下完全一致。压力适配器不充当正式D端点。使用GPU租约，已有CUDA任务则拒绝装载，不与450次控制器开发选择并行占卡。

远端串行启动器按既有监督进程的PID及启动tick等待；必须同时看到该进程终止、completed/exit0、完整150×3记录及选择器校验通过，才允许开始。观察超时或句柄缺失不算成功，失败不自动重启。核验前再次检查来源commit/工作区、官方资产、预算守护存活且余量足够；子进程设30分钟超时，超时中断并保留失败，整机原预算保护继续有效。队列部署后的实际PID和状态保存在私有运行记录；本文是预先计划，不冒充已完成9B结果。

真实微型Transformer集成已运行上述生产入口，原始tokens、账本及资产一致，实际断言六次加载对一次加载；另验证超小上下文明确失败并留下状态/账本、重复输出目录被拒。首次4096-token微型夹具因其小词表编码长度较大被硬上限拒绝，日志保留；改为足够大的微型位置容量，正式Qwen上下文没有改变。新加三项轻量检查覆盖开发集限定、固定提示次序、计费比较字段与生成观察器在异常后的还原。

本地279项检查包含16项可选ML跳过，其余通过；独立服务器CPU环境全部279项通过、无跳过，测试日志140.729秒，驱动总计142.299秒，未用GPU。见[原始证据](../examples/results/formal-m3z-residency-probe/README.md)。

9B核验尚未完成。即使通过，也只支持在预冻结阶段考虑采用新的统一常驻政策，不能直接改动已冻结结果或据两条任务外推全阶段一定省多少小时。正式M6/M7入口目前仍逐任务冷启动，共享选项默认关闭；最终政策、预算可行性及协议冻结待实测后处理，正式训练0/6。

```bash
python -m intentlab.residency_probe --actor /local/official/base --analyzer /local/engineering/adapter --tasks /private/development-tasks.jsonl --out /private/new-probe-directory --device cuda --max-new-tokens 128
```
