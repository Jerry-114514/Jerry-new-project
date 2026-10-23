# M2i: programmatic fault coverage and declared mutants

Existing 600 train contracts, 12 additional fault scenarios each, 7200 new views. Combined pool has 9600 views and preserves the old 2400-case prefix. No new source tasks, templates, human labels or model calls. R_ORDER now has 1800 violated views in this candidate pool.

All 28800 new requirement states match independently declared scenario expectations. Six isolated, explicitly edited offline labelers each produce counterexamples. This does not prove exhaustive correctness or reference quality. Blocked-input cases are explicitly outside this matrix.

`audit.py` checks metadata by default. With `--private-root` and `--original-adapted`, it rebuilds all fault cases, regenerates labels, repeats all six mutants and verifies the private files. Public artifact hashes are exact bytes; source identity normalizes text line endings.

Raw inputs, cases, expectations, labels and SFT remain private. The expanded pool is not frozen as the final training set. See [interpretation and limitations](../../../docs/contract-fault-coverage.md).
