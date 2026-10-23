# 程序标签协议v3：冻结与隔离验证

2026-10-23。落实用户选择的完全程序标签路线。v1/v2人审路径保留，新v3不接受reviews/adjudications字段，也不生成或要求人工身份声明。研究范围固定为`encoded_specifications_only_no_human_evaluation`。

## 变更内容

使用[程序标签正式草案](../configs/formal-protocol.programmatic.draft.json)，dataset明确绑定cases、labels、全部tasks、全部references和export；另有仅test/OOD的execution任务及参考。程序标签、独立参考复算、故障/变异记录、来源隔离、控制器开发选择、统计、资源预算和测试封存分别作为证据，不把标签存在视为正式就绪。

冻结前重新生成逐例标签，检查完整任务覆盖及公开合同绑定，比较全部程序标签、SFT行和heldout gold；修改标签后只更新manifest哈希不能通过。冻结捕获文件哈希后再次校验，检查过程中变化的标签、参考、SFT或证据会被拒绝。锁中明确绑定程序标签与验证证据；训练阶段只读训练/开发SFT及冻结摘要，不重新打开标签库、参考或测试gold。协调人all验证核对全部冻结文件。

来源隔离记录可复算每个源分组、模板、操作族和原始输入指纹。同一精确输入跨源分组或跨划分复用会拒绝，不因改任务ID、要求或模板名而放行。该规则不证明语义独立或许可充分；来源谱系、公开旧资产排除、近重复、授权及有效统计单位仍需实际证据。测试/OOD仍须新建和封存。

独立参考求值器覆盖当前九种编码操作，不调用在线transform/analyzer/oracle。ASCII筛选使用参数化SQLite NOCASE；十进制half-up使用有理数和整数舍入；稳定排序使用插入排序；其余操作有独立控制流。标准库日期和Unicode原语仍有共享依赖，不能称完全独立的形式化证明。范围外操作、非法输入或参考不一致明确失败。

正式程序验证重新执行开发故障矩阵和六种声明变异；blocked开发任务若尚未纳入矩阵，会阻止正式通过，而非悄悄计作覆盖。完整参考与诊断标签按各自语义验证，历史隐藏时允许诊断unknown。执行参考审计由独立求值器生成；控制器计划使用[程序版草案](../configs/controller-plan.programmatic.draft.json)，保留真实开发轨迹、强固定k选择和风险消融，不再要求两位人工声明。

## 命令

协调人准备证据，使用新的输出目录：

```bash
python -m intentlab.programmatic_protocol --cases /private/cases.jsonl --tasks /private/all-tasks.jsonl --references /private/all-references.jsonl --execution-tasks /private/heldout-tasks.jsonl --execution-references /private/heldout-references.jsonl --out runs/new-programmatic-evidence
python -m intentlab.protocol check --spec configs/formal-protocol.programmatic.draft.json --out runs/programmatic-readiness.json
```

证据准备失败保留failed状态和原因，不能标为completed。修改草案中的实际数据、证据、少样本ID、上下文和计算预算后，只有check真正通过才允许freeze；不能为通过检查制作空的功效/来源/预算证明。现有2048草案只是未批准起点，已知不覆盖长候选；正式参数须由实际程序目标和少样本B测量确定。

## 本轮证据和限制

现有600份单模板训练合同/9600候选视图已经通过标签及独立参考复算、故障变异验证和源输入指纹检查。这是开发证据，只有train，不是完整正式数据。

工程检查覆盖：无人工文件的v3冻结、篡改标签/参考拒绝、跨源输入复用拒绝、全部验证、缺少程序绑定拒绝、程序控制器计划和测试gold删除后的训练验证；另有六个真实微型模型子进程的两调度/三种子、中断恢复及所选模型绑定检查。微型工程结果不计入正式9B六次训练。旧版回归初查曾发现缺省schema辅助调用兼容错误，以及旧错误文本断言过时，均修复并保留初查日志。

实际新数据、多模板、验证/测试/OOD、新来源谱系和授权、blocked故障矩阵、强B、功效、真实长度预算及控制器开发选择仍未完成。M3正式冻结与M4正式训练仍未完成，v3接口存在不代表可跳过这些工作。
