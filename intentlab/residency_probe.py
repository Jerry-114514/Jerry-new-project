"""Development-only equivalence and cost probe; never scores task correctness."""

import argparse
from contextlib import contextmanager
from copy import deepcopy
import json
from pathlib import Path
import time

from .core import digest, initial_state
from .execution_data import load_execution_tasks
from .model_backend import LanguageModelActor, SchemaLanguageModelAnalyzer
from .model_pool import LocalModelPool
from .protocol import file_hash, source_git
from .report import save_json
from .shared_role_backend import compatible_base_adapter


def development_prompts(tasks):
    if len(tasks) < 2 or any(t["split"] not in {"train", "validation"} for t in tasks):
        raise ValueError("Probe requires at least two development tasks and no heldout tasks")
    chosen = sorted(tasks, key=lambda t: t["id"])[:2]
    if len({t["id"] for t in chosen}) != 2:
        raise ValueError("Distinct development tasks required")
    batches = []
    for task in chosen:
        captured = []
        class Capture:
            def complete(self, prompt):
                captured.append(prompt)
                return {"text": '{"actions":[],"done":true}', "usage": {}}
        state = initial_state(task)
        LanguageModelActor(Capture()).propose(task, state, "initial")
        SchemaLanguageModelAnalyzer(Capture())(task, state)
        batches.append({"task_id": task["id"], "split": task["split"], "calls":
            [("actor", captured[0]), ("analyzer", captured[1]), ("actor", captured[0])]})
    return batches


def without_timing(snapshot):
    value = deepcopy(snapshot)
    value["events"] = [{k: v for k, v in row.items() if k != "elapsed_seconds"} for row in value["events"]]
    return value


@contextmanager
def capture_tokens(backend):
    """Observe the actual returned token tensor, including special tokens."""
    original = backend.model.generate
    had_override = "generate" in vars(backend.model)
    outputs = []
    def generate(*args, **kwargs):
        result = original(*args, **kwargs)
        outputs.append(result.tolist())
        return result
    backend.model.generate = generate
    try:
        yield outputs
    finally:
        # Do not retain a bound method on the module after the probe call.
        if had_override:
            backend.model.generate = original
        else:
            del backend.model.generate


def asset_hashes(paths):
    return {role: {p.relative_to(Path(root)).as_posix(): file_hash(p)
                   for p in sorted(Path(root).rglob("*")) if p.is_file()} for role, root in paths.items()}


