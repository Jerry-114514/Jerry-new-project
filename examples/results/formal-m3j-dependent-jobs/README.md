# M3j: live one-shot dependent development jobs

Launch snapshot records a verified running follow-up process waiting on the known live baseline inference PID and start ticks. This is not completion evidence. The worker starts scoring only after the dependency exits and all three 600-output conditions are complete. It then validates the preselected 32-task collection and official model assets, runs one actor-only development collection, and labels its preserved trajectories offline.

Source remains pinned to the clean b4a757a checkout throughout. Exact scorer/selection hashes and normalized intake-code hash are recorded; follow-up code is in scripts/run_procedural_followup.py. It never restarts or overwrites a failed stage. PID identity changes, partial outputs, source changes, and binding changes stop successors. Six-hour wait timeout does not kill or replace the dependency.

Five focused tests and 243-test local suite (14 optional ML skips) pass. A real queue process is waiting; no new collection or scoring completion is claimed. Raw data and eventual logs remain private. See [phase rules and remaining work](../../../docs/dependent-development-jobs.md).
