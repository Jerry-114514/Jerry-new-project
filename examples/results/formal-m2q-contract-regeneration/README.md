# 冻结任务合同的来源重建核验

2026-10-26。使用冻结源码 `20214fb28ba1c8a4a2be0be075c97e33eedb2ba0` 的任务构造函数、原始生成计划和预先承诺的私有随机流，重新计算1050份公开任务合同。重建结果与冻结任务文件**逐字节一致**：train 600、validation 150、test 200、OOD 100。源身份、输入、规格、要求、模板与来源字段全部参与比较，不只比较随机ID。

任务文件 SHA256 为 `3adb95d02a0224b4b4078f237813c5f47d808e5055a637d2b7ce3a706c8c4c24`，合同列表的规范化摘要为 `67892c44b95f398810c0a6e04848e8072c00913faa08be1c2847bf9c6289cc0c`；文件哈希与列表摘要是两种不同计算。核验先检查生成源码与冻结Git文本一致、计划摘要一致、五条私有流对应已有种子承诺，再重建并比较；不生成新随机流，不挑选候选。

此过程只调用 `make_task` 和匹配测试的 `reword`，没有调用同时生成参考答案和标签的批次构建入口，没有打开gold、参考文件或模型预测，也不调用模型。原冻结数据及正在运行的M6没有修改。

本核验支持“这批合同可由所记录程序和私有流确定性生成”的来源结论。它不证明程序从未受其他资产启发、不构成法律授权认证，也不证明语义独立、严格IID或不存在预训练污染。既有跨划分规范化重复与近邻全部保留，见[相似度风险记录](../../../docs/matched-test-similarity.md)。**M2整体仍未验收完成**。

## 复算

在具备原冻结Git对象及原私有材料的仓库中执行；下列路径是本轮实际路径，私有种子和逐例任务当前不上传GitHub：

```powershell
python -X utf8 scripts/audit_frozen_contract_regeneration.py --source-commit 20214fb28ba1c8a4a2be0be075c97e33eedb2ba0 --tasks runs/prior-public-input-audit-20261025/private-input/tasks.jsonl --base-seeds runs/procedural-private-seeds-20261023.json --matched-seed runs/matched-test-private-seed-20261023.json --out runs/frozen-contract-regeneration-replay
```

已有输出目录会被拒绝。输出只包含汇总，不保存重建合同、种子或逐例ID。原始生成代码和检查逻辑可公开审查；在私有材料按最终发布范围提供前，外部读者无法仅凭本目录完成独立逐例复算。

实际负向检查：错误的私有流被种子承诺检查拒绝；在任务文件末尾增加空行被文件SHA检查拒绝；两次拒绝均未生成成功结果目录。原冻结文件仍保持相同SHA。见[检查结果](checks.json)、[完整摘要](summary.json)和[校验清单](checksums.json)。这些检查证明对应拒绝路径，不代表所有可能篡改场景均已测试。
