# M2m: input-layout-matched, wording-heldout candidates

200 new private procedural test sources, 800 views. Train/validation exports remain byte-identical; OOD public tasks/cases unchanged. The original three-file structural test is preserved, not overwritten. No test model calls or final candidate selection.

All 1050 combined source references independently recomputed; original development fault/mutation validation regenerated. Local and AutoDL builds agree for 17/18 files byte-for-byte. The one exception is export/manifest.json line endings only; its parsed/normalized content matches. Both exact hash lists are retained. No seed, raw task, reference, label or heldout observation contents are public.

`strict_iid_claim` remains false: input distributions are matched by generator role, but wording is held out and blocked cadence/finite family quotas require qualified inference. This is not source-independence proof or completion of the original in-distribution-testing requirement. Formal protocol still points to the previous candidate and is not frozen.

238 local tests discovered, 14 optional ML skips; other tests pass. New fixture initially assumed all families require the operation field, but key_present deliberately permits missing keys; assertion corrected to compare each family against its train counterpart. No production rule change resulted. See [details and replay command](../../../docs/input-matched-test-candidates.md).
