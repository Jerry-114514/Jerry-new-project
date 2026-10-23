# 程序标签正式路线：范围、实现和剩余门槛

2026-10-23。用户已明确选择：“完全采用程序标签，结论限定于明确编码的形式化规格，不声称人工验证”。idea.md已更新为2.0，不再等待人工人员。原人工流程保留供历史复现；当前计划不向任何人分发9600项或320项任务。

## 保留的实验要求

继续完成原M1–M8，包括强少样本原始模型对照、余弦/Plateau各种子0/1/2共六次训练、隔离诊断、P1–P4真实模型闭环、预登记动态控制消融、任务级统计、长期模型备份及GitHub同步。不能因改变标签来源而改为两个上下文替代学习率矩阵，或只测规则分析器。

训练600–1000、开发150–200、测试200及OOD100仍是规划起点，最终数量由开发功效、模板多样性和计算预算决定。参数变体与证据视图不自动变成独立任务。现有WikiSQL训练候选不能转成未公开确认性test/OOD。

## 已实现的离线标注器

`intentlab.programmatic_labels`读取公开任务、固定参考文件和证据视图。它不调用在线transform、public_solution、analyze_execution或evaluate_execution；按独立状态机计算输入保护、校验顺序，按静态参考计算结果，按实际公开文件计算报告计数。已知历史先通过可信虚拟工具重放核验，伪造ok、事件hash或最终快照不一致会被拒绝。

隐藏历史时，快照已变化仍能证明输入违规；快照恢复且历史不可见则为unknown。结果文件不存在可从完整路径清单判违规，不因历史隐藏改为unknown。报告真实计数与结果正确性分别判断。四规则的含义沿用当前显式规则，其中validate_before_write要求至少一次与原始必需字段完整性一致的校验事件；这一约定应在生成规格说明中明确，不能只靠模糊自然语言推断。

绑定检查包括源任务、模板、操作族、划分、请求、输入、要求、规格和参考任务ID；同一来源映射到多个合同目前拒绝，须先建立更精确映射，不能随意选一份参考。参考文件结构经与原执行加载器相同的内存校验。

```bash
python -m intentlab.programmatic_labels --cases /private/cases.jsonl --tasks /private/tasks.jsonl --references /private/references.jsonl --out runs/new-programmatic-export
```

输出目录必须不存在。train/validation保留与现有SFT接口兼容的公开prompt和findings；test/OOD分为heldout下的cases与gold，不生成训练加载器可误读的test.jsonl。完整逐例程序标签和参考哈希只用于协调人溯源，不进入公开prompt。导出manifest明确标记programmatic、human_reviews_completed=0、human_evaluation_claim=false、protocol_frozen=false。该协调人目录不应整体授予训练角色访问权限。

## 必须继续完成

程序标签通路已接入独立的[schema_version=3协议](programmatic-protocol-v3.md)，旧v1/v2人审路径保留供复现。v3绑定程序标签、任务/参考/视图、独立实现验证、扰动与变异、源输入隔离及其余正式证据，不再要求人工声明；训练验证不打开测试gold。接口工程迁移不等于正式冻结，新数据、完整覆盖和预算仍须实际补齐。

新测试已经覆盖：八个旧开发操作族的静态参考、隐藏历史、写后恢复、缺文件、结果与报告分离、伪造事件和错配规格、程序导出不产生人工字段。它们是旧开发数据的工程检查，不是新的正式测试结果，也不证明所有参考正确。后续应使用新任务族、独立参考构造和更系统的对抗/变异覆盖，报告所有失败和未覆盖情形。

算法生成的合同应明确记录program_generated来源，不宣称human_authored。对公开改编来源继续核验授权和适配范围；不把仓库的许可标签自动解释为全部原始内容可发布。没有人工验证不等于忽略来源、参考和规格之间的风险。

当前已对现有600份单模板训练候选、2400视图生成9600项程序标签并重算通过，与在线规则的状态比较无分歧；这只是实现一致性。分布检查发现R_ORDER只有1800 satisfied/600 unknown，尚无violated，须补充先写后验等轨迹。该批仅train，无新的封存test/OOD，不能直接启动正式训练。公开元数据见[M2h](../examples/results/formal-m2h-programmatic-labels/README.md)。

后续[M2i](contract-fault-coverage.md)保留该批不变，另生成7200个故障视图，扩充候选池中的顺序违规已有1800；六种声明的标签器变异均有反例。新增视图不增加独立源任务，仍需补齐模板/划分/blocked分支和正式协议冻结，最终训练视图选择尚未冻结。
