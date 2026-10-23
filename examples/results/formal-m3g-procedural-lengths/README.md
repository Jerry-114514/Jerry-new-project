# M3g: actual procedural SFT lengths

The official pinned tokenizer measures all 2400 train and 600 validation pairs using production encoding, including target EOS. No heldout files or model weights are read by `measure-driver.py`. Summary binds pair-file hashes, six official tokenizer assets and source commit. Full per-case lengths remain private.

`probe-driver.py` selects lower-median and maximum total-length pairs in each development split, then performs two real 9B QLoRA updates with a 7168 context and deferred invalid test file. It is a development resource probe, not one of the six formal trainings. Probe completion must be established from its recorded attempt and result, not the existence of this driver.

The recorded probe completed with exit 0, two updates and test deferred. Peak reserved memory was 18,807,259,136 bytes; process wall time was 51.67 seconds. Validation includes the 6628-token maximum development pair. This is not a 7168-token training backward stress test. No full validation-set accuracy or pre-training baseline was measured.

Run `python examples/results/formal-m3g-procedural-lengths/audit.py` to check saved evidence integrity and key invariants. This does not replay tokenization or training. See [interpretation and remaining budget work](../../../docs/procedural-length-budget.md). No formal budget approval, few-shot coverage, or formal accuracy claim follows from this measurement.
