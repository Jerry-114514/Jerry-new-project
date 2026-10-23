# M3ad 模型与恢复状态的实际跨主机备份

流程及边界见[备份指南](../../../docs/model-checkpoint-backup.md)。正式训练0/6、正式端点备份0，M8未完成。

- `engineering-backup-receipt.json`：先前两步压力实验的真实适配器、tokenizer及latest.pt，共10文件约886MB；源整包与用户本地逐成员SHA核验通过。保存初次生成包的源码SHA及最终本地校验源码SHA，不把后续小幅成员名检查扩展冒充最初生成版本。
- `server-source-status.json`：实际工程包的源端完成记录和代码哈希。
- `server-tests.log` / `server-final-tests.log`：4项服务器字节检查及最终成员名检查版本的重复核验。
- `local-tests.log`：290项本地检查，16可选ML跳过，其余通过。

模型包只留在用户本地持久工作区和私有AutoDL存储，不入Git。官方底座的逐项复制尚在执行，完成并校验后才发布独立索引，不由工程适配器的receipt推断底座已备份。
