# 正式实验工程审计与执行记录

日期：2026-10-22。目标依据：[idea.md](../idea.md)。本记录对应 M1 工程推进，不是正式实验结果。

## 里程碑状态

| 里程碑 | 当前状态 | 可核验证据或剩余依赖 |
| --- | --- | --- |
| M1 工程差距审计与接口 | 进行中 | 新领域合同、静态独立评估、有界工具反馈和重放已实现；正式执行与冻结绑定等仍待补齐 |
| M2 新数据及双人标注 | 进行中 | 原有 8 个开发源任务已有真实执行及盲标注视图；未增加独立任务数，人工审核仍为 0 |
| M3 强基线与协议冻结 | 未完成 | Schema 推理、审核示例加载和冻结工具已实现；实际人工示例、功效与执行审核仍待完成，正式协议未冻结 |
| M4 六次正式训练 | 未启动 | 串行矩阵和中断恢复已用微型模型验证；正式 9B 数据与协议依赖未满足 |
| M5 独立测试 | 未启动 | 不存在经双人核验并冻结的正式测试集 |
| M6 真实执行器四组闭环 | 正式未启动 | 已做 32 次开发运行，四组均 2/8；正式新数据、冻结条件和对照仍未完成 |
| M7 动态控制消融 | 正式未启动 | 新增 fixed-k/dynamic-k 开发实现、显式映射和逐轮重算；正式新任务、配置冻结和预登记消融仍待完成 |
| M8 统计、报告和发布 | 未完成 | 已有任务级配对 bootstrap；种子聚合、闭环指标、长期模型备份待完成 |

用户已选择“先准备标注包，人员稍后确定”。可以继续工程、候选构建和开发测试；不能将无人审核的候选升级为正式人工基准，也不能把自动标注署名为两位人工审核者。

修复数量 k 的新增开发检查见 [报告](repair-intensity-development-report.md)：真实模型 fixed-k/dynamic-k 各 2/8，均无修复机会；受控缺交付物检查中固定 k=2、3 与动态 k 均成功。105 项 AutoDL 测试通过。该进展不替代正式执行与冻结绑定，不将人工审核或 M7 记为完成。

用户指出纯模型从不触发修复的问题后，新增显式 rule/model/hybrid 模式。混合模式在三项开发任务、两种策略上共触发八次修复和八次独立硬检查，Unicode 修复成功，时区仍失败；109 项 AutoDL 测试通过，见 [诊断与修复](analyzer-false-pass-fix.md)。本轮及上一轮尚未提交 Git：自动审批服务因用量额度限制未能执行提交请求，GitHub 同步仍待完成。

随后补充 [单 GPU 独占保护与失败审计](gpu-resource-audit.md)：CUDA 入口共享进程级内核锁并检查实际 compute PID，AutoDL 全部 114 项测试及微小真实 CUDA 检查通过。另保存两组额外探索的全部 64 条失败记录：3B 输出接口失败及两个 9B 进程争用显存。它们不替代正式 M4/M5；正式数据、人工审核和冻结依赖仍未满足。

## 审计发现和本轮修正

