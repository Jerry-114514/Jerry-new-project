# M3ab 可登记的条件常驻与审计

见[运行规则和未完成门槛](../../../docs/registered-model-residency.md)。新选项未写入正式候选，未部署至运行中的GPU源。

- `local-tests.log`：最终286项本地检查，16项可选ML跳过，其余通过。
- `server-status.json` / `server-full-tests.log`：bb168cd0加本轮改动的独立CPU工程快照，286项全部通过、无跳过；实际生产文件与当时测试文件字节SHA已记录。
- `targeted-status.json` / `targeted-tests.log`：仅扩展M7揭晓/评分测试后的4项服务器检查，生产文件未变，最终测试文件SHA单独保存。没有把后续覆盖冒充早先全量运行已包含的断言。

M6/M7条件间冷加载、任务间独立账本及权重驻留、异常释放、重新hash后的装载/计时篡改拒绝均由合成工程夹具验证。真实9B有限等价性证据在M3aa，没有新增正式模型调用或效果结论。活动GPU源保持bb168cd0，正式训练0/6。
