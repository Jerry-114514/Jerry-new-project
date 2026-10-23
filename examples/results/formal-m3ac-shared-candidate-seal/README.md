# M3ac 新候选身份与相同材料封存

见[构建范围与未完成门槛](../../../docs/shared-history-freeze-preparation.md)。不是正式冻结或模型效果结果。

- `preparation-status.json`：独立eeca3130构建，活动GPU源bb168cd0未改；新身份与旧seal完整保留，ready=false及source_root/预算/控制器依赖明确记录。
- `parameter-delta-audit.json`：去掉常驻登记及还原证据路径后，整个新旧规格相等；训练、数据、种子、预算和统计计划不改。
- `material-seal.json`：新候选的实际结构化封存，仅含路径、哈希、覆盖计数及策略。10个材料绑定与旧seal完全相同，不含题目/gold。

构建侧读取参考标签只检查覆盖与finding接口，不运行heldout模型、不计算性能或损失。含财务快照的完整私有准备包已归档至用户本地，不上传Git。正式训练0/6。