1. 原训练器总是在完成训练时读取并评估 test。新增 `--defer-test`，开启后不打开、不分词、不计入数据指纹、不评价 test；只读 train 和 validation。原探索协议默认行为保留，正式开发和训练必须明确开启该参数。验证方式是在 test 文件放入非法 JSON，训练仍可完成且结果含 `test_deferred=true`。
2. 原模型分析器在隐藏历史时强制把 R_INPUT 和 R_ORDER 改写为 unknown。这会覆盖快照已证明违规的正确判断，也掩盖模型本身的错误。现在保留合法模型判断，仍拒绝隐藏或虚构事件引用；独立硬约束检查继续负责执行门控。此变更使新旧协议不相同；旧原始结果不重写，确认性实验必须固定新版本。
3. 原 runner 总是开启独立硬检查，不能做 P1/P2。新增 `--disable-hard-guard`，只关闭独立检查，保留共同的模型接受规则；默认开启。记录开关状态及被拒候选，在关闭条件中 `hard_guard_passed=null`，避免把“未检查”写成“检查通过”。仅在虚拟环境中做关闭消融。
4. 旧 SFT 导出依赖少量 fixture 和固定四项要求。新增 `intentlab.formal_data`，支持显式公开要求、原始输入、当前文件和可见事件；双人审核、独立仲裁、来源记录、分组防泄漏和导出分离。它不是任意自然语言自动要求抽取器，人工仍须核验要求完整性。
5. 新增 `intentlab.formal_eval`，单独统计接口、语义状态、不安全 satisfied 与证据引用存在性。缺失输出计错，不丢弃；按源任务聚合视图后计算主要错误率。证据是否在语义上支持结论仍需人工审核，不能由“索引存在”代替。

## 接口与证据边界

| 正式要求 | 已有能力 | 仍需完成 |
| --- | --- | --- |
| 数据来源及隔离 | 原任务/模板跨集合拒绝、规范化请求重复拒绝、OOD 族隔离、原始文件哈希 | 大规模候选、语义近重复审查、独立来源核验和数据授权审核 |
| 人工标注 | 独立空白包、不同审核者声明、冲突包、第三人仲裁、原始一致率和同一对标注者的 kappa | 真实人员、外部身份与审核记录；程序不证明填写者确为人类 |
| 推理输入隔离 | 通用提示只包含白名单公开信息；测试标签单独导出 | 正式集权限隔离及冻结审计；快照和事件来源真实性核验 |
| 训练测试隔离 | defer-test 模式；导出不在训练目录创建 test.jsonl | 正式训练入口强制配置、独立最终 loss 评估及同精度复核 |
| 强提示基线 | 完整 Schema 通用推理、已审核开发示例导入、身份/模板重叠拒绝、快照和事件引用、runner 协议适配 | 实际人工示例选择和效果评测，示例数量及预算冻结 |
| 执行端和约束 | 新领域合同、独立静态参考、工具反馈和部分失败保留、门控开关、分离权重和共享账本 | 扩展正式任务领域，绑定冻结协议及对照 |
| 预算公平 | 多角色共用硬 token 账本，失败预留计费，阻止超限调用，任务时间含模型切换 | 正式上下文/输出上限冻结、远程提供商计量（当前仅本地推理） |
| 训练公平 | 配对种子、恢复优化器、确定顺序、监督 token 和样本暴露、六组串行矩阵、配对预算核验 | 开发测量及实际冻结的搜索/训练预算 |
| 诊断统计 | 缺失输出保留、三状态混淆矩阵、任务级配对 bootstrap | 训练种子不确定性、开发功效分析、预先固定的多重比较方法 |
| 闭环统计 | 原始事件及成功/违规指标 | 初始不可逆违规分层、新增违规、误拦截及成本效率指标 |
| 冻结与发布 | 源码/Git/模型/tokenizer/环境/数据冻结工具、13 项官方资产再核验、恢复进程检查 | 实际协议封存、测试揭晓审计、持久模型存储及长期备份 |

## 数据和标注工具的使用

运行入口为仓库根目录下的 Python。新工具不需要 ML 依赖。

```bash
python scripts/build_formal_candidates.py --out runs/formal/candidates.jsonl
python -m intentlab.formal_data audit --cases runs/formal/candidates.jsonl
python -m intentlab.formal_data packet --cases runs/formal/candidates.jsonl --out runs/formal/annotation-packet
```

生成器只提供 8 个模型编写的开发场景，包括金额舍入、时区边界、Unicode、稳定排序、null 与缺失值、区间边界、字面 ID 和写后恢复。轨迹为明确注入的工具动作，不是自然模型失败；没有监督标签，不是已核验的独立测试任务。不得用扩大循环生成数量代替独立来源的数据建设。

