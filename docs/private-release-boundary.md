# 来源声明与当前发布边界的可复算检查

2026-10-25状态说明：下面检查仅绑定2026-10-23指定快照；六次正式训练和端点备份现已完成，见[验收回执](../examples/results/formal-m4e-training-complete/README.md)。后续提交另有逐包发布检查，但不能将本页旧快照的零命中外推到未来。正式发布还需按[M8验收步骤](formal-reproduction-acceptance.md)对实际发布提交和资产逐项复核。

2026-10-23。本轮检查Git快照c7910e2的1723个已跟踪文件，共16,792,331 bytes。读取五个实际私有研究split seed及两份公开合同文件，在内存中检查已提交内容和路径，不打印匹配原文；不直接打开SSH私钥、私有gold或当前模型预测。既有Git公开归档（包括历史结果文件）只作字节扫描，不进行评分。私有seed与合同先对照该Git快照中已发布的种子承诺及文件SHA256，避免错用无关样本产生“未泄露”假象。

旧结构测试200源、新输入匹配候选200源和共享OOD100源，共500个私有heldout源，3980个原输入身份值。相同OOD身份必须对应相同合同。检查实际seed字面值、heldout源ID和输入身份字符串；本轮三类命中均为0，runs/tmp/checkpoints目录也没有被跟踪。这是已知字面标识的有限检查，不证明没有编码、拆分、去标识后的内容暴露。

两份候选各1050合同的source声明均为program_generated、私有研究数据且未分配公开数据许可；它们共享训练/验证和OOD，不能相加成2100独立来源。原构建和独立参考/故障复算证据分别见M2j/M2m。本轮只确认声明、版本绑定与发布边界，不以元数据自述证明法律许可、语义独立或参考普遍正确。仓库根未发现LICENSE/LICENSE.md/LICENSE.txt/COPYING；本轮未新增或替用户选择任何许可文件，也不作许可结论。

Git快照中有三个早期smoke权重资产，均核对其固定配置为随机微型GPT-2结构（2层、48维、vocab768），包括微型LoRA基座配方；不是9B基座或本轮正式适配器。报告保留这些文件路径，没有误称“仓库完全没有权重”。未发现未检查的权重后缀路径。正式六组模型权重尚未产生，长期备份未完成。

AutoDL当次观察中，v3与匹配候选目录、顺序任务及资源测量根目录为700，两个实际私有seed文件为600。它们限制其他普通用户的文件访问，但相同root运行角色仍能访问；不能把目录分离或权限数字宣称为已完成进程角色隔离。当前应用层输入分离和defer-test测试，与最终正式封存需分别验证。

可公开的本轮材料是代码、计划、聚合统计、审计结果及哈希。原题、私有随机流、原始参考/标签、未揭晓测试预测及正式权重继续私有；未来发布范围、模型备份和测试揭晓仍按最终协议办理。此检查**不完成正式test_sealing或整体provenance验收**，也不把旧快照检查说成未来提交永远安全。

复算命令（输出必须新目录）：

```bash
python scripts/audit_private_release.py --commit c7910e25565b3c2cb9bd467186f45af2543d122e --base PRIVATE/v3 --matched PRIVATE/matched --base-seeds PRIVATE/base-split-seeds.json --matched-seed PRIVATE/matched-seed.json --out PRIVATE/new-release-audit
```

三项针对性测试检查实际标识命中、文件名脱敏/私有路径发现、公开承诺及无关夹具不误报。本地250项测试含14项ML跳过，其余通过。公开[快照结果和日志](../examples/results/formal-m3l-release-boundary/README.md)；原marker集合和私有数据不随报告发布。
