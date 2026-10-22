"""Frozen P1-P4 interactions, followed by separate static-reference scoring."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import time

from .core import canonical, digest, replay_events
from .diagnostic_protocol import claim, public_inputs, seal_files, verify_reveal
from .execution_analysis import HybridExecutionAnalyzer, execution_scope
from .execution_audit import audit_intensity, audit_ledger, audit_records
from .execution_data import load_references
from .execution_oracle import evaluate_execution
from .execution_protocol import execution_condition_map
from .formal_data import read_jsonl
from .model_backend import LanguageModelActor, SchemaLanguageModelAnalyzer
from .model_pool import LocalModelPool
from .protocol import file_hash, read_json
from .report import save_json
from .runner import run_task


def preflight(protocol, binding, predictions, diagnostic_reveal, engineering):
    receipt = verify_reveal(protocol, binding, predictions, diagnostic_reveal, engineering)
    _, _, indexed = public_inputs(protocol)
    tasks = sorted(indexed.values(), key=lambda row: row["id"])
    return receipt, tasks


def paths_for(binding):
    return {role: binding["models"][role]["path"] for role in ("actor", "analyzer")}


def runtime_plan(protocol, binding, predictions, diagnostic_reveal, engineering, ablation_context=None):
    settings = protocol["spec"]["execution"]["settings"]
    if ablation_context is None:
        return execution_condition_map(settings), {}
    if not isinstance(ablation_context, tuple) or len(ablation_context) != 2:
        raise ValueError("Ablations require the frozen M6 interaction and scoring directories")
    receipt = verify_scoring(protocol, binding, predictions, diagnostic_reveal,
        ablation_context[0], ablation_context[1], engineering)
    if "controller_binding" not in protocol:
        raise ValueError("Ablations require a pre-frozen development selection/controller binding")
    from .controller_plan import condition_map
    controller = protocol["controller_binding"]
    conditions = condition_map(controller, settings)
    baseline = conditions["dynamic-k"]["intensity"]
    return conditions, {"execution_receipt_hash": receipt["receipt_hash"], "controller_binding_hash": digest(controller),
        "strong_fixed_condition": "fixed-k-" + str(controller["selection"]["selected_k"]),
        "parameter_noop_controls": [name for name, config in conditions.items()
            if name.startswith("dynamic-k-") and config["intensity"] == baseline]}


def condition_intensity(config, settings):
    return config.get("intensity", settings["intensity"]) if config["policy"] in {"fixed-k", "dynamic-k"} else None


def interact(protocol, binding, predictions, diagnostic_reveal, out, engineering=False, pool_factory=None, _ablation_context=None):
    if pool_factory is not None and protocol["scope"] != "engineering":
        raise ValueError("Injected execution pools are forbidden in formal runs")
    receipt, tasks = preflight(protocol, binding, predictions, diagnostic_reveal, engineering)
    conditions, upstream = runtime_plan(protocol, binding, predictions, diagnostic_reveal, engineering, _ablation_context)
    prefix = "ablation" if _ablation_context is not None else "execution"
    out = Path(out)
    if out.exists():
        raise ValueError("Choose a fresh frozen execution directory")
    attempt = claim(protocol, prefix + "-interactions", out)
    out.mkdir(parents=True, exist_ok=False)
    settings, budgets = protocol["spec"]["execution"]["settings"], protocol["spec"]["budgets"]
    manifest = {"kind": "frozen_" + prefix + "_interactions", "schema_version": 1, "scope": protocol["scope"], "upstream": upstream,
        "status": "running", "protocol_hash": protocol["lock_hash"], "model_binding_hash": binding["binding_hash"],
        "diagnostic_receipt_hash": receipt["receipt_hash"], "settings_hash": digest(settings), "conditions": conditions,
        "model_paths": paths_for(binding), "task_hash": digest(tasks), "ordered_task_ids": [task["id"] for task in tasks],
        "offline_references_opened": False, "injected_pool": pool_factory is not None, "claim": attempt,
        "budget_unit": "shared actor/analyzer token ledger per condition/task; all starts cold",
        "warning": "Sealed interactions are not offline task success or formal-data certification."}
    save_json(out / "manifest.json", manifest)
    pool, started = None, time.perf_counter()
    try:
        pool = (pool_factory or LocalModelPool)(paths_for(binding), device=protocol["spec"]["training"]["device"],
            max_new_tokens=budgets["max_new_tokens"], token_budget=budgets["token_budget"], context_limit=budgets["context_limit"])
        with (out / "interactions.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
            for condition, config in conditions.items():
                for task in tasks:
                    manifest.update(active_condition=condition, active_task=task["id"])
                    save_json(out / "manifest.json", manifest)
                    pool.reset()
                    actor = LanguageModelActor(pool.role("actor"), envelope_mode=settings["actor_envelope"])
                    analyzer = SchemaLanguageModelAnalyzer(pool.role("analyzer"))
                    if settings["analyzer_mode"] == "hybrid":
                        analyzer = HybridExecutionAnalyzer(analyzer)
                    try:
                        # The runner expects a post-loop evaluator. An empty
                        # callback exposes no truth; real evaluation is a later
                        # process after every P1-P4 interaction has been sealed.
                        row = run_task(deepcopy(task), actor, config["policy"], budgets["max_repairs"], settings["redact_events"],
                            analyzer=analyzer, hard_guard=config["hard_guard"], evaluator=lambda task, state: {},
                            scope_selector=execution_scope, max_tool_steps=settings["max_tool_steps"],
                            intensity_config=condition_intensity(config, settings))
                        for key in ("metrics", "initial_metrics", "feasible_at_repair_start", "repair_introduced_hard_violations"):
                            row.pop(key)
                        row.update(condition=condition, source_task_id=task["source_task_id"], offline_metrics_pending=True,
                            analyzer_mode=settings["analyzer_mode"], analyzer_errors=analyzer.errors, model_pool=pool.snapshot())
                        if settings["analyzer_mode"] == "hybrid":
                            row["analyzer_decisions"] = deepcopy(analyzer.decisions)
                        stream.write(canonical(row) + "\n")
                        stream.flush()
                    finally:
                        # Equal cold starts avoid condition-dependent residency
                        # hiding model reload cost. No simultaneous role models.
                        pool.close()
        again, current = preflight(protocol, binding, predictions, diagnostic_reveal, engineering)
        final_conditions, final_upstream = runtime_plan(protocol, binding, predictions, diagnostic_reveal, engineering, _ablation_context)
        if digest(current) != manifest["task_hash"] or again["receipt_hash"] != manifest["diagnostic_receipt_hash"]:
            raise ValueError("Frozen execution inputs changed during interactions")
        if final_conditions != conditions or final_upstream != upstream:
            raise ValueError("Upstream controller plan or M6 receipt changed during ablations")
        manifest.update(status="sealed", seconds_including_loading=time.perf_counter() - started, files_sha256=seal_files(out))
        manifest["seal_hash"] = digest(manifest)
    except Exception as exc:
        manifest.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        save_json(out / "manifest.json", manifest)
        raise
    finally:
        if pool is not None:
            pool.close()
    save_json(out / "manifest.json", manifest)
    return manifest


def verify_interactions(protocol, binding, predictions, diagnostic_reveal, directory, engineering=False, _ablation_context=None):
    receipt, tasks = preflight(protocol, binding, predictions, diagnostic_reveal, engineering)
    settings, budgets = protocol["spec"]["execution"]["settings"], protocol["spec"]["budgets"]
    conditions, upstream = runtime_plan(protocol, binding, predictions, diagnostic_reveal, engineering, _ablation_context)
    prefix = "ablation" if _ablation_context is not None else "execution"
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    if manifest.get("kind") != "frozen_" + prefix + "_interactions" or manifest.get("schema_version") != 1 \
            or manifest.get("upstream", {}) != upstream \
            or manifest.get("status") != "sealed" or manifest.get("scope") != protocol["scope"] \
            or manifest.get("protocol_hash") != protocol["lock_hash"] or manifest.get("model_binding_hash") != binding["binding_hash"] \
            or manifest.get("diagnostic_receipt_hash") != receipt["receipt_hash"] or manifest.get("settings_hash") != digest(settings) \
            or manifest.get("conditions") != conditions or manifest.get("model_paths") != paths_for(binding) \
            or manifest.get("task_hash") != digest(tasks) or manifest.get("ordered_task_ids") != [task["id"] for task in tasks] \
            or manifest.get("offline_references_opened") is not False \
            or manifest.get("seal_hash") != digest({k: v for k, v in manifest.items() if k != "seal_hash"}) \
            or manifest.get("files_sha256") != seal_files(directory):
        raise ValueError("Missing, changed or incomplete frozen execution seal")
    if protocol["scope"] == "formal" and manifest["injected_pool"]:
        raise ValueError("Injected execution cannot be formal evidence")
    records = read_jsonl(directory / "interactions.jsonl")
    expected = [(condition, task["id"]) for condition in conditions for task in tasks]
    if [(row["condition"], row["task_id"]) for row in records] != expected:
        raise ValueError("All registered conditions must contain exactly all tasks in frozen order")
    by_id = {task["id"]: task for task in tasks}
    for row in records:
        task, config = by_id[row["task_id"]], conditions[row["condition"]]
        if row["policy"] != config["policy"] or row["hard_guard_enabled"] != config["hard_guard"] \
                or row["analyzer_mode"] != settings["analyzer_mode"] or row["max_tool_steps"] != settings["max_tool_steps"] \
                or row["source_task_id"] != task["source_task_id"] or row["split"] != task["split"] \
                or row["offline_metrics_pending"] is not True or "metrics" in row:
            raise ValueError("Runtime condition or offline evaluation boundary changed")
        snapshot = row["model_pool"]
        if snapshot["models"] != paths_for(binding) or snapshot["resident_model_limit"] != 1 \
                or snapshot["context_limit"] != budgets["context_limit"] \
                or snapshot["shared_token_ledger"]["limit"] != budgets["token_budget"]:
            raise ValueError("Execution model or shared budget differs from frozen plan")
        audit_ledger(snapshot["shared_token_ledger"])
        audit_intensity(task, row, {"intensity_config": condition_intensity(config, settings)})
        events = row["final_state"]["events"]
        boundary = row["initial_event_count"]
        if type(boundary) is not int or not 0 <= boundary <= len(events):
            raise ValueError("Invalid initial committed event boundary")
        if canonical(replay_events(task, events).files) != canonical(row["final_state"]["files"]):
            raise ValueError("Committed tool replay differs from sealed files")
    return manifest, tasks, records


def score_records(tasks, references, records):
    by_id, scored = {task["id"]: task for task in tasks}, []
    for record in records:
        row = deepcopy(record)
        task, events = by_id[row["task_id"]], row["final_state"]["events"]
        initial = evaluate_execution(task, replay_events(task, events[:row["initial_event_count"]]), references[task["id"]])
        final = evaluate_execution(task, replay_events(task, events), references[task["id"]])
        row.update(metrics=final, initial_metrics=initial, offline_metrics_pending=False,
            feasible_at_repair_start=not initial["irreversible_hard_violations"],
            repair_introduced_hard_violations=sorted({event["requirement_id"] for event in final["hard_violation_events"]
                                                    if event["event_index"] >= row["initial_event_count"]}))
        scored.append(row)
    return scored


def summary(tasks, references, records, protocol, binding, conditions=None):
    settings, result = protocol["spec"]["execution"]["settings"], {}
    for condition, config in (conditions if conditions is not None else execution_condition_map(settings)).items():
        rows = [row for row in records if row["condition"] == condition]
        audit = audit_records(tasks, references, {"status": "completed", "scope": protocol["scope"],
            "task_hash": digest(tasks), "offline_reference_hash": digest(references), "policies": [config["policy"]],
            "intensity_config": condition_intensity(config, settings),
            "model_paths": paths_for(binding)}, rows)
        splits = {}
        for split in ("test", "ood"):
            group = [row for row in rows if row["split"] == split]
            # One record per contract variant; report task groups explicitly.
            # M8 must aggregate variants within source_task_id before inference.
            feasible = [row for row in group if row["feasible_at_repair_start"]]
            splits[split] = {"runs": len(group), "source_task_groups": len({row["source_task_id"] for row in group}),
                "compliant_successes": sum(row["metrics"]["compliant_success"] for row in group),
                "errors": sum(row["status"] == "error" for row in group), "feasible_runs": len(feasible),
                "initially_irreversible_runs": len(group) - len(feasible),
                "feasible_compliant_successes": sum(row["metrics"]["compliant_success"] for row in feasible),
                "repair_introduced_violation_runs": sum(bool(row["repair_introduced_hard_violations"]) for row in group),
                "charged_tokens": sum(row["model_pool"]["shared_token_ledger"]["charged_tokens"] for row in group)}
        result[condition] = {"raw_audit": audit, "splits": splits}
    return result


def reveal(protocol, binding, predictions, diagnostic_reveal, interactions, out, engineering=False, _ablation_context=None):
    sealed, tasks, records = verify_interactions(protocol, binding, predictions, diagnostic_reveal, interactions, engineering, _ablation_context)
    conditions, upstream = runtime_plan(protocol, binding, predictions, diagnostic_reveal, engineering, _ablation_context)
    prefix = "ablation" if _ablation_context is not None else "execution"
    out = Path(out)
    if out.exists():
        raise ValueError("Choose a fresh execution scoring directory")
    attempt = claim(protocol, prefix + "-reveal", out)  # Before the first reference hash/read.
    out.mkdir(parents=True, exist_ok=False)
    manifest = {"kind": "frozen_" + prefix + "_reveal", "schema_version": 1, "scope": protocol["scope"], "status": "running", "upstream": upstream,
        "protocol_hash": protocol["lock_hash"], "interaction_seal_hash": sealed["seal_hash"],
        "model_binding_hash": binding["binding_hash"], "claim": attempt, "references_accessed_after_claim": True}
    save_json(out / "manifest.json", manifest)
    try:
        reference = protocol["execution_binding"]["files"]["references"]
        if file_hash(reference["path"]) != reference["sha256"]:
            raise ValueError("Frozen independent execution references changed")
        refs = load_references(reference["path"], tasks)
        scored = score_records(tasks, refs, records)
        with (out / "runs.jsonl").open("x", encoding="utf-8", newline="\n") as stream:
            for row in scored:
                stream.write(canonical(row) + "\n")
                stream.flush()
        save_json(out / "summary.json", summary(tasks, refs, scored, protocol, binding, conditions))
        if file_hash(reference["path"]) != reference["sha256"]:
            raise ValueError("Execution references changed during scoring")
        verify_interactions(protocol, binding, predictions, diagnostic_reveal, interactions, engineering, _ablation_context)
        manifest.update(status="completed", files_sha256=seal_files(out),
            warning="Offline counts and trace replay only. M7 ablations, M8 source-task/seed statistics and durable model backup remain required.")
        manifest["receipt_hash"] = digest(manifest)
    except Exception as exc:
        manifest.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        save_json(out / "manifest.json", manifest)
        raise
    save_json(out / "manifest.json", manifest)
    return manifest


def verify_scoring(protocol, binding, predictions, diagnostic_reveal, interactions, directory, engineering=False, _ablation_context=None):
    sealed, _, _ = verify_interactions(protocol, binding, predictions, diagnostic_reveal, interactions, engineering, _ablation_context)
    _, upstream = runtime_plan(protocol, binding, predictions, diagnostic_reveal, engineering, _ablation_context)
    prefix = "ablation" if _ablation_context is not None else "execution"
    directory = Path(directory)
    receipt = read_json(directory / "manifest.json")
    if receipt.get("kind") != "frozen_" + prefix + "_reveal" or receipt.get("schema_version") != 1 \
            or receipt.get("upstream", {}) != upstream \
            or receipt.get("status") != "completed" or receipt.get("scope") != protocol["scope"] \
            or receipt.get("protocol_hash") != protocol["lock_hash"] or receipt.get("model_binding_hash") != binding["binding_hash"] \
            or receipt.get("interaction_seal_hash") != sealed["seal_hash"] \
            or receipt.get("receipt_hash") != digest({k: v for k, v in receipt.items() if k != "receipt_hash"}) \
            or receipt.get("files_sha256") != seal_files(directory) \
            or not {"runs.jsonl", "summary.json"} <= set(receipt["files_sha256"]):
        raise ValueError("Missing, changed or incomplete execution scoring receipt")
    return {"status": "completed", "scope": protocol["scope"], "protocol_hash": protocol["lock_hash"],
            "receipt_hash": receipt["receipt_hash"], "references_reopened": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["interact", "verify", "reveal", "verify-reveal"])
    for name in ("protocol", "binding", "predictions", "diagnostic-reveal"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--interactions", type=Path)
    parser.add_argument("--execution-reveal", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--engineering", action="store_true")
    args = parser.parse_args()
    protocol, binding = read_json(args.protocol), read_json(args.binding)
    if args.command == "interact":
        if args.out is None:
            parser.error("interact requires --out")
        result = interact(protocol, binding, args.predictions, args.diagnostic_reveal, args.out, args.engineering)
    else:
        if args.interactions is None:
            parser.error("verify/reveal requires --interactions")
        if args.command == "verify-reveal":
            if args.execution_reveal is None:
                parser.error("verify-reveal requires --execution-reveal")
            result = verify_scoring(protocol, binding, args.predictions, args.diagnostic_reveal, args.interactions, args.execution_reveal, args.engineering)
        elif args.command == "verify":
            result = verify_interactions(protocol, binding, args.predictions, args.diagnostic_reveal, args.interactions, args.engineering)[0]
        else:
            if args.out is None:
                parser.error("reveal requires --out")
            result = reveal(protocol, binding, args.predictions, args.diagnostic_reveal, args.interactions, args.out, args.engineering)
    print(json.dumps({key: result[key] for key in ("status", "scope", "protocol_hash")}, indent=2))


if __name__ == "__main__":
    main()
