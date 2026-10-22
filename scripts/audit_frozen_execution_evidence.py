"""Recompute public engineering P1-P4 traces/scores without model binaries."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.core import canonical, digest
from intentlab.execution_data import load_execution_tasks, load_references
from intentlab.formal_data import read_jsonl
from intentlab.frozen_execution import condition_intensity, score_records, summary
from intentlab.execution_protocol import execution_condition_map


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def audit(root, ablation=False):
    matrix = Path(root) / "matrix"
    protocol, binding = read(matrix / "protocol.engineering.lock.json"), read(matrix / "execution-model-lock.json")
    if protocol["scope"] != "engineering" or binding["scope"] != "engineering":
        raise ValueError("Only public synthetic engineering evidence can use this replay")
    prefix = "ablation" if ablation else "execution"
    interactions, scored = matrix / (prefix + "-interactions"), matrix / (prefix + "-reveal")
    if ablation:
        from intentlab.controller_plan import condition_map
        conditions = condition_map(protocol["controller_binding"], protocol["spec"]["execution"]["settings"])
    else:
        conditions = execution_condition_map(protocol["spec"]["execution"]["settings"])
    sealed, receipt = read(interactions / "manifest.json"), read(scored / "manifest.json")
    for directory, record, field, status in ((interactions, sealed, "seal_hash", "sealed"), (scored, receipt, "receipt_hash", "completed")):
        actual = {path.relative_to(directory).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in directory.rglob("*") if path.is_file() and path != directory / "manifest.json"}
        if record["scope"] != "engineering" or record["status"] != status \
                or record["protocol_hash"] != protocol["lock_hash"] or record["model_binding_hash"] != binding["binding_hash"] \
                or record[field] != digest({key: value for key, value in record.items() if key != field}) \
                or record["files_sha256"] != actual:
            raise ValueError("Execution seal, receipt or raw outputs differ")
    if sealed["injected_pool"] or sealed["offline_references_opened"] \
            or sealed["kind"] != "frozen_" + prefix + "_interactions" or receipt["kind"] != "frozen_" + prefix + "_reveal" \
            or sealed["conditions"] != conditions \
            or receipt["interaction_seal_hash"] != sealed["seal_hash"] \
            or sealed["diagnostic_receipt_hash"] != read(matrix / "diagnostic-reveal/manifest.json")["receipt_hash"]:
        raise ValueError("Not the claimed real tiny-model M5-to-M6 sequence")
    settings, budgets = protocol["spec"]["execution"]["settings"], protocol["spec"]["budgets"]
    model_paths = {role: binding["models"][role]["path"] for role in ("actor", "analyzer")}
    if sealed["settings_hash"] != digest(settings) or sealed["model_paths"] != model_paths:
        raise ValueError("Execution settings or bound model roles differ")
    if ablation:
        baseline = conditions["dynamic-k"]["intensity"]
        expected_upstream = {"execution_receipt_hash": read(matrix / "execution-reveal/manifest.json")["receipt_hash"],
            "controller_binding_hash": digest(protocol["controller_binding"]),
            "strong_fixed_condition": "fixed-k-" + str(protocol["controller_binding"]["selection"]["selected_k"]),
            "parameter_noop_controls": [name for name, config in conditions.items() if name.startswith("dynamic-k-") and config["intensity"] == baseline]}
        if sealed["upstream"] != expected_upstream or receipt["upstream"] != expected_upstream:
            raise ValueError("M7 upstream M6/controller provenance differs")
    tasks = sorted(load_execution_tasks(matrix / "diagnostic-inputs/tasks.jsonl"), key=lambda row: row["id"])
    references_path = matrix / "diagnostic-inputs/references.jsonl"
    if hashlib.sha256(references_path.read_bytes()).hexdigest() != protocol["execution_binding"]["files"]["references"]["sha256"] \
            or digest(tasks) != sealed["task_hash"]:
        raise ValueError("Archived public tasks or engineering static references differ")
    refs = load_references(references_path, tasks)
    raw = read_jsonl(interactions / "interactions.jsonl")
    expected = [(condition, task["id"]) for condition in conditions for task in tasks]
    if [(row["condition"], row["task_id"]) for row in raw] != expected \
            or any("metrics" in row or row["offline_metrics_pending"] is not True for row in raw):
        raise ValueError("Frozen interaction coverage or scoring boundary differs")
    by_id = {task["id"]: task for task in tasks}
    for row in raw:
        task, config = by_id[row["task_id"]], conditions[row["condition"]]
        snapshot = row["model_pool"]
        if row["policy"] != config["policy"] or row["hard_guard_enabled"] != config["hard_guard"] \
                or row["intensity_config"] != condition_intensity(config, settings) \
                or row["analyzer_mode"] != settings["analyzer_mode"] or row["max_tool_steps"] != settings["max_tool_steps"] \
                or any(row[key] != task[key] for key in ("source_task_id", "family", "split")) \
                or snapshot["models"] != model_paths or snapshot["resident_model_limit"] != 1 \
                or snapshot["context_limit"] != budgets["context_limit"] or snapshot["shared_token_ledger"]["limit"] != budgets["token_budget"]:
            raise ValueError("Recorded control, task identity or shared budget differs from the frozen plan")
        if any(event["completion_allowance"] > budgets["max_new_tokens"]
               for event in snapshot["shared_token_ledger"]["events"] if event["status"] != "denied"):
            raise ValueError("Recorded completion allowance exceeds the frozen output cap")
    recomputed = score_records(tasks, refs, raw)
    if canonical(recomputed) != canonical(read_jsonl(scored / "runs.jsonl")):
        raise ValueError("Offline score/initial prefix/repair attribution replay differs")
    totals = summary(tasks, refs, recomputed, protocol, binding, conditions)
    if canonical(totals) != canonical(read(scored / "summary.json")):
        raise ValueError("Condition summaries, budgets or intensity decisions differ")
    return {"scope": "engineering", "conditions": len(conditions), "runs": len(raw),
        "source_task_groups": len({task["source_task_id"] for task in tasks}),
        "errors_retained": sum(row["status"] == "error" for row in raw),
        "compliant_successes": sum(row["metrics"]["compliant_success"] for row in recomputed),
        "trace_metrics_budget_intensity_and_summary_replayed": True, "model_forward_recomputed": False,
        "human_reviews_completed": 0, "formal_9b_training": False,
        "warning": "Real tiny CPU generations with two output tokens; engineering failure-path coverage, not model capability, guard efficacy, formal execution or persistent model backup."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("examples/results/formal-m1k-frozen-execution"))
    args = parser.parse_args()
    subprocess.run([sys.executable, str(Path(__file__).with_name("audit_diagnostic_evidence.py")), "--root", str(args.root)], check=True)
    report = audit(args.root)
    (args.root / "execution-verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    sums = {p.relative_to(args.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in args.root.rglob("*") if p.is_file() and p.name != "checksums.json"}
    # String-key sort is identical on Windows and Linux; Path sorting is not.
    (args.root / "checksums.json").write_text(json.dumps(sums, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
