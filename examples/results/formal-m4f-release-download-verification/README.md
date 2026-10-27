# M4f：模型Release的实际公开下载校验

2026-10-27。六份验证集所选Qwen3.5-9B适配器、一个去重共享分词器及README、清单、SHA256SUMS已作为[GitHub Release附件](https://github.com/Jerry-114514/Jerry-new-project/releases/tag/qwen35-9b-m4-adapters-20261027)发布。共10个附件，969742150字节，未使用Git LFS，也未开启付费额度。

全部10个附件的GitHub服务端大小及SHA256与本机相符；随后实际从公开下载链接读取完整内容、不使用Authorization请求头，逐文件重新计算SHA256，全部匹配。该回执证明模型附件实际可下载及内容一致，不代替模型加载/前向检查、正式质量评估、训练断点恢复或M8整体验收。

主凭据见[receipt.json](receipt.json)，记录每个附件的完整大小、实测下载SHA256、Release身份及观察时间。三个原始下载观察快照保存在`completed-download-source-snapshots/`，原始字节SHA256在主凭据中绑定。

失败和操作记录保留：首次公开下载复核的第二个文件响应截断，未记作通过；重新取得完整内容后验证成功。顺序核验器在完整验证三份余弦包后被主动停止，避免重复下载已经由并行核验器处理的附件，见[停止记录](sequential-download-stop-receipt.json)。前两个快照可能显示failed或停止前的running状态，它们仅贡献其中实际完整验证成功的逐文件条目；其余七个附件由独立并行会话完整验证。主凭据要求十个唯一附件齐全且各自实测大小及SHA256一致，不会把下载中的部分文件计为成功。此前发布工具使用草稿阶段缓存下载URL遇到404的失败也保留在本机发布日志；刷新正式Release URL后完成了本回执中的实际下载。

使用方法见Release附带README：下载所需的一个适配器、共享分词器和校验文件；显式加载固定revision的官方基础模型，再挂载适配器。发布不包含基础模型、优化器、正式测试gold或逐例预测。M7/M8状态仍以[执行记录](../../../docs/formal-experiment-status.md)为准；`m8_complete=false`。
