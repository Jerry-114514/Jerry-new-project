# M3f: supervised-position logits resource probe

Official Qwen3.5-9B NF4/BF16 QLoRA on a single RTX 5090: 4608 tokens, 512 synthetic target tokens, two updates, exit 0. Peak reserved 19312672768 bytes. Synthetic unrelated targets only; not a formal endpoint or accuracy experiment.

The driver runs against an isolated archive of parent e698bec plus the recorded `intentlab/neural.py` patch. The driver and patched file are bound by hashes; the runtime source snapshot is saved. No real labels or sealed test data are used. The test file intentionally is invalid and deferred. Adapter/checkpoint weights remain outside this public evidence directory and are not formal deliverables.

`python examples/results/formal-m3f-supervised-logits/audit.py` checks saved evidence and data identity; it does not repeat training or prove tokenizer lengths independently. The recorded driver asserts exact token lengths using the official tokenizer before training. See [implementation, checks and limits](../../../docs/supervised-logits-memory.md).
