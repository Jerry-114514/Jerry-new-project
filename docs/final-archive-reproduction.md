# 最终归档的离线统计复算

`scripts/replay_formal_archive_statistics.py`从本地最终数据发布包直接读取归档，无需AutoDL路径、GPU、基础权重或模型服务。它核对外部给定的发布清单SHA256、六个相关归档及每个成员、封存收据、冻结协议和完整`intentlab/`科学源码，再调用原注册统计函数，逐字段比较原报告及原复算报告的canonical JSON。它不修改协议内的绝对路径，不提取到原服务器目录。

本轮实际已在Windows协调机的Python 3.14上完成：64个冻结科学源码文件一致，18项比较及完整报告所有字段与服务器Python 3.12保存的结果一致。无需重新训练。它验证的是原记录的注册统计算术，不重新运行模型、oracle、标签核验或上游完整冻结入口，不证明源任务独立性或区间覆盖率。完整数据包目前仍在本地，公开发布等待对测试题、程序gold、参考答案及生成种子的明确确认；当前不能称外部已可独立下载复算。

## 准备

保留仓库历史以访问冻结提交`20214fb28ba1c8a4a2be0be075c97e33eedb2ba0`。使用含复算脚本的当前分支，科学源码不能与冻结提交不同。本入口只需标准库，原统计环境为Python 3.12，本次本地实测为Python 3.14；其他版本未作全量一致性承诺。

将最终Release的全部附件下载到同一目录。用可信仓库索引中的清单SHA256及SHA256SUMS核对附件；不能把未知清单自算出的哈希当作独立可信值。文件名与发布清单保持一致。收到明确公开确认并实际上传、下载校验之后，再补充实际Release链接和可信清单索引。

```text
python scripts/replay_formal_archive_statistics.py --package /path/to/downloaded-assets --expected-manifest-sha256 TRUSTED_MANIFEST_SHA256 --source-commit 20214fb28ba1c8a4a2be0be075c97e33eedb2ba0 --out /path/to/new-replay-output
```

输出必须是新目录。成功时保存`report.json`和`replay-verification.json`；异常停止，不自动缩小比较范围、改置信区间或替换失败记录。canonical一致性与文件字节一致性不同：本入口重新排版JSON，不把其文件SHA说成原服务器原始字节SHA。

## 其他复算入口

M7候选、成本、实际目标和中断额外计费见[命令与说明](../examples/results/formal-m7c-ablation-results/README.md)。九条件证据支持补充评分使用`scripts/postformal_evidence_support.py`，输入为同一发布包内M7、scientific、predictions和scoring归档，指定已信任的四个SHA256和协议/绑定哈希；必须使用新输出目录，该指标仍标为探索性。

合同构造可使用`scripts/audit_frozen_contract_regeneration.py`，将科学归档内`dataset/tasks.jsonl`与`contract-regeneration-inputs.tar`内原始随机流提供给公开命令，核对五个种子承诺并重建1050份合同。此方法不证明普遍原创性、语义独立或法律授权。程序标签与参考的独立核验另由`intentlab.programmatic_protocol.validation_record`完成，不通过统计复算暗中宣称已重新验证。

适配器位于已有模型Release。真实模型加载和有限前向检查另有[实际完成凭据](../examples/results/formal-m8b-restored-inference-check/README.md)。本入口不执行训练恢复、全量模型输出重放或新环境安装验证；公共复现还依赖最终数据实际发布、下载校验、来源质量记录和完整报告验收。
