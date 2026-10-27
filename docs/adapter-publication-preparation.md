# 六份正式适配器的发布准备

**2026-10-27更新：用户明确要求不使用LFS，已改为[GitHub Release附件发布](https://github.com/Jerry-114514/Jerry-new-project/releases/tag/qwen35-9b-m4-adapters-20261027)。** 六份适配器、去重共享分词器及校验说明共10个附件已发布，服务端大小与SHA256均匹配；独立匿名完整下载核验仍在进行。见[发布与恢复记录](m7-recovery-and-release-20261027.md)。下述LFS相关描述仅为此前准备方案，未执行LFS上传，后续复现请按Release的README操作。

`scripts/prepare_adapter_release.py`把已有异机备份中的六份验证集所选导出整理成新的本地目录。它不上传文件、不调用模型、不修改GitHub预算或启用付费，也不将准备完成登记为M8完成。

输入是带可信SHA256的传输计划与已发布的M4完成回执。六个job必须齐全，实际权重与回执中的验证选点导出哈希一致；各源文件先验大小与哈希、复制后核验目标，再复查源文件未变。输入回执的SHA以可信原始字节为准；Windows工作区换行改变时，应从对应固定Git提交读取原始字节核验，不能自算一个新哈希绕过检查。

每个job只复制六项：adapter_model.safetensors、adapter_config.json、selection.json、chat_template.jinja、tokenizer.json和tokenizer_config.json。不会复制基础模型、latest.pt、优化器状态、run_config、逐例预测、测试案例或gold。新的manifest保留原导出文件哈希和验证选点；各job适配器配置保持原字节，可能仍包含旧服务器基础路径。加载说明要求显式加载官方基础模型及固定revision，再挂载选定适配器，避免依赖旧路径。

输出包括36项推理文件、清单、加载说明及Git LFS属性。六份实际权重各173181072字节，共1039086432字节，约0.97 GiB；分词器等文件可由Git按内容去重。这里只准备LFS属性，尚未证明对象已上传或可由外部下载。完整模型文件仍应通过恢复推理检查，不能用本脚本的字节核验替代实际加载、质量评估或训练断点恢复。

```powershell
python -X utf8 scripts/prepare_adapter_release.py --plan PRIVATE/plan.json --plan-sha256 TRUSTED_PLAN_SHA256 --training-receipt PRIVATE/published-training-receipt.json --receipt-sha256 TRUSTED_RECEIPT_SHA256 --out NEW_PRIVATE_OUTPUT
```

实际上传前需核实账户现有Git LFS用量和超额控制。可用总额度不等于当前剩余额度，成功取得仓库认证也不证明账单接口权限。准备脚本不提供修改计费设置的功能；额度未确认时保留本地包，不把指针或上传计划当作可下载模型。后续如发布，应记录实际LFS对象上传、远端分支绑定，以及从全新目录下载后逐项哈希一致的证据。普通CI检出应保持默认不下载大权重，复现读者也应只拉取所需job。

三项字节夹具测试覆盖严格文件清单、禁止复制checkpoint、重复/缺失输入、错误可信哈希、源文件变动、与所选模型不一致、拒绝覆盖和全新目录复算一致；夹具不是实际训练权重：

```powershell
python -X utf8 -m unittest discover -s tests -p test_adapter_release_preparation.py -v
```