给两位标注者分别提供 `cases.jsonl` 和空白 `review-template.jsonl`，两人在独立提交前不看对方标签。审核后填写稳定审核者标识和 `human_verified=true`。状态为 satisfied/violated/unknown；证据引用为 `request`、`input:<路径>`、`file:<路径>` 或可见的 `event:<索引>`。历史隐藏时不得引用事件；快照变化可证明违规，快照未变不能证明历史未写入。

人工将两份审核结果合并为 reviews.jsonl，不覆盖历史版本。状态或证据引用有分歧时，生成第三人仲裁包：

```bash
python -m intentlab.formal_data conflicts --cases runs/formal/candidates.jsonl --reviews runs/formal/reviews.jsonl --out runs/formal/disputes
python -m intentlab.formal_data export --cases runs/formal/candidates.jsonl --reviews runs/formal/reviews.jsonl --adjudications runs/formal/adjudications.jsonl --out runs/formal/reviewed
```

没有分歧时省略 `--adjudications`。仲裁人须与该任务的两位初审人不同，填写理由并审核所有要求；工具不会自动生成仲裁标签。已存在的输出目录不覆盖，以保留来源。

训练和验证导出为 train.jsonl / validation.jsonl；测试和 OOD 的公开 cases 与 gold 分别写入 `heldout/<split>/cases.jsonl` 和 `heldout/<split>/gold.jsonl`。该目录分离不是操作系统访问控制，使用时还需按职责隔离访问。manifest 明确 `protocol_frozen=false`，不能把审核导出当作已登记协议。

离线推理结果采用 `{"case_id":"...","text":"模型原始输出"}`，最终离线评分示例：

```bash
python -m intentlab.formal_eval --cases runs/formal/reviewed/heldout/test/cases.jsonl --gold runs/formal/reviewed/heldout/test/gold.jsonl --predictions runs/formal/test-predictions.jsonl --out runs/formal/test-score.json
```

评分不运行模型，也不把 gold 传给模型。严格 Schema 和预先定义的 ID 对象归一化同时报告；归一化不改状态，ID 与键冲突时报错。重复 case 或 JSON 键拒绝，缺失输出保留在分母。任务级 bootstrap 区间条件于已训练模型，不包含跨种子训练不确定性。

## 验证记录与下一步

本轮工程检查使用已有 AutoDL ML 环境中的微型真实 Transformer，验证训练器行为及恢复；不是新一轮 9B 正式训练。测试日志保存在 `examples/results/formal-m1-engineering/`。对新数据的 5090 长度与预算压力测试仍待正式候选量和协议确定。

后续优先补齐正式执行与冻结绑定、动态纠偏强度及消融，同时扩大新来源任务并人工审核。新领域闭环的实际失败见[开发报告](execution-development-report.md)，冻结器和训练矩阵见[正式协议指南](formal-protocol-guide.md)。人工审核待人员确定。M1–M8 均未被本轮工程工作替代或缩小。

## 第二轮：强提示推理、共享预算和分离角色

已完成以下工程接口，并在 AutoDL 现有 ML 环境通过全部 71 项测试；本地无 ML 依赖的环境通过 65 项，明确跳过 6 项真实模型集成测试。证据见 [第二轮结果目录](../examples/results/formal-m1b-engineering/)。

