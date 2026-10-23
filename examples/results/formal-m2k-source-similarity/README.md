# M2k: descriptive normalized source similarity

`audit-driver.py` reads only the private public task contracts and the published hash manifest. It never reads reference/gold files or model predictions. Normalize away random identity/tag values, field names and file boundaries, then compare typed row sequences conditional on identical operation parameters. A normalized row edit distance <=0.25 is a descriptive flag, not an independence or leakage guarantee.

Summary replayed exactly on Windows and AutoDL. Two train/validation pairs are flagged; no candidate is removed or reassigned. Actual source tasks and pairwise flags remain private. Run the driver at its configured paths to replay; an existing output directory is rejected. Other environments must explicitly set the three root constants to their private dataset, source and fresh output locations.

See [method, counts and limitations](../../../docs/procedural-source-similarity.md). No test model outcomes, no data acceptance claim and no formal freeze.
