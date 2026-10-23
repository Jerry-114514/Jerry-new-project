# M2h: explicitly programmatic diagnostic labels

User chose the fully programmatic route on 2026-10-23; idea.md 2.0 records the scope change. Existing 600 single-template train contracts produce 2400 view labels / 9600 requirement states. No human reviews, new model calls, new sealed test/OOD or formal training.

The new offline evaluator uses static reference files and its own state machine, not the online solver/analyzer or execution oracle. On these candidates its states agree with the online analyzer on all 9600 items. This is a consistency observation, not proof of correctness or independent sources. Labels for hidden histories retain unknowns.

**Coverage gap:** R_ORDER has 1800 satisfied / 600 unknown and zero violated. Additional order-failure trajectories and other systematic perturbations are needed before formal training. There remains only one shared project template.

Raw tasks, reference files, full labels and SFT pairs stay private. Only metadata, hashes and replayer are published. The artifact's `formal_protocol_migrated=false` records the stage of this export; the old human-reviewed formal protocol still needs a separately versioned machine-evidence path.

```bash
python examples/results/formal-m2h-programmatic-labels/audit.py
python examples/results/formal-m2h-programmatic-labels/audit.py --private-root /private/adapted --export /private/programmatic-export
```

Private replay regenerates all labels, checks file identities and all SFT content. Default mode checks saved metadata only. The production module's own tests are in `tests/test_programmatic_labels.py`. Full programmatic export is not protocol freeze; see [implementation guide](../../../docs/programmatic-label-guide.md).
