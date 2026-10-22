# M2c：固定上游 train 的外部来源导入证据

2026-10-23。来源为 [WikiSQL](https://github.com/salesforce/WikiSQL/tree/cffb423077756d04c1bac5bcd45167c86903fbcb)，固定提交 cffb423。只解析上游 train 两个 JSONL 成员，没有执行 SQL 或解析上游 dev/test JSON。

56,355 条训练记录、18,585 个表格经确定性结构/资源初筛后，得到 600 条来源候选，覆盖 600 个 table_id 与 82 个结构模板。它们仍不是项目任务、人工标注或独立样本证明。

质量核查发现 599 份不同的精确表内容、422 个非空 page_id 值、150 条缺失 page_id，及 20 组重复 page_id。这些分组和模板均须继续核验，不能声称已经达到正式训练数据规模。

## 证据

- `pool/public-index.jsonl`：600 条标识符/记录位置/哈希/尺寸，不含原题、表格值或 SQL。
- `pool/manifest.json`：原始输入身份、两个训练成员校验值、全部筛选计数和未完成标记。
- `quality.json`：精确内容、page_id 与结构模板分组的元数据，只作风险线索。
- `acquisition-local.json`：实际成功下载的三个文件及 Git/SHA256 校验。
- `acquisition-remote-failed.json`：AutoDL 直连超时的原始失败清单，未覆盖或伪装成功。
- `acquire_source.py`：实际本机采集脚本，保留许可和 README；需从仓库根目录在全新输出目录运行，不能覆盖既有源数据。
- `runtime-identity.json`、测试日志和 `source-comparison.json`：AutoDL **188 项全部通过**，本地 178 项通过、10 项缺少 ML 依赖跳过；109 个源码/配置匹配，索引与 manifest 在 Windows/Linux 字节一致。

六项新增测试覆盖只读 train/不提取路径、压缩包篡改和重复/链接成员拒绝、确定性分组不复制凑配额、公开索引不带题目/答案、来源池不能冒充项目案例或 SFT，以及不可覆盖输出。所有小 tar 数据均为明确合成单元夹具，不作实际来源或人工批准证据。

## 复核

```bash
python examples/results/formal-m2c-wikisql-source-intake/audit.py
python examples/results/formal-m2c-wikisql-source-intake/audit.py --archive runs/wikisql-source-20261023/data.tar.bz2
```

第一条只审计元数据；第二条重新校验和读取固定上游 train，重建索引、协调人池摘要及质量报告。后者已实际在本机通过，部署时在 AutoDL 再复核。不会生成标签、执行模型或读取项目测试材料。

原始压缩包、原许可、README 及 600 条原题/表格/SQL 保留在本机 ignored runs 目录及 AutoDL 独立数据目录；本仓库未发布这些内容。上游仓库许可标识及出处见 [NOTICE](NOTICE.md)，不代表衍生材料的发布审核已完成。

**project_cases_created=0，human_verified_sources=0，annotation_ready=false，execution_adapter_ready=false。** 本池不得直接升级为隔离测试，也不能代替真实双标、适配、功效/预算、协议冻结或正式六次训练。完整说明见[来源导入指南](../../../docs/wikisql-source-intake.md)。
