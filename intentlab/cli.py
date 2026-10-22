import argparse
import json
import platform
from pathlib import Path

from . import __version__
from .actors import HTTPActor, ScriptedActor
from .core import digest, load_tasks, replay_events
from .fixtures import build_tasks, export_diagnostics
from .learning import read_examples, train
from .report import save_experiment, save_json
from .runner import run_task
from .oracle import evaluate


def main(argv=None):
    parser = argparse.ArgumentParser(description="Evidence-driven repair experiment harness")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-data")
    build.add_argument("--tasks", type=Path, default=Path("data/tasks.json"))
    build.add_argument("--out", type=Path, default=Path("runs/data"))
    build.add_argument("--count", type=int, default=40)
    build.add_argument("--overwrite", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("--tasks", type=Path, default=Path("data/tasks.json"))
    run.add_argument("--out", type=Path, default=Path("runs/demo"))
    run.add_argument("--policies", nargs="+", choices=["none", "fixed", "fixed-full", "dynamic"], default=["none", "fixed", "fixed-full", "dynamic"])
    run.add_argument("--repeats", type=int, default=2)
    run.add_argument("--max-repairs", type=int, default=3)
    run.add_argument("--redact-events", action="store_true")
    run.add_argument("--disable-hard-guard", action="store_true",
                     help="Independent guard ablation in the virtual environment; model gate remains active")
    run.add_argument("--actor-url", default=None)
    run.add_argument("--model-path", type=Path, help="Local saved model for real language-model inference")
    run.add_argument("--actor-model-path", type=Path, help="Fixed local execution model, separate from analyzer")
    run.add_argument("--analyzer-model-path", type=Path, help="Local diagnostic model, separate from actor")
    run.add_argument("--analyzer-interface", choices=["legacy", "schema"], default="legacy")
    run.add_argument("--model-role", choices=["actor", "analyzer", "both"], default="analyzer")
    run.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    run.add_argument("--max-new-tokens", type=int, default=256)
    run.add_argument("--token-budget", type=int, default=20000)
    run.add_argument("--limit", type=int, help="Limit selected tasks for a local model smoke run")
    run.add_argument("--risk-model", type=Path, help="Optional train-baseline model for target ranking only")
    run.add_argument("--split", choices=["all", "train", "validation", "test"], default="all")
    learning = sub.add_parser("train-baseline")
    learning.add_argument("--data", type=Path, default=Path("runs/data/diagnostic_views.jsonl"))
    learning.add_argument("--out", type=Path, default=Path("runs/training"))
    learning.add_argument("--epochs", type=int, default=24)
    learning.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    replay = sub.add_parser("replay")
    replay.add_argument("--tasks", type=Path, default=Path("data/tasks.json"))
    replay.add_argument("--records", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "build-data":
        if args.count < 12:
            parser.error("Use at least 12 fixtures for all operation families")
        if args.tasks.exists() and not args.overwrite:
            tasks = load_tasks(args.tasks)
        else:
            tasks = build_tasks(args.count)
            save_json(args.tasks, tasks)
        export_diagnostics(tasks, args.out)
        save_json(args.out / "manifest.json", {"type": "synthetic_diagnostic_fixture", "tasks": len(tasks),
                  "trajectories": len(tasks) * 4, "views": len(tasks) * 8, "task_hash": digest(tasks),
                  "split_rule": "train=dedupe/filter/project/validate; validation=aggregate; test=split",
                  "warning": "Code-generated smoke data, not independently human-annotated benchmark."})
        print(json.dumps({"tasks": len(tasks), "out": str(args.out)}))
    elif args.command == "run":
        if args.repeats < 1 or not 0 <= args.max_repairs <= 20:
            parser.error("Invalid repeat or repair count")
        all_tasks = load_tasks(args.tasks)
        tasks = [t for t in all_tasks if args.split == "all" or t["split"] == args.split]
        if args.limit is not None:
            if args.limit < 1:
                parser.error("Task limit must be positive")
            tasks = tasks[:args.limit]
        if not tasks:
            parser.error("No tasks in selected split")
        records = []
        risk_weights = None
        if args.risk_model:
            risk_model = json.loads(args.risk_model.read_text(encoding="utf-8"))
            if risk_model.get("model_type") != "logistic_rule_signal_smoke_baseline":
                parser.error("Unsupported risk model type")
            risk_weights = risk_model["weights"]
        backend, pool = None, None
        separate = args.actor_model_path is not None or args.analyzer_model_path is not None
        if separate:
            if args.model_path or args.actor_url:
                parser.error("Dedicated role paths cannot be combined with --model-path or --actor-url")
            from .model_backend import LanguageModelActor, LanguageModelAnalyzer, SchemaLanguageModelAnalyzer
            from .model_pool import LocalModelPool
            paths = {role: path for role, path in (("actor", args.actor_model_path),
                                                  ("analyzer", args.analyzer_model_path)) if path is not None}
            pool = LocalModelPool(paths, args.device, args.max_new_tokens, args.token_budget)
        if args.model_path:
            if args.actor_url:
                parser.error("Choose either a local model or HTTP actor")
            from .model_backend import LocalBackend, LanguageModelActor, LanguageModelAnalyzer, SchemaLanguageModelAnalyzer
            backend = LocalBackend(args.model_path, args.device, args.max_new_tokens, args.token_budget)
        for policy in dict.fromkeys(args.policies):
            for repetition in range(args.repeats):
                for task in tasks:
                    actor = HTTPActor(args.actor_url) if args.actor_url else ScriptedActor()
                    analyzer = None
                    analyzer_type = None
                    if backend or pool:
                        analyzer_type = SchemaLanguageModelAnalyzer if args.analyzer_interface == "schema" else LanguageModelAnalyzer
                    if pool:
                        pool.reset()
                        if "actor" in pool.paths:
                            actor = LanguageModelActor(pool.role("actor"))
                        if "analyzer" in pool.paths:
                            analyzer = analyzer_type(pool.role("analyzer"))
                    if backend:
                        backend.reset()
                        if args.model_role in {"actor", "both"}:
                            actor = LanguageModelActor(backend)
                        if args.model_role in {"analyzer", "both"}:
                            analyzer = analyzer_type(backend)
                    result = run_task(task, actor, policy, args.max_repairs, args.redact_events, analyzer, risk_weights,
                                      hard_guard=not args.disable_hard_guard)
                    if backend:
                        result["model_usage"] = dict(backend.usage)
                        result["model_generations"] = list(backend.generations)
                        result["analyzer_errors"] = analyzer.errors if analyzer else []
                        result["shared_token_ledger"] = backend.ledger.snapshot()
                    if pool:
                        result["model_pool"] = pool.snapshot()
                        result["analyzer_errors"] = analyzer.errors if analyzer else []
                    result["repetition"] = repetition
                    records.append(result)
        manifest = {"version": __version__, "python": platform.python_version(), "actor": "local_model" if backend or pool else "http" if args.actor_url else "scripted",
                    "task_hash": digest(all_tasks), "policies": args.policies, "repeats": args.repeats,
                    "max_repairs": args.max_repairs, "redact_events": args.redact_events, "split": args.split,
                    "hard_guard_enabled": not args.disable_hard_guard,
                    "model_role": list(pool.paths) if pool else args.model_role if backend else None,
                    "model_paths": pool.paths if pool else {"shared": str(args.model_path)} if backend else None,
                    "executor_is_language_model": ("actor" in pool.paths if pool else
                                                    bool(backend and args.model_role in {"actor", "both"})),
                    "analyzer_interface": args.analyzer_interface if backend or pool else None,
                    "token_budget": args.token_budget if backend or pool else None,
                    "risk_model_hash": digest(risk_weights) if risk_weights else None,
                    "warning": ("Greedy model repeats are not independent statistical samples." if backend or pool else
                                "HTTP repeats require provider configuration to assess independence." if args.actor_url else
                                "Scripted repeats are duplicates, not independent statistical samples.")}
        if pool:
            pool.close()
        if backend:
            backend.close()
        print(json.dumps(save_experiment(records, args.out, manifest), indent=2))
    elif args.command == "replay":
        tasks = {t["id"]: t for t in load_tasks(args.tasks)}
        count = 0
        for line in args.records.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            task = tasks[record["task_id"]]
            saved = record.get("final_state", record)
            state = replay_events(task, saved["events"])
            if state.files != saved["files"]:
                raise ValueError("Replayed artifacts differ from recorded artifacts")
            truth = record.get("metrics", record.get("truth"))
            if truth is not None and evaluate(task, state) != truth:
                raise ValueError("Replayed evaluation differs from recorded metrics")
            count += 1
        print(json.dumps({"replayed": count, "artifacts_and_metrics_match": True}))
    else:
        examples = read_examples(args.data)
        summary = []
        for schedule in ("cosine", "plateau"):
            for seed in args.seeds:
                model = train(examples, schedule, seed, args.epochs)
                save_json(args.out / f"{schedule}-seed-{seed}.json", model)
                summary.append({"schedule": schedule, "seed": seed, "test": model["test"],
                                "best_validation_loss": model["best_validation_loss"], "lr_reductions": model["lr_reductions"]})
        save_json(args.out / "summary.json", {"type": "logistic_rule_signal_smoke_baseline", "runs": summary,
                    "data_hash": digest(args.data.read_text(encoding="utf-8")),
                    "warning": "Not QLoRA, not a learned LLM actor, and not evidence of scheduler innovation."})
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
