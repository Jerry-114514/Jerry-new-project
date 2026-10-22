# Hybrid analyzer repair verification

2026-10-22, development only. [Diagnosis and results](../../../docs/analyzer-false-pass-fix.md).

Six real original Qwen3.5-9B runs: first three public development tasks, fixed-full/dynamic, hybrid public-rule authority with retained model sidecar. Both conditions achieve 2/3, proposing four repairs and executing four independent hard checks each. Decimal succeeds initially, Unicode succeeds after repair, timezone remains wrong after three attempts. No hard-guard rejections or workflow errors. This verifies repair activation, not improved LM diagnosis, formal efficacy or a safety effect.

- `hybrid/`: raw runs, manifest, summaries and strata; model and effective judgments remain separate.
- `inputs/`: all eight existing public development definitions and separate references; only the first three were selected. Human reviews: 0.
- `runtime-identity.json`, `model-assets.json`: post-run source/environment record and reverified official model assets. Not a formal freeze.
- `interaction-source/`: the exact 36 interaction modules, retained before the subsequent GPU lease change; source fingerprints refer to this copy.
- `tests.log`: all 109 tests pass on AutoDL. `tests-local.log`: 102 pass, seven optional ML skips.
- `verification.json`: six independently replayed records, 14 sidecar merge decisions recomputed, per-run repair opportunities and override counts.
- `checksums.json`: hashes of all other files; text uses LF.

Rebuild with `python scripts/audit_hybrid_development.py --root examples/results/formal-m1f-hybrid` at the corresponding implementation. Another experiment began sharing the GPU after this run started; do not infer performance benefits from timings. Negative timezone results remain in the denominator. This is not formal M6/M7 completion, and no test/OOD was evaluated.

Publication update: initially blocked by automatic approval review quota and then git transport timeouts, the bundle was subsequently published through the connected GitHub interface in commit `7396e01`. Its tree exactly matches the reviewed local tree. Local and separate AutoDL development copies remain available.
