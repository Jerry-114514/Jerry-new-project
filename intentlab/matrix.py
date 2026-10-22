"""Sequential paired-seed training with a frozen protocol and explicit resume.

Each training child is a separate process. Existing state never causes automatic
relaunch, and interrupted jobs require an explicit --resume after handle checks.
"""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import shutil
import subprocess
import sys
import uuid

from .core import digest
from .protocol import file_hash, read_json, verify
from .report import save_json


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    save_json(temporary, value)
    temporary.replace(path)


@contextmanager
def supervisor_lock(out):
    path = Path(out) / "matrix.lock"
    handle = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump({"pid": os.getpid(), "host": socket.gethostname(),
                   "created_utc": datetime.now(timezone.utc).isoformat()}, stream)
    try:
        yield
    finally:
        path.unlink()


def process_exists(pid):
    if type(pid) is not int or pid < 1:
        raise ValueError("Invalid recorded process ID")
    if os.name == "nt":
        # os.kill(pid, 0) is not a harmless existence probe on Windows.
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x1000, False, pid)
        if handle:
            kernel.CloseHandle(handle)
            return True
        error = ctypes.get_last_error()
        if error == 87:  # ERROR_INVALID_PARAMETER: no process with this PID.
            return False
        raise RuntimeError("Cannot establish recorded Windows process state")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError as exc:
        raise RuntimeError("Cannot establish recorded process state") from exc
    return True


def recover_lock(out):
    path = Path(out) / "matrix.lock"
    previous = read_json(path)
    if previous["host"] != socket.gethostname() or process_exists(previous["pid"]):
        raise RuntimeError("Recorded supervisor is live or on another host; do not recover")
    state_path = Path(out) / "matrix.json"
    if state_path.exists():
        state = read_json(state_path)
        for job in state["jobs"]:
            if job.get("status") == "running" and job.get("pid") is not None:
                if job.get("host") != socket.gethostname() or process_exists(job["pid"]):
                    raise RuntimeError("Recorded training child may still be live")
    archive = path.with_name("matrix.recovered-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f") + ".json")
    path.replace(archive)
    return {"recovered": str(archive), "previous_process_verified_missing": True}


def configurations(lock):
    spec = lock["spec"]
    return [(f"{schedule}-seed-{seed}", dict(spec["training"],
        data=lock["dataset_export"]["root"], model=lock["models"]["analyzer_base"]["path"],
        schedule=schedule, seed=seed)) for seed in spec["seeds"] for schedule in spec["schedules"]]


def validate_result(result, config):
    if result.get("config") != config or not result.get("completed") or result.get("test_deferred") is not True or "test" in result:
        raise ValueError("Completed training must match frozen config and contain no test evaluation")
    if result.get("examples_seen") != config["steps"] * config["batch_size"] * config["accumulation"]:
        raise ValueError("Actual example exposure differs from frozen update budget")
    if not isinstance(result.get("supervised_tokens"), int) or result["supervised_tokens"] < 1:
        raise ValueError("Missing supervised-token accounting")


def training_artifacts(directory):
    directory = Path(directory)
    files = [directory / "latest.pt", *sorted((directory / "model").rglob("*"))]
    if not files[0].is_file() or not any(path.suffix == ".safetensors" for path in files[1:] if path.is_file()):
        raise ValueError("Completed job is missing its checkpoint or exported model")
    return {path.relative_to(directory).as_posix(): file_hash(path) for path in files if path.is_file()}


def paired_training_audit(jobs, out):
    grouped = {}
    for job in jobs:
        if job["status"] != "completed":
            raise ValueError("Paired audit requires all six completed jobs")
        result = read_json(Path(out) / job["name"] / "result.json")
        validate_result(result, job["config"])
        if file_hash(Path(out) / job["name"] / "result.json") != job["result_sha256"]:
            raise ValueError("Result changed after job completion")
        if training_artifacts(Path(out) / job["name"]) != job["artifacts_sha256"]:
            raise ValueError("Training/model artifacts changed after completion")
        grouped.setdefault(job["config"]["seed"], {})[job["config"]["schedule"]] = result
    audit = []
    for seed, pair in grouped.items():
        a, b = pair["cosine"], pair["plateau"]
        for field in ("data_hash", "base_identity", "train_tokens", "supervised_tokens", "sample_exposures"):
            if a[field] != b[field]:
                raise ValueError(f"Seed {seed} paired training differs in {field}")
        audit.append({"seed": seed, "paired_exposure_equal": True, "supervised_tokens": a["supervised_tokens"],
                      "examples_seen": a["examples_seen"]})
    return audit


