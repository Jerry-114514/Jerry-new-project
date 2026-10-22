# Repair intensity development bundle

Development only, 2026-10-22. Full report: [repair-intensity-development-report.md](../../../docs/repair-intensity-development-report.md).

- `model/`: 16 real original Qwen3.5-9B actor/analyzer runs, fixed-k=1 and dynamic-k. Both 2/8 compliant successes, **zero repair proposals**. No adaptive efficacy conclusion.
- `controlled/fixed-{1,2,3}/`: 48 scripted runs with injected missing deliverables, each including a repeated dynamic arm. Fixed-one 0/8; fixed-two, fixed-three and dynamic 8/8. These are engineered controls, not natural errors or independent new tasks.
- `inputs/`: the same eight public development tasks and separate static offline references. Human reviews: 0; never give offline references to a model.
- `runtime-identity.json`, `model-assets.json`: post-run interaction module fingerprints, environment and reverified official assets. No formal preregistration claim.
- `tests.log`, `tests-autodl-final.log`, `tests-local.log`: initial 104 AutoDL tests, final 105 AutoDL tests, final local 105 tests with seven ML skips.
- `remote-replay-audit.json`, per-control audits and `verification.json`: independent replay, budget and k-decision recomputation. There are 64 run records and 64 controlled repair decisions, but only eight source groups reused across all conditions.
- `checksums.json`: SHA256 of all other bundle files. Published text uses LF.
- `interaction-source/`: exact 36-module interaction snapshot, retained so later analyzer fixes do not overwrite this experiment's identity.

Run `python scripts/summarize_intensity_development.py` to rebuild verification and checksums. It checks the bundled interaction snapshot against runtime fingerprints; the current offline auditor recomputes the unchanged task contracts. Use `--source-root` only to verify another exact copy of the same interaction implementation.

No training, human annotation, formal test/OOD evaluation or confirmatory M7 completion is claimed. Historical validation findings and failures remain unchanged.
