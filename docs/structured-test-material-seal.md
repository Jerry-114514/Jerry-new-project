# 程序测试材料的结构化封存

2026-10-23。原schema-v3入口只要求test_sealing证据文件存在，内容缺少结构化校验。新增独占创建的programmatic_test_material_seal，正式v3必须通过；旧工程夹具和旧v1/v2路径不升级为真实正式证据。

清单绑定候选协议的规范化身份（包含预算、少样本示例、训练和执行设置、路径）、四份注释/参考输入、test/OOD公开案例与gold、执行合同与参考共10个文件的绝对路径和SHA256，并记录test/OOD案例数。创建时核对完整有序案例覆盖和gold接口；程序标签正确性仍由原独立参考/故障/变异核验承担，封存本身不证明答案正确。

创建前若相同数据目录已有诊断/揭晓claim则拒绝，不允许覆盖原seal。固定规则仍为每协议一次生成声明、全部预测封存后独立揭晓、训练只读train/validation。已有claim被删除或另建恶意流程不在此操作防护的证明范围；同root角色仍有访问权限，不宣称OS隔离、可信外部时间戳或无人曾检查材料。

正式冻结把已验证的清单摘要写入test_seal_binding，与原协议的annotation、dataset及execution哈希交叉核对。训练阶段只检查锁内元数据，不打开seal、gold、注释库或执行参考；all阶段重新核对实际材料。改变预算、seal内容、gold字节、文件路径或绑定会被拒绝。训练时不读测试答案的约束不因新增封存而放松。

五项针对性检查已通过：完整材料独占创建/候选改变拒绝；修改gold或用纯文字证书拒绝；覆盖缺失或已存在claim拒绝；删除全部封存输入后元数据校验仍可执行且篡改绑定失败；改变候选训练配置不能沿用原seal。本地全272项测试含15项可选ML依赖跳过，其余通过。正式运行检出还需部署复核及实际材料创建，本轮此时不声称已封存或已冻结。

构建命令（候选中的evidence.test_sealing必须与out相同；目录和文件必须是新的）：

```bash
python -m intentlab.test_material_seal --spec PRIVATE/candidate-protocol.json --out PRIVATE/evidence/test-sealing.md
```

文件扩展名沿用既有证据路径，内容为严格JSON。不要用文字占位证书绕过接口。正式check/freeze会重复核验，控制器、计算预算及其他门槛仍独立成立。公开[针对性及完整本地检查](../examples/results/formal-m3w-structured-seal/README.md)。