def run_matrix(lock, out, resume=False, engineering=False, stop_after_updates=None):
    if lock.get("scope") == "engineering" and not engineering:
        raise ValueError("Engineering protocol requires explicit --engineering; it is not formal training")
    if lock.get("scope") not in {"formal", "engineering"}:
        raise ValueError("Unknown frozen protocol scope")
    verify(lock, phase="training")
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    state_path = out / "matrix.json"
    if state_path.exists() and not resume:
        raise ValueError("Existing matrix requires explicit --resume; do not relaunch from stale status")
    if resume and not state_path.exists():
        raise ValueError("No prior matrix to resume")
    planned = configurations(lock)
    with supervisor_lock(out):
        if state_path.exists():
            state = read_json(state_path)
            if state["lock_hash"] != lock["lock_hash"] or [(j["name"], j["config"]) for j in state["jobs"]] != planned:
                raise ValueError("Resume protocol or configurations changed")
        else:
            state = {"kind": "paired_training_matrix", "schema_version": 1, "scope": lock["scope"], "lock_hash": lock["lock_hash"],
                "status": "planned", "jobs": [{"name": name, "config": config, "status": "pending"}
                                               for name, config in planned], "heldout_evaluated": False}
            atomic_json(state_path, state)
        state["status"] = "running"
        atomic_json(state_path, state)
        for job in state["jobs"]:
            directory = out / job["name"]
            previous_status = job["status"]
            if job["status"] == "completed":
                result_path = directory / "result.json"
                validate_result(read_json(result_path), job["config"])
                if file_hash(result_path) != job["result_sha256"]:
                    raise ValueError("Completed result changed; do not silently skip it")
                if training_artifacts(directory) != job["artifacts_sha256"]:
                    raise ValueError("Completed model/checkpoint changed; do not silently skip it")
                continue
            if previous_status == "pending" and directory.exists() and any(directory.iterdir()):
                raise ValueError("Untracked artifacts in a pending job; do not import an external checkpoint")
            if previous_status == "running":
                if job.get("pid") is None or job.get("host") != socket.gethostname() or process_exists(job["pid"]):
                    raise RuntimeError("Training child is live or cannot be established as missing")
            if previous_status == "launching" and Path(job["acknowledgement"]).exists():
                raise RuntimeError("Launch acknowledgement exists without a recorded running PID; inspect process state")
            checkpoint = directory / "latest.pt"
            if previous_status not in {"pending", "launching"} and not checkpoint.exists():
                raise ValueError("Interrupted/failed training has no checkpoint; do not silently start from scratch")
            verify(lock, phase="training")
            config_path = out / (job["name"] + ".config.json")
            if config_path.exists() and read_json(config_path) != job["config"]:
                raise ValueError("Job configuration file changed")
            atomic_json(config_path, job["config"])
            attempt = uuid.uuid4().hex
            ack = out / "attempts" / (attempt + ".ack.json")
            job.update(status="launching", attempt=attempt, acknowledgement=str(ack), pid=None)
            job.setdefault("attempts", []).append({"attempt": attempt, "status": "launching"})
            atomic_json(state_path, state)
            command = [sys.executable, "-m", "intentlab.matrix_worker", "--ack", str(ack),
                       "--config", str(config_path), "--out", str(directory)]
            if checkpoint.exists():
                if not resume:
                    raise ValueError("Interrupted job needs explicit resume and an existing checkpoint")
                command += ["--resume", str(checkpoint)]
            if stop_after_updates is not None:
                command += ["--stop-after", str(stop_after_updates)]
            with (out / (job["name"] + ".log")).open("a", encoding="utf-8") as log:
                child = subprocess.Popen(command, cwd=lock["spec"]["source_root"], stdout=log, stderr=subprocess.STDOUT)
                job.update(status="running", pid=child.pid, host=socket.gethostname(),
                           started_utc=datetime.now(timezone.utc).isoformat())
                job["attempts"][-1].update(status="running", pid=child.pid)
                atomic_json(state_path, state)
                # Worker imports the trainer only after this acknowledgement.
                # A crash between Popen and PID persistence cannot launch an
                # untracked GPU job; a new attempt uses a different ack path.
                atomic_json(ack, {"pid": child.pid, "attempt": attempt})
                try:
                    code = child.wait()
                except BaseException:
                    # Keep the exact child PID and running state. Never infer
                    # child termination solely from a lost supervisor handle.
                    atomic_json(state_path, state)
                    raise
            job["exit_code"] = code
            job["attempts"][-1]["exit_code"] = code
            job["finished_utc"] = datetime.now(timezone.utc).isoformat()
            if code != 0:
                job["status"] = state["status"] = "failed"
                job["attempts"][-1]["status"] = "failed"
                atomic_json(state_path, state)
                return state
            result = read_json(directory / "result.json")
            shutil.copyfile(directory / "result.json", out / "attempts" / (attempt + ".result.json"))
            if not result.get("completed"):
                job["status"] = state["status"] = "interrupted"
                job["attempts"][-1]["status"] = "interrupted"
                atomic_json(state_path, state)
                return state
            validate_result(result, job["config"])
            job.update(status="completed", result_sha256=file_hash(directory / "result.json"))
            job["artifacts_sha256"] = training_artifacts(directory)
            job["attempts"][-1].update(status="completed", result_sha256=job["result_sha256"])
            atomic_json(state_path, state)
        state.update(status="completed", paired_audit=paired_training_audit(state["jobs"], out))
        atomic_json(state_path, state)
        return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--engineering", action="store_true")
    parser.add_argument("--stop-after-updates", type=int)
    parser.add_argument("--recover-lock", action="store_true")
    args = parser.parse_args()
    if args.recover_lock:
        print(json.dumps(recover_lock(args.out), indent=2))
        return
    if args.lock is None:
        parser.error("--lock required")
    result = run_matrix(read_json(args.lock), args.out, args.resume, args.engineering, args.stop_after_updates)
    print(json.dumps({"status": result["status"], "scope": result["scope"],
                      "jobs": [{"name": j["name"], "status": j["status"]} for j in result["jobs"]]}, indent=2))
    if result["status"] == "failed":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
