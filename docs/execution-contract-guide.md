# 新领域执行合同与独立评估

本接口用于 [idea.md](../idea.md) 的工程建设和开发实验。它覆盖八类明确的 JSON 数据操作，支持真实本地模型执行、分析、候选修复和独立事后评价。当前数据仍是已有八个公开开发源任务的执行变体，不增加独立任务数量，也不是人工审核后的正式基准。

## 公共任务和静态参考分开

`scripts/build_execution_development.py` 生成两个文件：

- `tasks.jsonl`：公开请求、原始输入、原文锚定要求、操作参数、必需字段、依赖关系和输出路径。
- `offline-references.jsonl`：另存的静态参考文件，只有事后评估器读取，不交给执行模型、分析模型或规则执行器。

八类操作是 decimal half-up 舍入、显式时区日期筛选、Unicode NFC、稳定排序、缺失与 null 区分、半开区间、字面字符串 ID 和原样复制。它们只是受支持的合同语言，不代表已经支持任意自然语言任务。

参考数据由常量独立编写，不调用 `contracts.transform` 或 `public_solution` 生成。回归检查故意破坏公共求解器，确认离线评估仍按原静态参考判错。这验证软件上的独立性，不证明人工真值已经核验；静态参考的正确性仍须独立人工审核。

每项要求绑定四种规则之一：输入全程保护、先验证再写入、交付物精确匹配、报告与实际文件一致。原始整数和字符串的保留要求写入公开请求；比较保留 JSON 类型，布尔值不能冒充整数。报告行数参照实际输出，错误数据配上正确行数的报告仍可以满足报告一致性，但不能满足结果正确性。

缺少必需字段时，只允许在真实失败检查后写 blocked 报告；不允许产生数据结果。工具自行计算字段检查结果，模型的 `ok` 只是自报值，不能把失败伪装成通过。

## 模型和规则使用相同公共规格

形式化诊断输入新增可选 `execution_spec`，保留公开操作、要求规则和依赖图。规则分析器和模型分析器都能看到同一份规格。该字段有明确白名单和验证规则，不能放入 oracle、状态标签或任意额外字段。

`formal_data` 和 `formal_inference` 可导出、训练和推理这种输入；少样本推理可通过 `--example-ids` 选择审核示例的准确顺序，并通过 `--context-limit` 限制实际上下文。已有旧协议结果不重写，新协议与旧提示不能混合作为确认性对照。

`snapshot_paths` 是公开证据目录中的路径清单，使模型可以引用“要求的文件不存在”这一事实；未知历史不能被引用，当前快照已证明变化时也不能一律弃权。

## 有界工具反馈

真实执行模型返回：

```json
{"actions": [{"op": "validate", "ok": true}], "done": false}
```

`done=false` 表示模型等待工具反馈。下次调用会得到实际事件和文件，继续 initial 或 repair 阶段。`done=true` 结束该次提议，不代表任务已经成功。独立评估不采信完成自报。

初始执行和每次候选修复默认最多三次工具反馈调用，一份完整提议累计最多 16 个动作；每个任务共享 actor/analyzer token 账本。调用上限、输出上限、上下文和修复次数全部记录。触及工具步骤上限会记录计数，不会被描述为交付成功。

初始动作真实提交到虚拟环境；候选修复只在克隆状态中执行，多次工具反馈共享同一个候选状态。独立检查会看到完整事件增量，包括跨两次调用写入再恢复输入的情况。拒绝的候选不会污染已提交状态。

初始阶段后续调用出错时，已经执行的初始动作仍保留在记录和评估中；修复阶段出错时保留候选轨迹，但不提交候选。日志保留每次反馈的完成标志、动作及格式情况。

## 格式与真实动作效果分开

开发入口默认 `--actor-envelope extract`：当模型已经明确给出合法 `actions` 和布尔 `done`，仅提取这两项，忽略回显的其他顶层字段。它不修改动作、参数或完成标志，不会把单个裸动作补造成完整计划。

额外字段、严格格式是否合规及原始生成均保留。模型回显的 `files`、`events` 等字段不会作为工具事实使用；真实状态只由 `State.apply` 更新。重复 JSON 键、无效动作、未知字段、非法路径或无效完成标志仍拒绝。这里的“未知字段”指动作对象中的字段；顶层额外字段仅在 extract 模式下忽略。

