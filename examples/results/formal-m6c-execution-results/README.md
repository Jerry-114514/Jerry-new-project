# M6正式闭环完成与描述性结果

2026-10-26。固定真实执行器和分析器，P1–P4各300份合同，1200条交互及1200条离线评分全部完成。`interact → verify → reveal → verify-reveal` 四阶段均退出0；总监督耗时约11.2023小时。M6原监督进程及全部子进程已退出，未重跑模型或更改冻结配置。

已实际从AutoDL复制完整结果到用户本机，归档24,422,400字节、11成员，SHA256 `0838a33d80bd45f7f6456f954eff4497e79dcf9ec4cdef0fdc5b3cda9636b2dc`。每成员、两份各1200条的记录、交互与评分封存及四阶段收据已重新校验；协调端再次复核与原异机凭据一致。执行评分收据为 `5a3bd558d8e0a28030193dbedefb69b8d45210c9e1ea62212729a34adddd2ea7`。

见[结果报告](REPORT.md)、[完整去敏摘要](summary.json)、[实际完成与备份凭据](receipt.json)及[校验值](checksums.json)。执行源码仍为 `20214fb28ba1c8a4a2be0be075c97e33eedb2ba0`，协议和模型绑定保持原值；M7随后按原冻结六条件[实际启动](../formal-m7b-controls-start/README.md)。

四条件的最终文件/事件状态逐任务完全相同，test均122/200合规成功、OOD均3/100；每条件保留42个错误运行、28次均未接受的修复尝试。独立硬检查实际触发拒绝，但没有观察到新增已提交硬违规或成功率的增量收益；合规修复候选为0，误拦截率为null。全部负结果、失败和条件保留，没有依据结果换模型或删条件。M6推理峰值显存未记录，报告不挪用M4训练峰值。

## 复算

在包含冻结Git提交对象的仓库中，使用实际异机归档和全新输出目录：

```powershell
python -X utf8 scripts/summarize_formal_execution.py --archive runs/formal-m6-backup-20261026/sealed-execution.tar --expected-sha256 0838a33d80bd45f7f6456f954eff4497e79dcf9ec4cdef0fdc5b3cda9636b2dc --out runs/m6-results-replay
```

脚本检查外部归档SHA、四阶段成功、封存成员、相同源任务群及原交互字段未被评分改写，逐项重算冻结summary，并计算已登记的描述性候选机会和共同可行子集。辅助源码与20214文本核对一致，不读取gold/参考文件，不加载模型。两次实际全新目录CLI输出的三个文件逐字节一致；公共summary与REPORT复制自该结果，公共checksums另覆盖本目录新增的验收材料。

这不是重新验证模型/参考真值，也不是M8确认性统计。原始合同、轨迹、模型文本及逐例评分继续私有，待正式测试全部结束后按可公开范围发布；当前仅凭本目录无法独立复算逐例真值。共享生成器、近重复及独立性限制仍由M2记录，M6完成不代表这些前提已证明，也不宣称human evaluation、开放业务安全或M8完成。
