"""Replay the public engineering statistics receipt after its upstream audits."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.core import canonical, digest
from intentlab.diagnostic_protocol import seal_files
from intentlab.frozen_statistics import compute


def audit(root):
    matrix = Path(root) / "matrix"
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    protocol = read(matrix / "protocol.engineering.lock.json")
    binding = read(matrix / "execution-model-lock.json")
    directory = matrix / "statistics-analysis"
    manifest = read(directory / "manifest.json")
    upstream = {name: read(matrix / stage / "manifest.json")["receipt_hash"]
                for name, stage in (("M5", "diagnostic-reveal"), ("M6", "execution-reveal"), ("M7", "ablation-reveal"))}
    if protocol["scope"] != "engineering" or manifest.get("scope") != "engineering" \
            or manifest.get("kind") != "frozen_statistics_analysis" or manifest.get("schema_version") != 1 \
            or manifest.get("status") != "completed" or manifest.get("protocol_hash") != protocol["lock_hash"] \
            or manifest.get("model_binding_hash") != binding["binding_hash"] \
            or manifest.get("upstream_receipts") != upstream \
            or manifest.get("statistics_settings_hash") != digest(protocol["spec"]["statistics"]) \
            or manifest.get("gold_or_references_reopened") is not False or manifest.get("m8_complete") is not False \
            or manifest.get("receipt_hash") != digest({key: value for key, value in manifest.items() if key != "receipt_hash"}) \
            or manifest.get("files_sha256") != seal_files(directory) or "report.json" not in manifest["files_sha256"]:
        raise ValueError("Statistics receipt or its upstream bindings changed")
    report = compute(protocol, matrix / "diagnostic-reveal", matrix / "execution-reveal", matrix / "ablation-reveal")
    if canonical(report) != canonical(read(directory / "report.json")):
        raise ValueError("Statistics stage differs from registered arithmetic")
    return {"scope": "engineering", "statistics_stage_verified": True, "upstream_stages": sorted(upstream),
            "comparisons_recomputed": len(report["comparisons"]), "secondary_family_size": report["secondary_family_size"],
            "candidate_and_common_feasibility_recomputed": True, "m8_complete": False,
            "human_reviews_completed": 0, "formal_9b_training": False,
            "warning": "Public synthetic engineering replay, not formal inference or independent human truth. Model binaries are not archived here; full live verification additionally requires the bound assets."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("examples/results/formal-m1o-candidate-statistics"))
    args = parser.parse_args()
    subprocess.run([sys.executable, str(Path(__file__).with_name("audit_research_statistics_evidence.py")), "--root", str(args.root)], check=True)
    report = audit(args.root)
    (args.root / "statistics-stage-verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    sums = {path.relative_to(args.root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in args.root.rglob("*") if path.is_file() and path.name != "checksums.json"}
    (args.root / "checksums.json").write_text(json.dumps(sums, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
