# 历史公开输入文件快照补查

2026-10-26。原[M2p六模式比较](../formal-m2p-identity-removed-inputs/README.md)识别显式 `inputs` 映射和prompt中的首个JSON对象，但未把运行记录的 `files` 映射视为输入。新增提取器识别其中 `input/` 路径下的**原生对象行数组**，沿用原六种签名比较，不改变当前1050份冻结合同或任何实验参数。

## 实际覆盖与结果

范围仍为冻结提交20214可达历史中 `data`、`examples/results` 的962个JSON/JSONL blob。对全部对象，原提取计数与原清单逐项一致；原辅助源码SHA保持不变。

|项目|对象数|容器出现次数|每种模式的不同历史签名数|
|---|---:|---:|---:|
|原显式inputs提取|23|829|60|
|新增input数组文件快照格式|76|3115|95|
|两类对象并集|81|不将重复计数相加作为任务数|两类签名可能重叠，不相加|

其中58个对象原先未能提取到输入。两类合计仍有879个已解析对象没有支持格式输入；另2个非JSON哨兵已由[M2r](../formal-m2r-sentinel-review/README.md)解释，原解析失败计数保留。3115次快照是多次记录中的出现次数，不是3115个独立源；95个不同签名也不证明统计独立。

当前合同保持train600、validation150、test200、OOD100，原文件SHA为 `3adb95d02a0224b4b4078f237813c5f47d808e5055a637d2b7ce3a706c8c4c24`，规范化列表摘要为 `67892c44b95f398810c0a6e04848e8072c00913faa08be1c2847bf9c6289cc0c`。原三种精确模式及移除声明格式rid后的三种模式，均未检出当前源合同匹配；逐例匹配表为0条。完整计数和范围见[摘要](summary.json)。

## 提取边界

只选 `files` 映射中的 `input/` 文件，且这些输入文件必须全部为原生数组、每行均为对象；不从部分合格文件拼凑匹配，不把JSON字符串或其他结构自动转成数组。输出文件不作为输入；原有answer/gold/response等字段排除策略及prompt首个JSON范围保留。普通id、字段名称、其他值、类型和行顺序均不改写。

历史运行快照可能含模型修改后的输入，因此匹配只能作为公开复用风险线索，不能直接证明原始输入相同或答案泄漏。本次无匹配不等于不存在语义变体、任意标识/字段改名、其他路径格式、外部资产或预训练污染；已记录的跨划分近重复没有删除。**M2整体仍未完成，不能据本补查宣称语义或统计独立性已证明。**

## 复算与验证

保持原辅助脚本的字节SHA `23063e03e879b7cee81671c8793ee4eb9750ed3d8246a79e441bb9df7db28bcd`，使用已有公开[历史对象清单](../formal-m2r-sentinel-review/historical-object-inventory.json)及原冻结Git对象。在持有当前私有合同的仓库中运行：

```powershell
python -X utf8 scripts/audit_prior_public_input_snapshots.py --source-commit 20214fb28ba1c8a4a2be0be075c97e33eedb2ba0 --current-tasks runs/prior-public-input-audit-20261025/private-input/tasks.jsonl --expected-tasks-hash 67892c44b95f398810c0a6e04848e8072c00913faa08be1c2847bf9c6289cc0c --inventory examples/results/formal-m2r-sentinel-review/historical-object-inventory.json --expected-inventory-sha256 7925992307b46f63f87274c49abb4463922a37954466f32b51f395c200251628 --out runs/input-snapshot-replay
python -X utf8 -m unittest discover -s tests -p test_prior_public_input_snapshots.py -v
```

5项针对性检查已通过：过去漏识别的快照被提取；端到端模拟Git字节管道的阳性对照命中六种模式；不完整输入组、答案/输出字段被排除；prompt范围保持首个JSON。夹具不是正式任务或模型运行。实际全量审计与另一个全新目录的summary、逐例匹配表、逐对象清单均逐字节一致，见[验证摘要](validation.json)。

本次只读取当前合同中的可见输入字段和既有公开历史资产，不打开当前的gold、独立参考文件或模型输出；历史含输出的公开JSON会作结构解析，比较仅使用规定输入字段。运行中的M7不受影响。当前合同和私有逐例表仍未公开，正式评估全部完成后按发布范围提供；当前汇总不冒充外部逐例复算或全链条访问隔离证明。校验值见[checksums.json](checksums.json)。
