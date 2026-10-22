# v2 execution protocol binding engineering evidence

2026-10-22. [Binding guide](../../../docs/execution-protocol-binding.md). **Engineering only; actual human reviews: 0; no formal 9B training.**

- `tests-autodl.log`: all 124 tests pass in the existing AutoDL ML environment. `tests-local.log`: 116 pass, eight optional ML integration skips.
- `runtime-identity.json`: post-run source/package identity; 38 interaction module hashes match this implementation. This is not a formal freeze.
- `matrix/protocol.engineering.lock.json`: v2 synthetic-unit lock with explicitly synthetic identities, placeholder evidence and a real tiny CPU model. Its readiness is not formal readiness.
- `matrix/matrix.json`, per-job and attempt records/logs: six tiny worker jobs, seven attempts including one interrupted/resumed job; all three paired seeds agree in data/base identity and token/example exposure.
- `matrix/engineering-scope.json`: execution task/reference/audit files, initial reviews and held-out gold were removed before workers ran. Training and resume completed without them.
- `verification.json`, `checksums.json`: saved result/config and paired-exposure recomputation plus file hashes.

Each pair used only four example exposures and 208 supervised tokens. These are infrastructure checks, not a substitute for the six planned official Qwen3.5-9B trainings or a scheduler efficacy finding. No actual human labels are generated or accepted by this audit.

Run `python scripts/audit_execution_binding_evidence.py` at repository root to recompute saved records. Tiny temporary checkpoints and weights were validated during the live test, but are not stored in this report, so this offline audit does not revalidate model binaries or claim durable model backup. Runtime paths in the synthetic lock refer to its temporary engineering environment and are not a usable formal protocol.

The development execution CLI still refuses test/OOD. Actual reviewed data, scientific evidence, post-training adapter identity binding, sealed execution/reveal entry, formal experiments and final statistics remain outstanding.
