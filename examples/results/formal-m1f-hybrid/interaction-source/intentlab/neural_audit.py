"""Run a reproducible real-LM training/resume/inference audit and save evidence."""

import argparse
import json
from pathlib import Path

from .actors import ScriptedActor
from .core import load_tasks
from .model_backend import LanguageModelAnalyzer, LocalBackend
from .neural import dependencies, train_neural
from .report import save_experiment, save_json
from .runner import run_task


def audit(data, tasks, out, steps=12):
    torch, _ = dependencies()
    configuration = {"data": str(data), "model": "tiny", "revision": None, "mode": "full", "device": "cpu",
        "schedule": "cosine", "steps": steps, "eval_every": max(1, steps // 3), "batch_size": 1,
        "accumulation": 2, "max_length": 2048, "lr": 0.001, "minimum_lr": 0.000005,
        "rank": 4, "alpha": 8, "seed": 0, "limit": 8, "threads": 2}
    records = []
    for schedule in ("cosine", "plateau"):
        config = dict(configuration, schedule=schedule)
        full_path, resumed_path = out / schedule, out / (schedule + "-resumed")
        full = train_neural(config, full_path)
        train_neural(config, resumed_path, stop_after=max(1, steps // 2))
        resumed = train_neural(config, resumed_path, resume=resumed_path / "latest.pt")
        a = torch.load(full_path / "latest.pt", map_location="cpu", weights_only=True)
        b = torch.load(resumed_path / "latest.pt", map_location="cpu", weights_only=True)
        equal = all(torch.equal(t, b["weights"][k]) for k, t in a["weights"].items())
        if not equal or full["history"] != resumed["history"]:
            raise ValueError("Resume equivalence audit failed")
        records.append({"schedule": schedule, "bitwise_resume_equivalent": equal,
                        "validation_loss": full["history"][-1]["validation"]["loss"], "test": full["test"],
                        "trainable_parameters": full["trainable_parameters"]})
    adapter = train_neural(dict(configuration, mode="lora"), out / "lora")
    backend = LocalBackend(out / "lora/model", max_new_tokens=12, token_budget=64)
    reply = backend.complete("JSON:\n")
    # Actual model inference in the runner, not a mocked HTTP response.
    backend = LocalBackend(out / "cosine/model", max_new_tokens=64, token_budget=4096)
    backend.torch.set_num_threads(2)
    runs = []
    for task in [t for t in load_tasks(tasks) if t["split"] == "test"][:2]:
        backend.reset()
        analyzer = LanguageModelAnalyzer(backend)
        result = run_task(task, ScriptedActor(), "dynamic", max_repairs=1, analyzer=analyzer)
        result["model_usage"] = dict(backend.usage)
        result["model_generations"] = list(backend.generations)
        result["analyzer_errors"] = analyzer.errors
        runs.append(result)
    save_experiment(runs, out / "inference", {"actor": "local_model", "role": "analyzer",
        "warning": "Tiny randomly initialized LM smoke; JSON failures are measured, not hidden."})
    report = {"kind": "real_causal_lm_infrastructure_audit", "schedules": records,
        "lora_parameters": adapter["trainable_parameters"], "lora_total_parameters": adapter["parameters"],
        "lora_generation_usage": reply["usage"], "inference_calls": sum(r["model_usage"]["calls"] for r in runs),
        "inference_json_errors": sum(len(r["analyzer_errors"]) for r in runs),
        "warning": "Validates real gradients, resume, adapter loading and model invocation; not pretrained-LLM efficacy or 5090 throughput."}
    save_json(out / "audit.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/sft"))
    parser.add_argument("--tasks", type=Path, default=Path("data/tasks.json"))
    parser.add_argument("--out", type=Path, default=Path("runs/neural-audit"))
    parser.add_argument("--steps", type=int, default=12)
    args = parser.parse_args()
    print(json.dumps(audit(args.data, args.tasks, args.out, args.steps), indent=2))


if __name__ == "__main__":
    main()
