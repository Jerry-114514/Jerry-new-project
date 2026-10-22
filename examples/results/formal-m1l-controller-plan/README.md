# M1l：强固定 k 开发选择与结构化控制计划

2026-10-22，engineering 范围。AutoDL 最终全部 **144 项测试通过**；本地 134 项通过、10 项无 ML 依赖跳过。全部数据和审核声明均为明确的合成单元资产，真实人工审核 0，正式协议及正式 9B 训练未启动。

本次先用真实微型 CPU 角色模型，在一项 validation 单元任务上运行 fixed-k=1/2/3，全部独立硬检查开启，模型/预算及其他设置一致。三次均因两 token 生成不足以形成动作 JSON 而失败，合规成功均为 0，计费 token 相同；按预先实现的并列规则选择较小 k=1。它不是实际正式强基线或 k=1 有效性的证据。

选择按源任务等权，先合规成功率，再计费 token，最后较小 k；变体数不提高源任务权重。冻结器重放开发原始记录与参考评分后，绑定选择报告、审核计划及哈希。绑定后删除开发报告和计划，六组真实微型训练、M5 九条件诊断和 M6 八次闭环仍完成。训练阶段没有重新读取这些私有选择材料。

## 文件

- `matrix/controller-development/`：三个 k 的实际开发运行、原始错误、成本、报告和选择结果；`selection.json` 保存前后资产身份及全部原始记录。
- `matrix/controller-plan.json`：本次合成单元计划，含明确标注的合成审核声明，不是真实人工。
- `matrix/controller-cases.jsonl`：原始工程公开案例，用于核对 validation 合同；不是正式隔离测试集。
- `matrix/protocol.engineering.lock.json`：包含 `controller_binding`，绑定完整计划、选 k 汇总和文件身份。
- 其余 `matrix/`：六个 worker、一次恢复、M5 和 M6 的实际原始记录，原有失败全部保留。
- `tests-autodl.log`：最终 144 项；`tests-local.log`：本地结果。`history/tests-autodl-initial.log` 和 `history/tests-autodl-strict.log` 为此前完整通过日志，不将重复测试次数相加。
- `history/controller-replay-path-failure.log`：在修复前复现的 Windows 读取 Linux 归档路径校验失败。只改了归档路径的跨平台识别，没有改写原始模型结果；修复后重放通过。
- `source-comparison.json`：远程测试时与本地归档源码/配置指纹一致；这不是逐行覆盖率或正式模型效果证明。
- `audit-tamper-checks.json`：改动报告/计划被拒；空白审核计划、engineering 报告被当作正式证据时也被拒绝。

离线复核不需要 ML 依赖：

```bash
python scripts/audit_controller_plan_evidence.py
```

重算开发选择、工具与指标、M5/M6 评分及预算。临时模型二进制没有归档；前向损失是现场记录，不在离线复核时重跑，不等于持久模型备份。

## 范围与未完成

已登记六种后续执行控制：fixed-k=1/2/3、dynamic-k、移除 hard 严重度权重、移除 unknown 严重度权重。这些 **M7 控制尚未执行**；两种权重控制不是“学习率损失加风险反馈”控制器，后者仍留待第一阶段完整后的探索及新未见测试确认。

M7 冻结运行入口、实际新数据和人工审核、开发功效与正式计算预算、协议封存、六次正式 9B 训练、正式 M5/M6/M7、M8 聚类/种子统计及持久模型存储仍待完成。原 M1–M8 目标不变，不把开发选择报告当作消融完成。
