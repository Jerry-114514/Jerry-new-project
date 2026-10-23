# M3e: full candidate prompt-length coverage

600 unreviewed train contracts / 2400 injected views, official pinned Qwen3.5-9B tokenizer. CPU only; no model inference, human labels, formal training or budget approval.

`measure-driver.py` requires a clean source checkout at 031007bef9f16360e5d4ff30f3c55acd0835954c, verified official tokenizer assets and the private M2g cases. It measures both complete prompt formats, asserts prior 48-view hash/length parity and writes only IDs, hashes and lengths alongside aggregates. The private cases are read by the existing schema validator; no reference solution or review file is opened.

```bash
python measure-driver.py --source /private/source-at-031007b --model /private/Qwen3.5-9B --cases /private/training-scale/adapted/cases.jsonl --out /private/new-length-output
python audit.py --rows /private/new-length-output/lengths.json
```

The full rows remain private and are bound by `private-rows.json`. `audit.py` independently recomputes summary counts from them and checks public artifact hashes. It does not re-tokenize: the driver performs that measurement with pinned assets. See [interpretation and initial failed preflight](../../../docs/training-length-budget.md).
