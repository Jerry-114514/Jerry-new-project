# M2j: private multi-template procedural candidate dataset

600 train / 150 validation / 200 seen-family test / 100 operation-OOD source draws, four views each: 4200 views, 26 templates, ten operation families. All split seeds and raw heldout materials remain private. Code and public seed commitments cannot reconstruct actual heldout samples without the private seeds.

These are independently seeded procedural draws conditional on fixed generator families, not independently human-authored tasks or proven semantic independence. Seen-family test also shifts file layout/required fields and is not strict IID. OOD reserves stable_unique and conditional_group_sum. No model inference, formal protocol freeze or training has occurred on this batch.

Independent reference and public-solver agreement checks cover all 1050 contracts. Development includes 64 missing-field contracts; the fault matrix covers 8744 views, including eight blocked scenarios. All six declared labeler mutants have counterexamples. Full reference correctness and all possible faults are not formally proved.

Local and AutoDL summary/validation/source-isolation records match. AutoDL 226 tests passed with no skips; local 226 tests include 14 ML skips. Earlier candidate revisions are retained privately; their tasks stay identical while fault views were improved before any model evaluation.

```bash
python examples/results/formal-m2j-procedural-candidates/audit.py
python examples/results/formal-m2j-procedural-candidates/audit.py --private-root /private/procedural-batch --evidence-root /private/procedural-evidence
```

Default checks metadata only. Private coordinator mode reconstructs every source/trajectory with private seeds, compares exact JSONL hashes, regenerates labels and repeats reference/fault/mutation checks. Never run private reconstruction in a training or online-inference role. Only aggregate metadata, hashes and replayer are public. See [scope, revisions and remaining work](../../../docs/procedural-candidate-dataset.md).
