# M8正式复算与发布验收

2026-10-25制定，2026-10-26更新阶段状态。本文是验收步骤，不是M8已完成回执，不修改冻结协议。当前M1/M3/M4/M5/M6已验收，M2保留数据质量限制；M7已在M6完成和异机备份后实际启动，正式统计尚未完成。采用程序标签，无人工标注前置条件，不报告human evaluation。

## 运行身份与前置证据

正式计算固定源码`20214fb28ba1c8a4a2be0be075c97e33eedb2ba0`；后续文档提交不部署到运行目录。协议lock hash为`a1b0440b0f93cfcb76ad9971cbfe73e8f08b30e45a6fef091c7cb74cc31fc027`，模型binding hash为`d27c35ff115f969cbe7a3b45e0b22f1bdb284d925e58f89819be83301523a003`。文件SHA、规范化内容digest和协议内部hash分别核对，不能混用。

| 验收项 | 必须检查的证据 | 当前状态 |
| --- | --- | --- |
| 数据与程序标签 | 冻结数据、独立参考、谱系、划分及近重复清单；与锁内哈希一致 | 工程证据已保存，M2限制见[逐项核对](m1-m2-evidence-review.md) |
| 六次训练 | 配对初始化、固定训练量、验证选点、曲线、失败/恢复边界 | 已有[M4验收](../examples/results/formal-m4e-training-complete/README.md) |
| M5 | 九条件预测封存、封存后跨主机校验、reveal/verify-reveal、六份损失记录 | 已有[完成及独立算术复算](../examples/results/formal-m5d-diagnostic-results/README.md)，预测和评分均已实际异机备份 |
| M6 | P1–P4全部300任务、失败记录、token账本、交互封存与评分验证 | 已有[四阶段与异机备份验收及负结果](../examples/results/formal-m6c-execution-results/README.md)；推理峰值显存未记录，未补造 |
| M7 | 三项fixed-k、dynamic及两项移除权重控制，各300任务，完整绑定及评分 | [已实际启动](../examples/results/formal-m7b-controls-start/README.md)，尚未完成 |
| M8 | 正式统计复算、科学前提说明、资产恢复材料、最终报告与发布提交 | 未完成 |

M5已经完成先封存再揭晓的实际顺序，评分阶段已在claim之后合法读取gold；“未读取gold”只描述此前生成阶段。观察器存活或状态刷新不等于备份成功。M6/M7按冻结入口顺序执行，[衔接等待器](../examples/results/formal-m7a-handoff-preparation/README.md)只在M6验证和异机备份后派发M7；失败保留原目录和凭据，不以新目录规避一次性生成约束。全部正式实验串行使用GPU，遵守原预算守卫；余额不足按实际失败/未完成记录，不删减登记条件或提高预算。

## 正式统计的可复算命令

M5/M6/M7均通过完成验证后，在冻结源码和依赖环境中执行下列命令。所有大写路径均替换为实际已绑定资产；输出使用全新目录。正式协议不加`--engineering`。

```bash
python -m intentlab.frozen_statistics run \
  --protocol LOCK --binding MODEL_BINDING \
  --predictions M5_PREDICTIONS --diagnostic-reveal M5_SCORED \
  --execution-interactions M6_INTERACTIONS --execution-reveal M6_SCORED \
  --ablation-interactions M7_INTERACTIONS --ablation-reveal M7_SCORED \
  --out NEW_STATISTICS_DIRECTORY

python -m intentlab.frozen_statistics verify \
  --protocol LOCK --binding MODEL_BINDING \
  --predictions M5_PREDICTIONS --diagnostic-reveal M5_SCORED \
  --execution-interactions M6_INTERACTIONS --execution-reveal M6_SCORED \
  --ablation-interactions M7_INTERACTIONS --ablation-reveal M7_SCORED \
  --statistics NEW_STATISTICS_DIRECTORY
```

`run`与`verify`递归检查上游绑定；不是只对report做哈希检查。将同一组已封存输入交给另一个全新统计目录，重算后比较规范化`report.json`全部内容；manifest的创建时间和receipt hash可能不同，不要求两个manifest字节相同。保存命令、退出码、源码、环境、输入清单及SHA和比较结果。复算不重新生成预测或重新选择模型。

