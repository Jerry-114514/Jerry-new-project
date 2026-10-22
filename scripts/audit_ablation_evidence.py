"""Replay engineering M7 controls after validating the M5/M6/controller chain."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from audit_frozen_execution_evidence import audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("examples/results/formal-m1m-frozen-ablation"))
    args = parser.parse_args()
    subprocess.run([sys.executable, str(Path(__file__).with_name("audit_controller_plan_evidence.py")), "--root", str(args.root)], check=True)
    report = audit(args.root, ablation=True)
    report.update(m7_execution_controls_run=True, lr_risk_feedback_run=False,
                  warning="Real tiny CPU control runs with two generated tokens; engineering failure paths only. No formal M7, LR risk-feedback result, statistical efficacy or durable model backup.")
    (args.root / "ablation-verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    sums = {path.relative_to(args.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in args.root.rglob("*") if path.is_file() and path.name != "checksums.json"}
    (args.root / "checksums.json").write_text(json.dumps(sums, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
