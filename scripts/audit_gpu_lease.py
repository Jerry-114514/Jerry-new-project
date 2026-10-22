"""Linux/AutoDL integration audit using our own tiny CUDA child only.

No training or 9B weights are loaded. External experiment processes are never
stopped; the audit refuses to start if CUDA is occupied.
"""

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.gpu_lease import GpuBusy, GpuLease, compute_processes, ensure_gpu_lease


def child_process(program, *args):
    child = subprocess.Popen([sys.executable, "-u", "-c", program, *args], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return child


def finish(child):
    if child.poll() is None:
        child.communicate("done\n", timeout=20)
    else:
        child.communicate(timeout=20)
    if child.returncode != 0:
        raise RuntimeError("Audit child exited unsuccessfully")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Choose a fresh output file")
    if compute_processes():
        raise GpuBusy("An external CUDA process is active; no child was started")
    evidence = {}
    legacy = child_process("import os,sys,torch; t=torch.empty(1,device='cuda'); print(os.getpid(),flush=True); sys.stdin.readline()")
    try:
        pid = int(legacy.stdout.readline().strip())
        if pid not in compute_processes():
            raise RuntimeError("nvidia-smi did not observe our live CUDA child")
        try:
            with GpuLease():
                raise AssertionError("An uncooperative CUDA process was not blocked")
        except GpuBusy as exc:
            evidence["legacy_cuda_child_refused"] = {"pid": pid, "message": str(exc)}
    finally:
        finish(legacy)
    lease = ensure_gpu_lease()
    # Import a backend to verify the public CUDA constructor, before ML loading.
    contender = subprocess.run([sys.executable, "-c",
        "from intentlab.model_backend import LocalBackend; from intentlab.gpu_lease import GpuBusy; import sys\n"
        "try: LocalBackend('this-model-must-not-load','cuda')\n"
        "except GpuBusy as e: print(str(e)); sys.exit(0)\n"
        "raise SystemExit('contending model unexpectedly loaded')"], capture_output=True, text=True, timeout=20)
    if contender.returncode != 0:
        raise RuntimeError(contender.stderr or contender.stdout)
    evidence["managed_second_backend_refused"] = contender.stdout.strip()
    import torch
    t = torch.empty(1, device="cuda")
    ensure_gpu_lease()  # Own CUDA PID is allowed; live reuse must not self-block.
    evidence["owner_cuda_allocation_and_reuse"] = True
    evidence["owner_pid"] = os.getpid()
    evidence["lock_file"] = str(lease.path)
    evidence["note"] = "Only audit-owned children were started/stopped. No models or formal training; kernel-crash recovery separately covered by tests."
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(evidence, indent=2))
    # Process-scoped lease stays held until exit, including resident CUDA state.


if __name__ == "__main__":
    main()