`scripts/audit_statistics_stage_evidence.py`只复算公开engineering夹具，不能用于给正式结果签发完成结论。正式入口的`m8_complete=false`是有意保留的边界；不得改写该字段以代替完整验收。

2026-10-26已补充[统计与独立目录复算监督代码](../examples/results/formal-m8b-statistics-preparation/README.md)，6项工程门槛/命令检查通过；后续已实际部署并核对源文件SHA，正式统计尚未运行。该代码要求M7验收及实际异机备份，串行执行两份同输入统计和验证，比较完整规范化报告；不会修改冻结统计参数，成功后仍保留M8最终验收边界。

对应的[M7异机备份和统计派发工具](../examples/results/formal-m8c-m7-backup-preparation/README.md)另有10项工程检查；远程探针已部署并完成实际SHA与运行身份核验，M7等待器未启动，尚未进行实际归档或复制。工具要求真实M7完成与进程退出，封存1800条交互及评分，实际跨主机复制和逐成员校验后才允许派发；源码和夹具不能代替实际完成凭据。

## 报告与科学前提

使用冻结v2分析方案：操作族内源任务重采样、固定三种子向量、任务配对、目标token加权损失；唯一主比较RQ1/test，17项次要比较保留完整Holm家族。不以视图或种子重复扩大独立样本量，不挑选有利的种子、分母、区间或失败组。

最终报告须逐项列出RQ1–RQ4和六项控制的效应、区间、分母、原始/校正p值及null原因。另列格式/状态/证据错误、unknown及violated召回、不安全satisfied、候选误拦截、共同可行子集、失败、调用/token、时间和显存。先区分任务是否初始不可逆违规，再解释安全收益；零观察违规不代表风险为零。全部保留负结果。

解释统计前提是否可信：同一生成器、固定族配额、保留的跨划分近邻、源任务依赖、符号翻转对称性和仅三个训练种子均须明确。限制不靠校正p值消除，显著性不等于开放业务泛化或算法创新。当前条件性输入匹配测试不描述为严格IID；功效不足如实报告。新增损失加风险学习率控制属于后续探索，不能列为本轮已完成的确认性比较。

## 资产恢复与发布

保存冻结源码及环境版本、完整协议和绑定、数据/参考/标签与谱系、六个模型端点、官方基座索引、M5–M7原始和评分记录、训练曲线、预算及失败日志、统计输入输出。每类资产有文件清单、字节数、可信源SHA和实际存储位置。端点tar不能替代其引用的官方基座；只留GitHub哈希索引也不能恢复模型。

六个端点和官方基座已有实际异机复制校验；六个端点另完成[全新本机目录文件恢复及JSON解析](../examples/results/formal-m8a-filesystem-restore/README.md)。后续阶段资产仍需复制并核对整包及每成员SHA。恢复证据区分“不解压字节校验”“全新目录文件恢复”“模型加载/推理”和“训练恢复/重新生成”，当前文件恢复不证明后两项。检查点含训练状态，恢复加载仅使用本项目可信来源和已核验字节。已公开的开发恢复证据不替代正式全流水线恢复实测。

确认性实验完成后再发布相应测试题目、程序标签、可重算记录及分析代码。逐项检查源声明和可发布范围；仓库无根许可的现状不能解释为已经授予数据、代码或模型许可。模型二进制保留持久存储并发布索引，来源与访问限制如实记载。私有研究种子和SSH认证材料不随结果发布。

发布前扫描实际提交内容与路径，检查已知私有标识、认证文件、私有目录和权重资产；已知字面标识零命中只证明有限范围的检查。测试材料正式开放时，分别登记允许公开的测试内容和仍私有的种子/认证内容，不能关闭全部检查来绕过预期命中。

最后以`idea.md`逐项填写“完成/失败/未能证明/未执行”、对应证据路径与hash、残余限制及GitHub实际提交。M2未解决项单独保留，不能用一段限制说明直接勾选完成。最终报告、可复算资产和发布引用均实际核验后，才能判断整体目标是否达到；本指南、统计凭据或绿色CI均不能单独证明M1–M8全部完成。