def run_probe(paths, tasks, out, device="cuda", max_new_tokens=128, token_budget=49152, context_limit=17408):
    batches = development_prompts(load_execution_tasks(tasks))
    if not compatible_base_adapter(paths):
        raise ValueError("Probe requires the same plain local base plus compatible LoRA")
    if device == "cuda":
        from .gpu_lease import ensure_gpu_lease
        ensure_gpu_lease()  # Refuse competing experiments before creating an attempt.
    from .neural import dependencies
    torch, _ = dependencies()
    out = Path(out)
    out.mkdir(mode=0o700, parents=True, exist_ok=False)
    status = {"kind": "development_residency_probe", "status": "running", "device": device,
        "formal_evaluation": False, "references_read": False, "heldout_read": False,
        "source": source_git(Path(__file__).resolve().parents[1]), "paths": {k: str(Path(v).resolve()) for k, v in paths.items()},
        "task_file_sha256": file_hash(tasks), "selected_tasks": [{k: b[k] for k in ("task_id", "split")} for b in batches],
        "prompt_hash": digest(batches), "max_new_tokens": max_new_tokens, "token_budget": token_budget,
        "context_limit": context_limit, "modes": {}, "warning": "Bounded engineering check, not universal equivalence or efficacy."}
    save_json(out / "status.json", status)
    pool = None
    try:
        before = asset_hashes(paths)
        save_json(out / "asset-hashes.json", before)
        for mode in ("cold-task-reload", "shared-condition-resident"):
            if device == "cuda":
                torch.cuda.reset_peak_memory_stats()
            started = time.perf_counter()
            pool = LocalModelPool(paths, device=device, max_new_tokens=max_new_tokens, token_budget=token_budget,
                                  context_limit=context_limit, share_base_adapter=mode == "shared-condition-resident")
            records = []
            for batch in batches:
                pool.reset()
                calls = []
                for role, prompt in batch["calls"]:
                    # Initialization is an actual model load and is timed by the pool.
                    # Intercept LocalBackend.complete only to observe its model.generate.
                    # The normal pool still controls loading, reset and shared accounting.
                    from unittest.mock import patch
                    from .model_backend import LocalBackend
                    original_complete = LocalBackend.complete
                    token_rows = []
                    def observed(backend, text, role="model"):
                        with capture_tokens(backend) as raw:
                            response = original_complete(backend, text, role=role)
                        token_rows.extend(raw)
                        return response
                    with patch.object(LocalBackend, "complete", observed):
                        reply = pool.complete(role, prompt)
                    if len(token_rows) != 1:
                        raise ValueError("Exactly one observed generation per call required")
                    calls.append({"role": role, "prompt_hash": digest(prompt), "reply": reply, "token_ids": token_rows[0]})
                    with (out / (mode + "-calls.jsonl")).open("a", encoding="utf-8") as stream:
                        stream.write(json.dumps({"task_id": batch["task_id"], **calls[-1]}, ensure_ascii=False) + "\n")
                records.append({"task_id": batch["task_id"], "calls": calls, "pool": pool.snapshot()})
                save_json(out / (mode + ".json"), records)
                if mode == "cold-task-reload":
                    pool.close()
            pool.close(); pool = None
            elapsed = time.perf_counter() - started
            status["modes"][mode] = {"seconds_including_loading": elapsed,
                "load_count": sum(len(r["pool"]["model_loads"]) for r in records),
                "loading_seconds": sum(x["seconds"] for r in records for x in r["pool"]["model_loads"]),
                "peak_allocated_bytes": torch.cuda.max_memory_allocated() if device == "cuda" else None,
                "peak_reserved_bytes": torch.cuda.max_memory_reserved() if device == "cuda" else None}
            save_json(out / "status.json", status)
        baseline = json.loads((out / "cold-task-reload.json").read_text(encoding="utf-8"))
        shared = json.loads((out / "shared-condition-resident.json").read_text(encoding="utf-8"))
        status["exact_outputs_and_tokens_equal"] = all(a["calls"] == b["calls"] for a, b in zip(baseline, shared))
        status["accounting_equal_except_time"] = all(without_timing(a["pool"]["shared_token_ledger"]) ==
            without_timing(b["pool"]["shared_token_ledger"]) for a, b in zip(baseline, shared))
        status["assets_unchanged"] = asset_hashes(paths) == before
        if not all(status[k] for k in ("exact_outputs_and_tokens_equal", "accounting_equal_except_time", "assets_unchanged")):
            raise ValueError("Residency probe differs; do not adopt as a transparent optimization")
        if status["modes"]["shared-condition-resident"]["load_count"] != 1:
            raise ValueError("Expected exactly one shared resident load across both development tasks")
        status["status"] = "completed"
    except BaseException as exc:
        status.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        if pool is not None:
            save_json(out / "failure-pool.json", pool.snapshot())
        raise
    finally:
        if pool is not None:
            pool.close()
        save_json(out / "status.json", status)
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("actor", "analyzer", "tasks", "out"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    parser.add_argument("--max-new-tokens", type=int, default=128)
    args = parser.parse_args()
    result = run_probe({"actor": args.actor, "analyzer": args.analyzer}, args.tasks, args.out,
                       device=args.device, max_new_tokens=args.max_new_tokens)
    print(json.dumps({k: result[k] for k in ("status", "exact_outputs_and_tokens_equal", "accounting_equal_except_time")}))


if __name__ == "__main__":
    main()