1. `python -m intentlab.formal_inference` 只读取被评估任务的公开输入，不接收其 gold。它使用完整 Schema 与快照/事件引用，保留模型原始输出；失败样本保存空输出及错误记录，不从分母删除。输出目录不能覆盖，写入过程逐条 flush。程序中断后的 manifest 保持 running，必须核查进程后人工处理，不支持静默跳过或自动重启。
2. 少样本条件通过 `reviewed_examples` 载入经过双审和仲裁的 train/validation 示例，按 case_id 确定顺序；拒绝测试示例、源任务或模板重叠、规范化请求重复及 OOD 族泄漏。正式示例的实际选择与数量仍需在开发阶段冻结。没有人工示例时不能把自动标签包装为基线 B。
3. `TokenLedger` 在调用前为 prompt 和允许生成长度预留额度，所有角色共享同一任务限额；成功后按真实生成 token 结算。失败而无法确认生成长度时保守扣除完整预留，记录 completion_tokens=null，不能伪装成已知实际用量。超预算调用被拒且记录；活跃预留不能通过 reset 清空。
4. `LocalModelPool` 为 actor 和 analyzer 配置不同路径，最多保留一个本地模型。不同路径切换时卸载后再加载，同路径复用；两者使用相同共享账本。重载开销计入任务墙钟并记录独立加载记录。这是显存可行的正确性实现，不是吞吐优化；不同对照条件须采用相同加载规则。
5. `SchemaLanguageModelAnalyzer` 为现有闭环适配完整 Schema 和字符串证据引用；不再把合法快照违规判断强制改成 unknown。引用不存在或严格输出不合规时记录错误并弃权。离线评分仍分别记录接口、语义和引用存在性，不能把在线弃权后的状态当作原始预测。
6. 训练检查点新增监督目标 token 与逐样本使用次数，连续训练与恢复结果均核验一致；旧检查点缺少这些字段时按原确定采样顺序重建。缓存每个 epoch 的排列，避免每取一个样本都重新打乱全量数据。

### 已实测的 9B 开发推理

使用官方原始模型、零样本完整 Schema，在 8 个未审核开发候选上完成推理。生成错误 0/8，严格接口合规 8/8，生成阶段约 27.14 秒；不含指纹计算和初始加载。没有读取真值、没有计算诊断准确率，不构成正式质量结论。

另用官方原始权重作为执行角色、既有 Plateau 开发适配器作为分析角色，执行三次工程调用“执行—分析—执行”：三次加载均完成，共计费 773 tokens，总墙钟约 26.16 秒，峰值 allocated 17.06 GiB / reserved 17.15 GiB。没有证明这些调用完成了真实任务；旧适配器仍是旧协议的开发产物，不作为本轮正式训练结果。对应实际原始输出和账本见 [角色检查](../examples/results/formal-m1b-engineering/runs/role-model-audit.json)。

### 命令

以下命令在 AutoDL 项目根目录运行，使用已验证的 venv；输出目录需不存在。首次只在开发候选运行。

```bash
/root/autodl-tmp/intentlab-venv/bin/python -m intentlab.formal_inference --cases candidates.jsonl --model /root/autodl-tmp/models/Qwen3.5-9B --device cuda --max-new-tokens 512 --token-budget 8192 --out runs/schema-development
```

少样本条件增加 `--example-cases`、`--example-reviews`、必要时 `--example-adjudications`，以及 `--example-count`。不得用查询任务自己的标注作为示例。

现有 fixture 闭环可指定固定执行模型与独立分析模型，供工程验证；新领域正式数据尚不能直接交给该 runner：

```bash
python -m intentlab run --actor-model-path /path/to/fixed-model --analyzer-model-path /path/to/analyzer --analyzer-interface schema --device cuda --token-budget 8192 --max-new-tokens 512 --split validation --policies fixed-full dynamic --repeats 1 --out runs/separate-roles
```

关闭独立检查的 P1/P2 使用新输出目录并增加 `--disable-hard-guard`。此开关不关闭共同模型门控。诊断离线评测每个证据视图重置预算；执行闭环每个任务重置预算；两种预算单位在清单中分开记录，不能混合比较。

当前主模型与适配器资产指纹在实测清单中可追溯，但正式冻结器还须绑定 tokenizer、全部角色基础模型、提示和代码版本。只记录路径不等于正式冻结。远程 HTTP actor 尚未接入该账本，不可用于声称本地预算公平的主对照。
