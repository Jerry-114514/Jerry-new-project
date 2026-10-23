# M1p: programmatic protocol v3 engineering evidence

Schema v3 binds explicit-spec programmatic labels without human review fields. v1/v2 remain available for legacy reproduction. This artifact records engineering migration, not a formal freeze or official-9B training.

600 existing single-template train contracts / 9600 candidate views: local and AutoDL independent reference/fault validation records and source-isolation records match. Static reference computation covers ASCII filtering here; separate unit tests cover all eight prior operation families, giving nine implemented operations in total. Shared standard-library primitives remain dependencies, not formal proofs.

AutoDL full suite: 219 tests, zero skips, including six real tiny-model training workers, interruption/resume and validation-selected execution model binding after coordinator labels/references and held-out materials are deleted. Local dependency-light suite: 219 tests, 14 ML skips. Both counts remain distinct. Initial legacy-regression failure metadata is retained and explained in the report.

```bash
python examples/results/formal-m1p-programmatic-protocol/audit.py
python examples/results/formal-m1p-programmatic-protocol/audit.py --adapted /private/adapted --expanded-cases /private/expanded-cases.jsonl
```

Default mode verifies saved metadata and implementation identity. Private mode recomputes all candidate label/reference/fault/mutation and source-isolation evidence. No source rows, reference files, full labels or actual gold are published. The source snapshot records the code/configuration/test identity used here; verification should use this artifact's recorded revision.

See [protocol guide](../../../docs/programmatic-protocol-v3.md). Final view selection, new validation/test/OOD, template diversity, blocked fault coverage, strong B, power, provenance/release and compute budgets remain unfinished.
