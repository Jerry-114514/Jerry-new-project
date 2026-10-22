"""Recompute public engineering statistical arithmetic, not full M8 acceptance."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.core import canonical
from intentlab.formal_data import read_jsonl
from intentlab.research_statistics import analyze_records


def audit(root):
    matrix = Path(root) / "matrix"
    protocol = json.loads((matrix / "protocol.engineering.lock.json").read_text(encoding="utf-8"))
    if protocol["scope"] != "engineering":
        raise ValueError("Only public engineering arithmetic evidence is supported")
    saved = json.loads((matrix / "research-statistics.json").read_text(encoding="utf-8"))
    report = analyze_records(protocol, json.loads((matrix / "diagnostic-reveal/scores.json").read_text(encoding="utf-8")),
        {f"{condition}-seed-{seed}": read_jsonl(matrix / f"diagnostic-reveal/{condition}-seed-{seed}-loss.jsonl")
         for condition in ("D", "E") for seed in (0, 1, 2)},
        read_jsonl(matrix / "execution-reveal/runs.jsonl"), read_jsonl(matrix / "ablation-reveal/runs.jsonl"), include_auxiliary="auxiliary" in saved)
    if canonical(report) != canonical(saved):
        raise ValueError("Statistical arithmetic, registered family or source/seed aggregation changed")
    return {"scope": "engineering", "comparisons_recomputed": len(report["comparisons"]),
        "secondary_family_size": report["secondary_family_size"],
        "comparisons_without_inference": sum(row["hypothesis_test"]["p_value"] is None for row in report["comparisons"].values()),
        "m8_complete": False, "human_reviews_completed": 0, "formal_9b_training": False,
        "warning": "Arithmetic replay only. Tiny test/OOD each have one source task, so CI and p-values are null; no evidence for efficacy, a calibrated risk bound, training-seed population inference or full M8 acceptance."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("examples/results/formal-m1n-statistics-core"))
    args = parser.parse_args()
    subprocess.run([sys.executable, str(Path(__file__).with_name("audit_ablation_evidence.py")), "--root", str(args.root)], check=True)
    report = audit(args.root)
    (args.root / "statistics-verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    sums = {path.relative_to(args.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in args.root.rglob("*") if path.is_file() and path.name != "checksums.json"}
    (args.root / "checksums.json").write_text(json.dumps(sums, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
