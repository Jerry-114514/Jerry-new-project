"""Replay public engineering fixed-k development selection, not M7 outcomes."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.controller_plan import condition_map, validate_selection
from intentlab.formal_data import read_jsonl


def audit(root):
    matrix = Path(root) / "matrix"
    lock = json.loads((matrix / "protocol.engineering.lock.json").read_text(encoding="utf-8"))
    if lock["scope"] != "engineering":
        raise ValueError("Only public engineering evidence is supported by this replay")
    binding = lock["controller_binding"]
    paths = {"plan": matrix / "controller-plan.json", "selection_report": matrix / "controller-development/selection.json"}
    for name, path in paths.items():
        if hashlib.sha256(path.read_bytes()).hexdigest() != binding["files"][name]["sha256"]:
            raise ValueError("Controller plan or development selection report changed")
    plan, report = (json.loads(paths[name].read_text(encoding="utf-8")) for name in ("plan", "selection_report"))
    if plan != binding["plan"] or report["injected_pool"] or report["scope"] != "engineering":
        raise ValueError("Not the claimed real tiny engineering selection")
    selection = validate_selection(report, lock["spec"]["execution"]["settings"], read_jsonl(matrix / "controller-cases.jsonl"))
    if selection != binding["selection"]:
        raise ValueError("Frozen strong fixed k differs from development replay")
    return {"scope": "engineering", "fixed_k_controls": len(report["arms"]),
        "validation_runs": sum(len(arm["records"]) for arm in report["arms"]),
        "validation_errors_retained": sum(row["status"] == "error" for arm in report["arms"] for row in arm["records"]),
        "selected_k": selection["selected_k"], "selection_and_raw_trace_audit_replayed": True,
        "planned_execution_controls": list(condition_map(binding, lock["spec"]["execution"]["settings"])),
        "m7_execution_controls_run": None if (matrix / "ablation-reveal/manifest.json").exists() else False, "lr_risk_feedback_run": False,
        "human_reviews_completed": 0, "formal_9b_training": False, "model_forward_recomputed": False,
        "warning": "Real tiny CPU validation selection with two output tokens; no formal data, human review, M7 ablation outcome or durable model backup."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("examples/results/formal-m1l-controller-plan"))
    args = parser.parse_args()
    subprocess.run([sys.executable, str(Path(__file__).with_name("audit_frozen_execution_evidence.py")), "--root", str(args.root)], check=True)
    report = audit(args.root)
    (args.root / "controller-verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    sums = {path.relative_to(args.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in args.root.rglob("*") if path.is_file() and path.name != "checksums.json"}
    (args.root / "checksums.json").write_text(json.dumps(sums, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
