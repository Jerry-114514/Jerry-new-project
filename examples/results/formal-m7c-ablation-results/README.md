# M7六条件完成与干预不足的负结果

原冻结四阶段已完成，1800条交互与1800条评分封存并实际异机备份。描述性汇总使用原封存记录和离线已评分结果，逐项核对原始计数；不读取gold/参考文件、不调用模型、不新增假设检验。[报告](REPORT.md)、[全量聚合与成本](summary.json)、[全新目录复算凭据](replay-verification.json)。正式18项统计见[结果表](../formal-m8a-statistics-comparisons/STATISTICS.md)。

**本轮没有形成不同的实际修复目标。** 六条件每次尝试都只选择一个根要求；fixed-k-1/2/3虽然请求值不同，实际选中根要求和依赖扩展目标的逐任务序列完全相同。移除hard权重改变部分请求值，但实际目标仍相同。六条件最终状态及计费token也相同。因此本轮完成了注册实验，却不能据此检验多根修复场景的动态强度收益，更不能宣称算法一般无效或等效。

每条件28次修复尝试，9个完整候选、19个不完整候选，完整且合规为0，接受为0。test成功122/200、OOD成功3/100，错误22/20全部保留。每条件1915708计费token，六条件共11494248；另保留中断前39次已完成任务的250109 token，总计11744357。900条完整固定条件前缀逐字节不变；中断动态条件整体重跑，39条不计为额外独立样本。

复算命令如下；两个归档的可信校验值必须来自既有实际备份凭据，而非任意输入自算后默认可信。输出目录必须全新。

```text
python scripts/summarize_formal_ablation.py --archive sealed-ablation.tar --expected-sha256 ae6ca2ac220d3172c36c93797a589093493f3f3788cdddc32f1812a45c1efc56 --protocol-hash a1b0440b0f93cfcb76ad9971cbfe73e8f08b30e45a6fef091c7cb74cc31fc027 --binding-hash d27c35ff115f969cbe7a3b45e0b22f1bdb284d925e58f89819be83301523a003 --interrupted-archive original-interrupted-m7.tar.gz --interrupted-sha256 662b4172c505e7df36226244905590b165a0474310d9f237b9c69f559f9aa4c5 --out new-m7-summary
```

后续若研究控制器收益，应在开发集预先检验多根修复机会、有效目标分离及候选合规率，再冻结新的未见测试；本轮不修改测试集、提示、分析器或控制器以挽救正结果。时间、显存缺失及共享生成器限制见报告。本目录不标记M2/M8完成。
