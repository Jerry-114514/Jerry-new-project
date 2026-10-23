# M3h: development prompt search in progress

This directory records the plan and exact drivers, not completed results. Preparation completed before the first inference call; publication occurs after inference started. It is a development search, not confirmatory preregistration.

All 600 validation views (150 source groups) are scheduled for A zero-shot, B3 three train examples and B4 four train examples. Example profiles cover complete, combined violations, hidden history and a mixed-status single fault, selected in that order using distinct families and minimum SHA256(case_id). Selection does not use example lengths or model outcomes. Train examples have no source/template/request overlap with the validation cases.

Maximum measured prompt lengths: A 6415, B3 10308, B4 12093. All conditions share context/token budget 13312, output cap 512, greedy decoding, official original Qwen3.5-9B BF16 and one resident backend. This input length coverage does not by itself establish longest few-shot GPU feasibility. Calls preserve raw output and ledger records; failures remain in denominators.

The generation process reads only public validation cases and programmatically labeled train examples, not validation gold, test or OOD files. Separate scoring is refused until all generation completes. Eligible B choices are B3/B4, selected on minimum validation task-mean normalized state error, then strict errors, then fewer examples. A is a reference condition and is not eligible as B. Same-validation comparisons after selection are descriptive and selection-biased. No partial scores are used to change the plan.

Actual predictions, validation gold and examples remain private. Plan contains hashes and development example IDs only; seeds and heldout contracts are not published. Formal 6-run training has not started. Results and final B choice remain pending.
