# M2d：私有显式合同适配与两题真实执行检查

600 条 WikiSQL train 来源候选中的 12 条被改编为新的公开文件合同，共 48 个注入视图、一个共享模板。人工审核和正式训练均为 0；不是原 WikiSQL NL→SQL 评测。

`adapter-manifest.json` 记录构建及范围；`lineage-public.jsonl` 只含来源指纹和未审核声明，不含私有视图故障映射。`private-file-sha256.json` 绑定私有构建，`runtime-identity.json` 记录 111 份源码、环境与官方资产核验。`program-reference-consistency.json` 是 12 题两种程序实现的一致性检查。

`smoke-summary.json` 对应官方原始 9B 的两次初始执行：4 次模型调用、程序异常 0，未审核候选参考下 1/2 合规，另一题未完成。没有修复、微调或正式条件比较。原始响应与表格仅私有保存，汇总不能当作人工准确率。首次 GPU 占用拦截和观察占用消失后的重试分别保存在两个日志中。

`tests-autodl.log` 为 195 项全通过；`tests-local.log` 为 185 项通过、10 项 ML 跳过。默认 `audit.py` 仅核验元数据；提供固定上游原始归档时重新构建来源与适配，另提供私有模型记录目录时逐次回放原始提示、输出和工具，无新推理。详见[适配说明](../../../docs/wikisql-equality-adaptation.md)。

空白盲包仅在私有目录准备；分发、来源保真及授权审核、两位真实审核者和必要仲裁均未完成。包的哈希与工作量见 `reviewer-package.json`。`checksums.json` 是本目录发布文件的字节校验表，不证明科学结论。
