# GPU resource audit and preserved failed experiments

2026-10-22. Engineering only. [Report](../../../docs/gpu-resource-audit.md).

- `gpu-lease-audit.json`: actual AutoDL CUDA check. Only our own tiny allocation children were created; foreign CUDA activity and a second managed backend are rejected, owner allocation succeeds.
- `tests.log`: all 114 tests pass on AutoDL. `tests-local.log`: 107 pass and seven optional ML skips.
- `runtime-source.json`: post-run GPU audit source fingerprint. The earlier failed experiments did not have their runtime source/environment frozen.
- `failures/3b-executor/`: all 32 failed public development runs; missing validate.ok/invalid tool schema or invalid JSON. No normalization into success.
- `failures/9b-actor-3b-analyzer/`: all 32 CUDA OOM failures while another 9B process was resident. No model token charges. This is resource contention, not a standalone model-fit result.
- `inputs/`: existing eight public development tasks and separate static references, no new independent test data.
- `failure-replay-audit.json`: all 64 failed records pass tool, metric and budget recomputation. Completed manifest means recording finished, not successful task completion.
- `verification.json`, `checksums.json`: recomputed failure categories and file hashes.

The remote run names containing m4/m5 are not formal milestone completion. No formal M4/M5/M6/M7 completion, human annotation, new training or efficacy claim is made. Do not run CUDA from outdated worktrees alongside protected jobs; cooperative locking cannot prevent arbitrary external programs from starting after a check.
