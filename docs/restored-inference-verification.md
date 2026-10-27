# 模型恢复后的加载与推理验收

文件哈希一致只证明字节恢复，不证明依赖可用、权重能加载或推理能运行。`scripts/verify_restored_inference.py`用于在原消融和正式统计监督流程结束、相关进程退出后，在原RTX 5090上验收恢复的官方基础权重和六份验证集所选LoRA导出。脚本准备和字节夹具检查不算实际模型验收；当前仍待真实执行。

## 使用实际推理配置

冻结源码的`intentlab/neural.py`在正式训练中使用NF4 QLoRA；`intentlab/model_backend.py`和`intentlab/shared_role_backend.py`在诊断/闭环推理中以BF16加载基础模型并挂载LoRA，不使用4bit推理。恢复探针沿用后者的模型精度、冻结包版本、非思考chat前缀和贪心生成方式，使用各导出自身的tokenizer。仅生成最多8个新token，不声称覆盖正式长上下文或全部生成预算。

必须显式从恢复目录的`base`加载基础模型，再把恢复目录的六个适配器逐一挂载；不能直接让适配器的`base_model_name_or_path`自动解析，否则可能误用旧服务器文件。适配器张量与对应已恢复safetensors逐项比较。取LoRA状态时关闭自动保存embedding检测，避免为比较词表而访问配置中的旧基础路径。未恢复的优化器状态或`latest.pt`不参与此检查，不加载pickle。

## 执行门禁与结果

脚本要求全新的外部输出目录、冻结源码commit且工作区干净、冻结协议和Python/包版本一致。原统计监督状态须与此前观察记录的SHA256相同，四阶段均成功、原报告和复算一致，监督器及子进程已退出。原预算守护配置必须保持不变，进程真实存活、记录新鲜且至少保留一小时运行时间；不调整预算上限。

恢复计划须与预先绑定的canonical JSON摘要一致，并检查每个实际文件的大小、SHA256、路径安全、完整清单以及六份非基础权重变更型LoRA导出。全部通过后才申请原独占GPU租约和导入ML库。任一门禁或实际推理失败均停止并保留记录，不自动重试模型。

对基础模型和六个适配器分别使用固定公开提示：`Return exactly one JSON object with a single key count and integer value 2. No other text.`。检查前向logits有限、实际生成1–8个新token，并保存真实token、文本和独立探针峰值显存。输出可能不符合提示格式；这项检查仅证明有限前向和有界生成，不作为任务正确率，也不据此调参。探针显存不能回填正式推理阶段缺失的资源指标。

参数包含`--root`、`--source`、`--source-commit`、`--protocol`、`--protocol-hash`、`--expected-plan-digest`、`--statistics-status`、`--statistics-status-sha256`、`--budget-config`、`--budget-config-sha256`、`--budget-status`及`--out`。完成后仍需把真实状态与输出异机备份、核验，结合原模型备份和统计结果评估M8。脚本成功本身不等于训练断点恢复、旧模型输出逐位复现、新环境重建或M8整体完成。

首次实际探针已执行，但未完成全部六个适配器：删除第一个活动适配器后，PEFT 在加载下一个适配器时仍查询旧的 `active_peft_config`，触发 `KeyError: 'cosine-seed-0'`。原失败日志保留，不把它计作完整恢复验收成功。修复为先加载新适配器、激活新适配器，再删除旧适配器；末尾活动适配器随整个模型释放。再次实际验收必须使用新输出目录，保留首次失败记录。

五项测试覆盖统计结束及进程退出门禁、六导出完整性、文件/计划改动、额外文件、缺导出、路径穿越及连续六适配器切换中的有效活动配置；不使用真实权重，不模拟为模型运行成功：

```powershell
python -X utf8 -m unittest discover -s tests -p test_restored_inference_admission.py -v
```
