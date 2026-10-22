# 分析器误判导致闭环不修复：诊断与修复

日期：2026-10-22。问题来源为用户截图，已用原始轨迹核验。

此前 16 条 9B 开发记录只有 initial 阶段，在线判断累计 satisfied 48 项、unknown 16 项、violated 0 项。runner 仅在存在 violated 时修复，因此输出文件缺失也没有触发 repair。独立硬检查检查候选修复，不能替代初始错误发现，故此前没有执行机会。

开发入口新增显式 `--analyzer-mode model|rule|hybrid`。model 保留完整 Schema 的纯模型对照；rule 使用公开可执行规则，只配置 actor 模型；hybrid 在运行模型诊断的同时，让公开规则负责已编码要求的门控，保存原始模型判断、规则判断、有效判断及覆盖记录。未指定模式时沿用原有路径选择逻辑，不悄悄改写旧条件。

当前四种要求均有公开检查器，所以 hybrid 的有效门控与 rule 相同，额外保留模型侧诊断及成本。这不是模型自身判断能力提升。规则只读公开规格、输入、文件快照及可见事件，不读独立离线参考；历史不可见时不能凭模型自信把历史性质判为已满足，仍保留 unknown。模型格式错误和调用成本不隐去，模型调用异常也不伪装成成功回退。

运行示例（已验证 venv、仓库根目录、新输出目录）：

```bash
python -m intentlab.execution --tasks runs/inputs/tasks.jsonl --references runs/inputs/offline-references.jsonl --out runs/hybrid --actor-model /root/autodl-tmp/models/Qwen3.5-9B --analyzer-model /root/autodl-tmp/models/Qwen3.5-9B --analyzer-mode hybrid --device cuda --policies fixed-full dynamic --max-tool-steps 3 --max-repairs 3 --context-limit 4096 --max-new-tokens 512 --token-budget 16384 --actor-envelope extract
```

纯规则模式删去 `--analyzer-model`，改为 `--analyzer-mode rule`。纯模型对照改为 `--analyzer-mode model`。有无硬检查的比较必须固定相同分析器，不能只给其中一组增加规则，否则无法分离干预效果。开发入口仍拒绝 test/OOD。

新增回归故意使模型把所有要求判为 satisfied：纯模型不修复、任务失败；混合路径识别缺失数据和报告，触发修复并通过独立离线评估。同时核验隐藏历史、私有答案隔离、原始错误保留及不完整判断拒绝。本地 109 项测试中 102 项通过、7 项无 ML 依赖跳过；AutoDL 109 项全部通过。

新模式保证可编码违规不会被模型的 satisfied 覆盖，不保证执行模型一定修好，也不保证独立硬检查必然产生组间差异。重复无效动作、预算耗尽及解析失败仍如实计入。真实 9B 开发验证另附记录，不把受控回归当作真实质量结论或正式实验完成。

## 5090 真实验证结果

实际使用官方原始 Qwen3.5-9B，同时担任 actor 和模型诊断侧角色；hybrid 的有效门控来自公开规则。开发任务选择输入文件顺序的前三项：金额舍入、时区边界、Unicode，未打开正式 test/OOD。对 fixed-full 和原有 dynamic 各运行一次，共六条记录；这不是动态 k 比较。

| 策略 | 合规成功 | 修复提议 | 独立硬检查执行 | 工作流错误 |
| --- | ---: | ---: | ---: | ---: |
| fixed-full | 2/3 | 4 | 4 | 0 |
| dynamic | 2/3 | 4 | 4 | 0 |

金额舍入初始成功；Unicode 经一次修复成功；时区边界虽进入三次修复仍失败。全部八份候选通过独立硬检查，没有发生硬违规拒绝；这证明硬检查现在有执行机会，但不能证明其产生组间安全优势。

旧纯模型记录在相同三项上仅金额舍入成功，未进入修复。前后开发检查经历分析器更换，不是微调提升或预先登记的效应估计；三个重复使用的公开源任务也不足以作统计泛化结论。

六条记录通过工具重放、独立离线指标和预算核验，14 次混合决策从真实工具状态及公开规则重新计算一致。保存原始模型判断及 12 项状态覆盖事件，不把有效判断伪装成模型原始预测。36 个实际交互模块已保存到结果包的 `interaction-source/` 并核对指纹；后续 GPU 独占保护不覆盖此运行源码。官方 13 项权重/tokenizer 资产重新核验通过。

本次上限为每任务 16,384 tokens、单次生成 512、上下文 4096、修复最多三轮、每份提议最多三步工具反馈。运行开始时显卡空闲，但途中另一个实验启动并使用同卡；没有工作流异常，不根据这次耗时作性能结论，也未停止或修改其他实验。

原始记录及核验见 [结果目录](../examples/results/formal-m1f-hybrid/README.md)，复算命令为：

```bash
python scripts/audit_hybrid_development.py --root examples/results/formal-m1f-hybrid
```

代码和结果保存在本地工作区及独立 AutoDL 开发目录 `/root/autodl-tmp/formal-m1f-hybrid`。此前提交请求受自动审批服务额度限制，随后 Git 直连超时；现已通过 GitHub 接口发布为 `7396e01`，远端源码树与本地审查树完全一致。此发布不改变开发结果的解释边界。
