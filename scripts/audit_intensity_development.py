"""Controlled injected omissions for k selection; not a language-model experiment."""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build_execution_development import development_tasks
from intentlab.core import digest
from intentlab.execution_analysis import ContractRuleActor, analyze_execution
from intentlab.execution_audit import audit_records
from intentlab.execution_oracle import evaluate_execution
from intentlab.formal_data import write_jsonl
from intentlab.intensity import validate_intensity
from intentlab.report import save_experiment, save_json
from intentlab.runner import run_task


class OmittedDeliverablesActor(ContractRuleActor):
    def propose(self, task, state, phase, target=None, attempt=0):
        if phase == "initial":
            return {"actions": [{"op": "validate", "ok": True}]}
        return super().propose(task, state, phase, target, attempt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path, default=Path("configs/intensity.development.json"))
    args = parser.parse_args()
    config = validate_intensity(json.loads(args.config.read_text(encoding="utf-8")))
    tasks, refs = development_tasks()
    references = {row["task_id"]: row for row in refs}
    args.out.mkdir(parents=True, exist_ok=False)
    policies = ["fixed-k", "dynamic-k"]
    manifest = {"kind": "controlled_injected_omission_intensity_audit", "scope": "engineering", "status": "running",
                "task_hash": digest(tasks), "offline_reference_hash": digest(references), "policies": policies,
                "intensity_config": config, "model_paths": None, "actor": "scripted", "executor_is_language_model": False,
                "max_repairs": 3, "max_tool_steps": 1, "hard_guard_enabled": True, "redact_events": False,
                "warning": "Scripted validate-only initial phase deliberately omits both deliverables. Not natural errors, independent tasks, token efficiency evidence, or formal M7 results."}
    save_json(args.out / "manifest.json", manifest)
    records = []
    for policy in policies:
        for task in tasks:
            row = run_task(deepcopy(task), OmittedDeliverablesActor(), policy, analyzer=analyze_execution,
                evaluator=lambda task, state: evaluate_execution(task, state, references[task["id"]]),
                intensity_config=config)
            row["source_task_id"] = task["source_task_id"]
            records.append(row)
    write_jsonl(args.out / "runs.jsonl", records)
    manifest["status"] = "completed"
    save_experiment(records, args.out, manifest)
    audit = audit_records(tasks, references, manifest, records)
    save_json(args.out / "replay-audit.json", audit)
    print(json.dumps({"runs": audit["runs"], "decisions": audit["intensity_decisions_recomputed"], "policies": audit["policies"]}, indent=2))


if __name__ == "__main__":
    main()