需要严格包格式的对照使用 `--actor-envelope strict`。所有主比较必须提前冻结同一处理方式，同时报告严格格式和实际任务指标，不能把投影后的可执行率冒充模型原生格式合规率。

## 初始不可逆问题与修复新增问题

离线评估器只在整个交互结束后评价初始快照和最终状态，真值不会控制目标选择、候选接受、补证或停止。记录区分：

- `initial_metrics`：初始执行结束后的事实，包括格式错误前已经发生的部分动作。
- `irreversible_hard_violations`：全历史中实际已发生的输入写入或非法顺序事件；写后恢复仍保留。
- `feasible_at_repair_start`：初始阶段未发现上述不可逆历史违规的分层，不保证剩余预算内一定可解。
- `repair_introduced_hard_violations`：初始事件边界之后新提交的违规事件对应的要求。即使同一要求初始已经出错，修复阶段再次违规仍会计入。
- `hard_guard_rejections`：在候选状态中被拦截的提议，与实际提交的违规分开。

`hard_violations` 同时包含尚未完成必需检查等未满足的硬要求；不能把其全部解释为已经发生破坏性写入。安全事件分析使用单独的事件记录。

报告同时保留全任务指标和初始未发生不可逆历史违规的分层，失败、预算耗尽、接口错误不从分母删除。`interaction_seconds` 与离线评估时间分开；模型加载和切换属于交互成本。

## 运行与盲标注

在仓库根目录使用有 ML 依赖的 venv。输出目录须是新目录。

```bash
python scripts/build_execution_development.py --out runs/execution-development
python -m intentlab.execution --tasks runs/execution-development/tasks.jsonl --references runs/execution-development/offline-references.jsonl --out runs/execution-rule --rule-actor
```

真实原始 9B 同时担任执行与分析角色的开发命令：

```bash
python -m intentlab.execution --tasks runs/execution-development/tasks.jsonl --references runs/execution-development/offline-references.jsonl --out runs/execution-model-on --actor-model /root/autodl-tmp/models/Qwen3.5-9B --analyzer-model /root/autodl-tmp/models/Qwen3.5-9B --device cuda --policies fixed-full dynamic --max-tool-steps 3 --max-repairs 3 --context-limit 4096 --max-new-tokens 512 --token-budget 16384 --actor-envelope extract
```

P1/P2 的开发消融改用新输出目录并加 `--disable-hard-guard`；其余参数不变。没有指定分析模型时使用公开规则分析器，必须在报告中注明；`--rule-actor` 是明确的工程执行器，不能称为真实模型。

该开发入口拒绝 test/OOD 执行，以免把尚未绑定完整冻结协议的实验当作确认性评估。正式执行仍需将任务/参考、模型选择和全部运行条件接入冻结器及测试揭晓审计。

从已完成的真实轨迹重建盲标注包：

```bash
python -m intentlab.execution_annotations --tasks runs/execution-development/tasks.jsonl --records runs/execution-model-on/runs.jsonl runs/execution-model-off/runs.jsonl --out runs/execution-annotation
```

导出器重放初始动作和各候选，核对最终提交状态，按完整公共观察去重。只把 `packet/` 给两位独立审核者；其中没有模型判断、oracle 指标、接受决策或方法名，标注表保持空白。来源映射另存，仅用于审计，不是权限隔离机制。

轨迹增加视图数量，不增加独立源任务数量。审核完成数仍为 0；不自动把任何模型或规则输出登记成人工标注，也不把这些公开开发源任务再放入正式测试。

## 开发记录的解释

早期运行分别暴露了裸动作缺少顶层数组、校验提议被当作完整执行、回显上下文造成严格包格式失败，以及在历史已可见时重复补证的问题。原始失败记录保留，作为开发协议变更记录；它们不是预先登记的质量实验。

最终开发对照仍只覆盖这八个源任务。规则基线可以按显式规格解题，不能据此声称学习率创新或任意自然语言泛化；模型仍可能误判缺失交付物、过度弃权或错误停止。正式研究需新的隔离任务、人工审核和三种子训练，而不是把接口修正包装成模型能力提升。
