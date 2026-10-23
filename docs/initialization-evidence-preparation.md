# 配对初始化实际验证与冻结前材料

2026-10-23。独立AutoDL CPU检出更新至c8eb676，运行三个套件共19项：初始化结果校验2项、真实tiny Transformer/LoRA集成7项、训练端点协议10项，全部通过、无跳过。GPU规范检出仍为d80be96，固定k开发进程173896/173913继续运行，未启动正式训练。

真实LoRA检查核对：同seed的cosine/plateau初始可训练张量SHA相同，换seed时不同；checkpoint记录与result一致，错误初始化指纹恢复被拒绝；历史checkpoint移除该字段后恢复仍标null。既有连续/恢复检查同时核对初始化SHA、曲线、暴露次数、监督量及最终张量相等。证据限于这些CPU模型与配置，不证明任意CUDA训练逐位可复现。正式六次训练仍需逐模型保存实际初始化、配对及导出证明，旧开发适配器不能代替。

同一时间对已发布c8eb676的1799个Git文件、16980019 bytes复算私有发布边界。五个实际私有种子、500个heldout源标识和3980个输入身份值均未发现已知字面命中，未跟踪runs/tmp/checkpoints目录。三个历史微型GPT-2 smoke权重按旧审查保留。根LICENSE仍缺，不新增许可、不宣称法律认证。此检查不证明不存在编码泄露或OS访问隔离。

服务器新增独立私有冻结前目录history-freeze-preparation-20261023：

- 逐文件复核4368视图候选与已发布19项SHA一致；沿用原source-isolation和programmatic-validation实际记录。
- 对300个heldout执行合同独立重算静态参考核验，生成execution-reference-check。
- 将实际16场景主检验敏感性、完整2464/664长度和预算草案绑定到材料；来源声明与发布范围保留程序生成、近邻风险、无人工验证及无新许可的限制。
- 生成heldout及执行材料的完整性清单；它只是preseal inventory，尚无最终协议、正式seal或reveal receipt。

候选协议的source_root指向干净的独立CPU检出c8eb676，数据指向已重建私有候选。未写入占位“完成”证据：length_and_compute_budget正式文件、test_sealing及controller_ablation_audit仍缺，入口返回ready=false。该入口在缺文件时提前返回，所以不能据此断言只有这三项剩余工作，补齐后仍要执行完整标签、引用、控制器、模型、代码及数据核验。

当前每小时租价及总预算上限等待用户信息，未伪造批准。已运行的固定k选择继续按已发布预算，失败保留；其450次未完成，不提前挑k。正式0/6。公开[三个真实CPU测试日志、发布边界结果及准备状态](../examples/results/formal-m3v-initialization-preparation/README.md)。
