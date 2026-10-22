"""Recompute execution outcomes and budgets from completed raw records."""

import argparse
import json
from pathlib import Path

from .core import canonical, digest, replay_events
from .execution_data import load_execution_tasks, load_references
from .execution_oracle import evaluate_execution
from .formal_data import read_jsonl
from .report import save_json
from .intensity import choose_intensity, validate_intensity


def audit_intensity(task, record, manifest):
    """Recompute decisions before each proposal from the last online findings."""
    if record["policy"] not in {"fixed-k", "dynamic-k"}:
        if record.get("intensity_config") is not None:
            raise ValueError("Unexpected intensity config in legacy policy")
        return 0
    config = validate_intensity(manifest.get("intensity_config"))
    if canonical(config) != canonical(record.get("intensity_config")):
        raise ValueError("Intensity configuration changed inside a condition")
    findings, checked = None, 0
    for step in record["history"]:
        if step["phase"] in {"initial", "verify"}:
            findings = step["findings"]
        elif step["phase"] == "repair":
            if findings is None:
                raise ValueError("Missing online findings before intensity decision")
            decision = choose_intensity(task, findings, record["policy"], config)
            if canonical(decision) != canonical(step.get("intensity_decision")) or canonical(decision["target"]) != canonical(step["target"]):
                raise ValueError("Intensity decision differs from public online findings")
            checked += 1
            if step["accepted"]:
                findings = step["findings"]
    return checked


def audit_ledger(ledger):
    charged = 0
    calls, denied = 0, 0
    for event in ledger["events"]:
        status = event["status"]
        if status == "completed":
            count = event["completion_tokens"]
            if type(count) is not int or not 0 <= count <= event["completion_allowance"]:
                raise ValueError("Invalid completed token charge")
            expected = event["prompt_tokens"] + count
            calls += 1
        elif status == "error":
            if event["completion_tokens"] is not None:
                raise ValueError("Failed unknown generation length is not an observed token count")
            expected = event["prompt_tokens"] + event["completion_allowance"]
            calls += 1
        elif status == "denied":
            expected = 0
            denied += 1
        else:
            raise ValueError("Completed execution contains an unsettled generation")
        if event["charged_tokens"] != expected:
            raise ValueError("Per-call token accounting mismatch")
        charged += expected
    if charged != ledger["charged_tokens"] or ledger["remaining_tokens"] != ledger["limit"] - charged \
            or not 0 <= charged <= ledger["limit"] or calls != ledger["calls"] or denied != ledger["denied_calls"]:
        raise ValueError("Shared ledger totals or hard budget mismatch")
    return charged


def audit_records(tasks, references, manifest, records):
    if manifest.get("status") != "completed":
        raise ValueError("Observe the active process; do not audit a running manifest as complete")
    by_id = {task["id"]: task for task in tasks}
    ids = {record["task_id"] for record in records}
    if not ids or not ids <= set(by_id):
        raise ValueError("Unknown or empty recorded task set")
    selected = [task for task in tasks if task["id"] in ids]
    if digest(selected) != manifest["task_hash"]:
        raise ValueError("Executed task definitions changed")
    selected_refs = {task["id"]: references[task["id"]] for task in selected}
    if digest(selected_refs) != manifest["offline_reference_hash"]:
        raise ValueError("Offline references changed")
    expected = {(policy, tid) for policy in dict.fromkeys(manifest["policies"]) for tid in ids}
    actual = [(row["policy"], row["task_id"]) for row in records]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("Duplicate or missing planned execution records")
    groups = {}
    intensity_decisions = 0
    for row in records:
        task = by_id[row["task_id"]]
        intensity_decisions += audit_intensity(task, row, manifest)
        events = row["final_state"]["events"]
        state = replay_events(task, events)
        if canonical(state.files) != canonical(row["final_state"]["files"]):
            raise ValueError("Committed tool replay differs from recorded files")
        metrics = evaluate_execution(task, state, references[task["id"]])
        if canonical(metrics) != canonical(row["metrics"]):
            raise ValueError("Final metrics differ from independent recomputation")
        first = next((step for step in row["history"] if step["phase"] == "initial"), {"actions": []})
        initial_count = row.get("initial_event_count", len(first["actions"]))
        if type(initial_count) is not int or not 0 <= initial_count <= len(events):
            raise ValueError("Invalid initial tool-event boundary")
        initial = replay_events(task, events[:initial_count])
        initial_metrics = evaluate_execution(task, initial, references[task["id"]])
        if canonical(initial_metrics) != canonical(row["initial_metrics"]):
            raise ValueError("Initial evaluation differs from the committed prefix")
        introduced = sorted({event["requirement_id"] for event in metrics["hard_violation_events"]
                             if event["event_index"] >= initial_count})
        if introduced != row["repair_introduced_hard_violations"]:
            raise ValueError("Repair-introduced violation attribution mismatch")
        if row["feasible_at_repair_start"] != (not initial_metrics["irreversible_hard_violations"]):
            raise ValueError("Initial historical feasibility stratum mismatch")
        charged = 0
        if "model_pool" in row:
            if row["model_pool"]["models"] != manifest["model_paths"]:
                raise ValueError("Model role paths changed inside a condition")
            charged = audit_ledger(row["model_pool"]["shared_token_ledger"])
        group = groups.setdefault(row["policy"], {"runs": 0, "compliant_successes": 0, "errors": 0,
            "repair_introduced_violation_runs": 0, "charged_tokens": 0})
        group["runs"] += 1
        group["compliant_successes"] += bool(metrics["compliant_success"])
        group["errors"] += row["status"] == "error"
        group["repair_introduced_violation_runs"] += bool(introduced)
        group["charged_tokens"] += charged
    return {"kind": "raw_execution_replay_audit", "verified": True, "runs": len(records),
        "intensity_decisions_recomputed": intensity_decisions,
        "source_task_groups": len({task["source_task_id"] for task in selected}), "policies": groups,
        "scope": manifest["scope"], "warning": "Recomputes program-defined references, not human truth or statistical independence."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--references", type=Path, required=True)
    parser.add_argument("--runs", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Choose a fresh audit output path")
    tasks = load_execution_tasks(args.tasks)
    references = load_references(args.references, tasks)
    results = {}
    for directory in args.runs:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        results[str(directory)] = audit_records(tasks, references, manifest, read_jsonl(directory / "runs.jsonl"))
    save_json(args.out, results)
    print(json.dumps({key: {"verified": value["verified"], "runs": value["runs"]} for key, value in results.items()}, indent=2))


if __name__ == "__main__":
    main()
