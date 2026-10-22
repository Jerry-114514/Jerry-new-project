"""Recompute the published v2 tiny-worker engineering evidence, not model loss."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.core import digest
from intentlab.matrix import validate_result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("examples/results/formal-m1h-execution-binding"))
    args = parser.parse_args()
    root = args.root
    matrix = json.loads((root / "matrix/matrix.json").read_text(encoding="utf-8"))
    lock = json.loads((root / "matrix/protocol.engineering.lock.json").read_text(encoding="utf-8"))
    if lock["scope"] != "engineering" or lock["schema_version"] != 2 or lock["lock_hash"] != digest({k: v for k, v in lock.items() if k != "lock_hash"}):
        raise ValueError("Engineering v2 lock content differs")
    if matrix["scope"] != "engineering" or matrix["status"] != "completed" or matrix["lock_hash"] != lock["lock_hash"] \
            or matrix["heldout_evaluated"] is not False or len(matrix["jobs"]) != 6:
        raise ValueError("Incomplete or misclassified worker matrix")
    pairs = {}
    attempts = 0
    for job in matrix["jobs"]:
        if job["status"] != "completed" or job["config"]["device"] != "cpu":
            raise ValueError("This evidence must contain completed tiny CPU jobs")
        path = root / "matrix" / job["name"] / "result.json"
        result = json.loads(path.read_text(encoding="utf-8"))
        validate_result(result, job["config"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != job["result_sha256"]:
            raise ValueError("Raw training result changed")
        pairs.setdefault(job["config"]["seed"], {})[job["config"]["schedule"]] = result
        attempts += len(job["attempts"])
    audit = []
    if set(pairs) != {0, 1, 2}:
        raise ValueError("Missing paired seeds")
    for seed, pair in pairs.items():
        if set(pair) != {"cosine", "plateau"}:
            raise ValueError("Missing paired scheduler")
        a, b = pair["cosine"], pair["plateau"]
        for field in ("data_hash", "base_identity", "train_tokens", "supervised_tokens", "sample_exposures"):
            if a[field] != b[field]:
                raise ValueError("Paired training exposure differs: " + field)
        audit.append({"seed": seed, "paired_exposure_equal": True,
                      "supervised_tokens": a["supervised_tokens"], "examples_seen": a["examples_seen"]})
    if audit != matrix["paired_audit"] or attempts != 7:
        raise ValueError("Recorded pair audit or resume attempts differ")
    output = {"kind": "v2_execution_binding_engineering_recomputation", "scope": "engineering",
        "workers": 6, "worker_attempts": attempts, "paired_audit": audit,
        "human_reviews_completed": 0, "formal_9b_training": False,
        "model_weights_reverified": False,
        "warning": "Recomputes saved result/config/exposure records. Tiny temporary weights were checked during the live test but are not archived in this report; this is not persistent model backup or formal training."}
    (root / "verification.json").write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8", newline="\n")
    sums = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and p.name != "checksums.json"}
    (root / "checksums.json").write_text(json.dumps(sums, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"workers": 6, "worker_attempts": attempts, "paired_seeds": len(audit)}, indent=2))


if __name__ == "__main__":
    main()
