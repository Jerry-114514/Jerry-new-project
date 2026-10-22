# 正式实验工程审计与执行记录

日期：2026-10-22。目标依据：[idea.md](../idea.md)。本记录对应 M1 工程推进，不是正式实验结果。

## 里程碑状态

| 里程碑 | 当前状态 | 可核验证据或剩余依赖 |
| --- | --- | --- |
| M1 工程差距审计与接口 | 进行中 | 本文矩阵；新增数据、标注、离线评分入口；训练和门控修正 |
| M2 新数据及双人标注 | 进行中 | 8 个未审核开发候选与空白标注包；人工人员稍后确定 |
| M3 强基线与协议冻结 | 未完成 | 全 Schema 已有通用提示构造；少样本选择、功效分析、冻结器未完成 |
| M4 六次正式训练 | 未启动 | 现有 24 步探索运行不计为正式训练 |
| M5 独立测试 | 未启动 | 不存在经双人核验并冻结的正式测试集 |
| M6 真实执行器四组闭环 | 未启动 | 独立检查开关已实现；新任务执行接口、固定执行器和预算账本待完成 |
| M7 动态控制消融 | 未启动 | 需先完成上述基线与协议；不把现有排序规则称为动态 k 控制 |
| M8 统计、报告和发布 | 未完成 | 已有任务级配对 bootstrap；种子聚合、闭环指标、长期模型备份待完成 |

用户已选择“先准备标注包，人员稍后确定”。可以继续工程、候选构建和开发测试；不能将无人审核的候选升级为正式人工基准，也不能把自动标注署名为两位人工审核者。

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
| 强提示基线 | 完整 JSON Schema、任意数量要求、快照和事件证据引用 | 与本地模型推理集成、开发示例选择、模型输出协议适配 |
| 执行端和约束 | 虚拟工具、事件重放、已有输入和顺序约束、门控开关 | 新领域任务的执行器和独立 oracle；分开的 actor/analyzer 权重 |
| 预算公平 | 单一本地 backend 内硬 token 限制 | 多 backend 共用账本、调用失败计量、统一计时与上下文预算 |
| 训练公平 | 配对种子、可恢复优化器、确定数据顺序 | 监督 token 累计、样本暴露量、固定搜索预算和正式矩阵调度器 |
| 诊断统计 | 缺失输出保留、三状态混淆矩阵、任务级配对 bootstrap | 训练种子不确定性、开发功效分析、预先固定的多重比较方法 |
| 闭环统计 | 原始事件及成功/违规指标 | 初始不可逆违规分层、新增违规、误拦截及成本效率指标 |
| 冻结与发布 | 代码/数据哈希、已有 GPU 模型资产索引 | 协议冻结器、测试揭晓审计、持久模型存储及长期备份 |

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

下一步优先完成通用诊断推理入口与强提示基线，以及共享预算账本和可切换执行/分析权重；同时继续构建有来源的新候选与标注包。人工审核待人员确定。M1–M8 均未被本轮工程工作替代或缩小。
