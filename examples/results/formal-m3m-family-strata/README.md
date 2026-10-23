# M3m: optional operation-family-stratified source bootstrap

Analysis-plan v2 samples the same number of sources inside each operation family. Point effects, all paired seed outcomes, token-weighted denominators and the one-primary/17-secondary registry remain fixed. Family labels must be consistent; strata with fewer than two sources suppress inferential outputs by this plan's conservative rule.

Arithmetic only: an intentionally fixed +1/-1 two-family fixture has point effect0 under both resamplers. Intervals differ because the conditional designs differ; this is not real-model improvement or coverage validation. The complete legacy v1 fixture report exactly matches recomputation using the previous commit's source. Old results are not rewritten.

The programmatic protocol draft selects v2; it is not frozen or deployed to active AutoDL jobs. Independent-source and sign-flip exchangeability assumptions remain; other generator quotas are not held fixed. Five new statistics tests plus one v2 frozen-stage receipt test,13 targeted statistics tests total, local256-test suite with14 ML skips. No private heldout data or real model outputs were read for this change. See [interpretation and remaining assumptions](../../../docs/family-stratified-statistics.md).

With repository history available through the recorded old commit, replay into a fresh directory using `python examples/results/formal-m3m-family-strata/record-driver.py --out runs/new-statistics-arithmetic` and compare arithmetic-check.json. No model or private dataset is required.
