"""Audit public-rule sidecar merging and actual repair opportunities offline."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.core import canonical, initial_state
from intentlab.execution_analysis import HybridExecutionAnalyzer
from intentlab.execution_audit import audit_records
from intentlab.execution_data import load_execution_tasks, load_references
from intentlab.formal_data import read_jsonl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root
    tasks = load_execution_tasks(root / "inputs/tasks.jsonl")
    references = load_references(root / "inputs/offline-references.jsonl", tasks)
    manifest = json.loads((root / "hybrid/manifest.json").read_text(encoding="utf-8"))
    records = read_jsonl(root / "hybrid/runs.jsonl")
    replay = audit_records(tasks, references, manifest, records)
    by_id = {task["id"]: task for task in tasks}
    merged_count = 0
    per_run = []
    for row in records:
        if row.get("analyzer_mode") != "hybrid" or manifest.get("analyzer_mode") != "hybrid":
            raise ValueError("This audit requires explicit hybrid records")
        task = by_id[row["task_id"]]
        state = initial_state(task)
        visible, index = not manifest["redact_events"], 0
        for step in row["history"]:
            if step["phase"] == "initial":
                state.apply(step["actions"])
                observation = state
            elif step["phase"] == "verify":
                visible, observation = True, state
            elif step["phase"] == "repair":
                observation = state.clone()
                observation.apply(step["actions"])
            else:
                continue
            if step.get("findings"):
                saved = row["analyzer_decisions"][index]
                check = HybridExecutionAnalyzer(lambda *args: saved["model_findings"])
                effective = check(task, observation, visible)
                if canonical(check.decisions[0]) != canonical(saved) or canonical(effective) != canonical(step["findings"]):
                    raise ValueError("Hybrid decisions differ from trusted tools and public rules")
                index += 1
            if step["phase"] == "repair" and step["accepted"]:
                state = observation
        if index != len(row["analyzer_decisions"]):
            raise ValueError("Missing or excess hybrid analysis trace")
        merged_count += index
        per_run.append({"task_id": row["task_id"], "policy": row["policy"], "status": row["status"],
            "compliant_success": row["metrics"]["compliant_success"],
            "repair_proposals": sum(step["phase"] == "repair" for step in row["history"]),
            "hard_guard_checks": sum(step.get("hard_guard_passed") is not None for step in row["history"]),
            "overridden_model_statuses": sum(len(item["overrides"]) for item in row["analyzer_decisions"])})
    out = {"kind": "hybrid_development_recomputation", "scope": "development", "replay": replay,
           "hybrid_decisions_recomputed": merged_count, "runs": per_run,
           "warning": "Limited public development tasks. Hybrid gate equals the public-rule baseline; no claim of improved LM diagnosis or guard efficacy."}
    (root / "verification.json").write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    sums = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and p.name != "checksums.json"}
    (root / "checksums.json").write_text(json.dumps(sums, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"runs": len(records), "hybrid_decisions_recomputed": merged_count, "per_run": per_run}, indent=2))


if __name__ == "__main__":
    main()
