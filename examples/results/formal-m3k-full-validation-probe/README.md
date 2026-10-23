# M3k: pending full-development validation/resource/resume probe

Launch snapshot is a verified live CPU dependency wait, not completed training. It waits for the entire baseline-scoring/natural-collection/intake predecessor to exit successfully. No concurrent GPU model is started.

Expected complete data: 2432 train views from 600 sources and 632 validation views from 150 sources, including 64 natural visibility views sharing old sources. Only median/max train cases are used for four pressure updates; all validation views are evaluated at updates2/4, across stop/resume. Production encoding, EOS, no truncation, 16384 predeclared probe cap, original official 9B NF4/BF16, same rank16/alpha32 and batch1/accum2. Invalid test marker is deferred.

Timing wrapper preserves the original evaluation function call/result, adds CUDA synchronization and writes separate cost records. It is not a new loss algorithm or formal training endpoint. No empirical cost/quality/resume outcome is claimed yet. Four focused tests and local 247-test suite (14 optional ML skips) pass; initial mock-code newline-hash expectation was corrected.

Source checkout must remain clean at b4a757a until all pending dependent jobs end. Driver, helper and wrapper are external and hash-bound. Raw SFT, targets, case-length rows, checkpoints and eventual logs remain private. See [full protocol and limits](../../../docs/full-validation-resource-probe.md).
