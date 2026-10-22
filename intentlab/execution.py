"""Development execution on public contracts with a separate offline evaluator.

This entry point is for engineering/development. Confirmatory execution still
needs binding to the complete frozen protocol and reviewed task/reference set.
"""

import argparse
from copy import deepcopy
import json
from pathlib import Path

from .core import canonical, digest, replay_events
from .execution_analysis import ContractRuleActor, analyze_execution, execution_scope
from .execution_data import load_execution_tasks, load_references, validate_tasks
from .execution_oracle import evaluate_execution
from .model_backend import LanguageModelActor, SchemaLanguageModelAnalyzer
from .model_pool import LocalModelPool
from .report import save_experiment, save_json
from .runner import run_task


def replay_execution(tasks, references, records):
    by_id = {task["id"]: task for task in tasks}
    checked = 0
    for record in records:
        if record["task_id"] not in by_id:
            raise ValueError("Unknown replay task")
        task = by_id[record["task_id"]]
        state = replay_events(task, record["final_state"]["events"])
        if canonical(state.files) != canonical(record["final_state"]["files"]):
            raise ValueError("Replayed artifact differs from committed files")
        if evaluate_execution(task, state, references[task["id"]]) != record["metrics"]:
            raise ValueError("Replayed offline metrics differ")
        checked += 1
    return {"replayed": checked, "committed_tools_and_final_metrics_verified": True}


def run_execution(tasks, references, out, pool=None, policies=("fixed-full", "dynamic"), max_repairs=3,
                  hard_guard=True, redact_events=False, rule_actor=False, max_tool_steps=3, actor_envelope="extract"):
    validate_tasks(tasks)
    if not tasks or set(references) != {task["id"] for task in tasks}:
        raise ValueError("Exactly one offline reference per selected task required")
    if not policies or any(policy not in {"none", "fixed", "fixed-full", "dynamic"} for policy in policies):
        raise ValueError("Unknown execution policy")
    if type(max_repairs) is not int or not 0 <= max_repairs <= 20:
        raise ValueError("Repair count must be between zero and twenty")
    if type(max_tool_steps) is not int or not 1 <= max_tool_steps <= 8:
        raise ValueError("Tool feedback steps must be between one and eight")
    if actor_envelope not in {"strict", "extract"}:
        raise ValueError("Unknown actor envelope policy")
    if any(task["split"] not in {"train", "validation"} for task in tasks):
        raise ValueError("Development execution cannot expose test/OOD tasks; use the future frozen confirmatory entry")
    if not rule_actor and (pool is None or "actor" not in pool.paths):
        raise ValueError("Choose an actual actor model or explicit engineering rule_actor")
    if rule_actor and pool is not None and "actor" in pool.paths:
        raise ValueError("Do not configure both rule and model actors")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    manifest = {"kind": "public_contract_development_execution", "scope": "development", "status": "running",
        "actor": "local_model" if pool else "scripted", "executor_is_language_model": not rule_actor,
        "analyzer": "schema_local_model" if pool and "analyzer" in pool.paths else "public_rule",
        "task_hash": digest(tasks), "offline_reference_hash": digest(references), "policies": list(policies),
        "max_repairs": max_repairs, "hard_guard_enabled": hard_guard, "redact_events": redact_events,
        "max_tool_steps": max_tool_steps,
        "actor_envelope": actor_envelope,
        "source_task_groups": len({task["source_task_id"] for task in tasks}),
        "model_paths": dict(pool.paths) if pool else None,
        "warning": "Unreviewed development contracts; not an independent human benchmark or confirmatory result."}
    save_json(out / "manifest.json", manifest)
    results = []
    # This closure is used only after interaction ends; it is never supplied to
    # the actor, analyzer, public rule solver or repair acceptance function.
    def judge(task, state):
        return evaluate_execution(task, state, references[task["id"]])
    try:
        with (out / "runs.jsonl").open("w", encoding="utf-8", newline="\n") as stream:
            for policy in dict.fromkeys(policies):
                for task in tasks:
                    if pool:
                        pool.reset()
                    actor = ContractRuleActor() if rule_actor else LanguageModelActor(pool.role("actor"), envelope_mode=actor_envelope)
                    analyzer = SchemaLanguageModelAnalyzer(pool.role("analyzer")) if pool and "analyzer" in pool.paths else analyze_execution
                    result = run_task(deepcopy(task), actor, policy, max_repairs, redact_events,
                        analyzer=analyzer, hard_guard=hard_guard, evaluator=judge, scope_selector=execution_scope,
                        max_tool_steps=max_tool_steps)
                    result["source_task_id"] = task["source_task_id"]
                    result["analyzer_errors"] = analyzer.errors if hasattr(analyzer, "errors") else []
                    if pool:
                        result["model_pool"] = pool.snapshot()
                    results.append(result)
                    stream.write(canonical(result) + "\n")
                    stream.flush()
        manifest["status"] = "completed"
        summary = save_experiment(results, out, manifest)
        # Report all-task rates as well as the subset that remained historically
        # feasible after initial execution. Never discard the other stratum.
        strata = {}
        for policy in dict.fromkeys(policies):
            group = [row for row in results if row["policy"] == policy]
            feasible = [row for row in group if row["feasible_at_repair_start"]]
            strata[policy] = {"all_runs": len(group), "feasible_runs": len(feasible),
                "initially_irreversible_runs": len(group) - len(feasible),
                "feasible_compliant_success_rate": sum(row["metrics"]["compliant_success"] for row in feasible) / len(feasible) if feasible else None,
                "repair_introduced_hard_violation_runs": sum(bool(row["repair_introduced_hard_violations"]) for row in group),
                "warning": "Development source groups are declared, not independently certified tasks."}
        save_json(out / "strata.json", strata)
        return {"summary": summary, "strata": strata, "manifest": manifest}
    finally:
        if pool:
            pool.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True, help="Offline only; never sent to a model")
    parser.add_argument("--out", type=Path, required=True)
    actor = parser.add_mutually_exclusive_group(required=True)
    actor.add_argument("--actor-model", type=Path)
    actor.add_argument("--rule-actor", action="store_true")
    parser.add_argument("--analyzer-model", type=Path)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--token-budget", type=int, default=16384)
    parser.add_argument("--context-limit", type=int, default=4096)
    parser.add_argument("--max-repairs", type=int, default=3)
    parser.add_argument("--max-tool-steps", type=int, default=3)
    parser.add_argument("--actor-envelope", choices=["strict", "extract"], default="extract")
    parser.add_argument("--policies", nargs="+", default=["fixed-full", "dynamic"])
    parser.add_argument("--disable-hard-guard", action="store_true")
    parser.add_argument("--redact-events", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    tasks = load_execution_tasks(args.tasks)
    references = load_references(args.references, tasks)
    if args.limit is not None:
        if args.limit < 1:
            parser.error("--limit must be positive")
        tasks = tasks[:args.limit]
        references = {task["id"]: references[task["id"]] for task in tasks}
    pool = None
    paths = {role: path for role, path in (("actor", args.actor_model), ("analyzer", args.analyzer_model)) if path}
    if paths:
        pool = LocalModelPool(paths, args.device, args.max_new_tokens, args.token_budget, context_limit=args.context_limit)
    result = run_execution(tasks, references, args.out, pool, args.policies, args.max_repairs,
                           not args.disable_hard_guard, args.redact_events, args.rule_actor, args.max_tool_steps, args.actor_envelope)
    print(json.dumps({"summary": result["summary"], "strata": result["strata"]}, indent=2))


if __name__ == "__main__":
    main()
