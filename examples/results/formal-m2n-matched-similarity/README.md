# M2n: matched-input candidate overlap, including negative findings

Same normalization and 0.25 row-edit threshold as M2k, applied to the M2m candidate public contract file pinned by SHA256. No gold or model output is read. Six exact normalized test/train pairs (five test sources), 165 near pairs (74 test sources). Candidate data is not removed, reassigned, regenerated or approved.

Both environments reproduce the same summary and private pair-list content; raw pair-list JSON differs only in line endings. No exact-byte claim is made for that metadata file. Pair IDs, normalized inputs and source-stratum lists remain private. Published aggregate strata are descriptive candidates, not finalized inferential analyses or evidence of source independence.

`audit-driver.py` is the exact M2k algorithm with only candidate dataset/output paths and expected input hash updated. It refuses an existing output directory. `strata-driver.py` was run locally after that audit; it creates a private source-level mask, keeping all four views of a source together. `audit.py` checks public recorded metadata integrity, not private data reconstruction. See [interpretation](../../../docs/matched-test-similarity.md).
