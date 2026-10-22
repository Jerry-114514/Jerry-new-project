# WikiSQL 外部来源候选池

2026-10-23。本轮补充可追溯的外部训练/开发来源，不创建正式项目案例或测试集。

## 来源及使用边界

采用 [WikiSQL 官方仓库](https://github.com/salesforce/WikiSQL/tree/cffb423077756d04c1bac5bcd45167c86903fbcb)，固定提交 `cffb423077756d04c1bac5bcd45167c86903fbcb`。[官方说明](https://github.com/salesforce/WikiSQL/blob/cffb423077756d04c1bac5bcd45167c86903fbcb/README.md)将其描述为众包表格查询语料；这不等于真实业务工单或已证明独立的任务。

上游 [LICENSE](https://github.com/salesforce/WikiSQL/blob/cffb423077756d04c1bac5bcd45167c86903fbcb/LICENSE)标注 BSD-3-Clause。本地保留原始许可和 README，配置记录其校验值；衍生数据的来源、表格内容及发布审核仍未完成。本仓库仅发布标识符、校验值和筛选元数据，不上传原题、表格或 SQL。

仅读取压缩包中的 `data/train.jsonl` 和 `data/train.tables.jsonl`。上游 dev/test JSON 未解析，SQLite 数据库与上游代码未执行。公开上游语料可能已在模型预训练中出现，不能直接作为本项目新隔离 test/OOD；允许用途仅为后续 train/validation 来源。

## 实际采集与初筛

AutoDL 直连原站超时，保留失败 acquisition 记录；本机成功下载后核对固定 Git blob、字节大小和 SHA256，再传到 AutoDL 独立复核。压缩包为 26,164,664 bytes，SHA256 为 `755c728ab188e364575705c8641f3fafd86fb089cb8b08e8c03f01832aae0881`。

实际解析 56,355 条上游训练记录、18,585 个表格。确定性的资源筛选限制为：表格最多 8 行、6 列，表头与行序列化不超过 1,800 字符，问句不超过 300 字符，条件不超过 3 项；这些只是开发资源代理，不证明后续提示能放入 2048 tokens。结构不符排除 43,660 条，查询结构/算子不符排除 37 条，保留 12,658 条结构候选。

按种子 20261023 的哈希顺序取样，限制每个 table_id 只取一条，并去掉规范化问句重复，最终选出 **600 条来源候选、600 个表格 ID、82 种结构查询模板**。没有按任何模型成绩筛选，也不声称该样本代表整个语料或真实用户任务分布。方法是开发方案，不是外部预注册。

## 质量检查揭示的剩余问题

600 个 table_id 只对应 **599 份不同的精确表内容**。上游提供的 page_id 有 **422 个不同值，150 条候选缺失，20 组 page_id 重复**。这些计数说明 table_id 不足以证明来源独立，不能将候选数量当作独立任务数，也不能把缺失 page_id 当成新页面。

下一步须核查重复内容、页面谱系、模板关系、上下文完整性及原问句与 SQL 的一致性。合组、排除或补来源后，要生成新版本及映射，保留本次原始候选。现有操作执行器不能直接处理这些查询，尚需设计受控适配器、项目要求、公开规则和独立离线参考。

上游 SQL 仅保存在协调人材料中，不是本项目的状态标注，更不能不经审查就附给模型当作公开要求或标准答案。所有项目双人标注与仲裁仍须实际完成。

## 复现与文件

固定来源参数在 `configs/wikisql-source.json`。已有经过校验的压缩包时运行：

```bash
python scripts/intake_wikisql.py --archive runs/wikisql-source-20261023/data.tar.bz2 \
  --source-spec configs/wikisql-source.json --out runs/wikisql-pool-v2
```

输出目录必须全新。`public-index.jsonl` 只有记录位置、表格 ID、哈希和尺寸；`coordinator-pool.jsonl` 包含原始问句/表格/上游 SQL，保留在本机及 AutoDL 数据目录，不作为盲包或直接训练数据。`project_split=null`，`human_reviewed=false`，适配和标注准备均为 false。

索引 manifest 中 `public_index_sha256` 是规范化记录数组的 SHA256；证据目录 `checksums.json` 另存实际文件字节校验值。默认复核只检查已发布元数据；提供原始压缩包时，可重放源数据筛选和内容/page_id 质量检查：

```bash
python examples/results/formal-m2c-wikisql-source-intake/audit.py
python examples/results/formal-m2c-wikisql-source-intake/audit.py --archive runs/wikisql-source-20261023/data.tar.bz2
```

Windows/Linux 重建的索引与 manifest 字节一致，AutoDL 188 项测试通过。导入器拒绝修改过的压缩包、重复/链接型训练成员；不提取压缩包路径、不执行 SQL，公开索引不含原始问题或上游答案。来源池也不能直接通过项目案例、执行任务或 SFT 格式验证。

**本轮新增可执行项目任务 0，人工核验来源 0，正式标注 0。** 未满足 idea.md 的 600–1,000 个独立训练任务目标，未运行本池模型实验，正式协议与六次训练仍未启动。
