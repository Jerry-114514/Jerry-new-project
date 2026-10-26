# 历史JSON解析失败的定点复核

2026-10-26。对[M2p历史公开输入审计](../formal-m2p-identity-removed-inputs/README.md)记录的两份解析失败，核对冻结Git对象、完整文件字节、生成代码、清单SHA及历史探针完成/延迟测试记录。两项均为**故意无效的非JSON硬件探针哨兵**，没有真实输入行；原解析失败计数仍保留，没有将它们改写为有效数据或忽略未知坏文件。

|冻结路径|字节数|核对依据|
|---|---:|---|
|`formal-m3a-context-probe/data-1024/test.jsonl`|57|生成器明确写入哨兵；manifest标明故意无效并绑定SHA；已完成探针记录defer_test及test_deferred为true|
|`formal-m3f-supervised-logits/data/test.jsonl`|33|生成器明确写入哨兵；既有checksums绑定SHA；已完成探针记录defer_test及test_deferred为true|

表内路径均位于 `examples/results/`，完整路径、Git blob SHA、SHA256及生成代码行号见[摘要](summary.json)。按唯一历史blob计数，相同字节在多个路径出现不重复计数。

原范围仍为冻结提交 `20214fb28ba1c8a4a2be0be075c97e33eedb2ba0` 可达历史中 `data` 与 `examples/results` 的962个JSON/JSONL对象：960个解析成功，2个解析失败；这两项的性质现已查明。937个解析成功但未提取到支持格式输入的对象、其他文件格式、语义变体、跨划分近邻及更广泛独立性问题，本复核均未解决。**M2整体仍未验收完成。**

## 可复算材料

本目录同时公开[原历史对象清单](historical-object-inventory.json)，内容仅为已有公开Git对象的路径、blob SHA、大小、解析状态和提取计数；不含当前合同、标签、逐例匹配表、模型输出或私有随机种子。清单字节SHA256为 `7925992307b46f63f87274c49abb4463922a37954466f32b51f395c200251628`，与此前M2p记录一致。无需当前私有任务即可复算本项定点复核。

在包含冻结Git提交对象的仓库中，使用保持原UTF8/LF字节的清单和全新输出目录：

```powershell
python -X utf8 scripts/audit_historical_json_sentinels.py --source-commit 20214fb28ba1c8a4a2be0be075c97e33eedb2ba0 --inventory examples/results/formal-m2r-sentinel-review/historical-object-inventory.json --expected-inventory-sha256 7925992307b46f63f87274c49abb4463922a37954466f32b51f395c200251628 --out runs/sentinel-review-replay
```

脚本验证清单SHA及962对象的完整可达集合；只对白名单中的两段**完整精确字节**进行归类，并检查对应冻结生成语句、清单和探针结果。未知无效文本以及追加JSON的扩展哨兵均被拒绝，不按文字前缀笼统放行。两次实际全新目录调用的摘要逐字节一致，原清单未修改。校验值见[checksums.json](checksums.json)。

哨兵中的文字是被审计的夹具数据。此过程没有打开当前合同、gold、参考文件、模型输出或权重，不执行探针或模型，也不修改冻结数据、当前M7配置或统计家族。历史defer记录只支持这两项探针的既有证据，不证明全系统访问隔离、法律授权、语义原创性或无预训练污染。
