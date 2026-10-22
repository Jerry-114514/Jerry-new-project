"""Recompute the two preserved 32-run development failure bundles."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.execution_audit import audit_records
from intentlab.execution_data import load_execution_tasks, load_references
from intentlab.formal_data import read_jsonl


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("examples/results/formal-m1g-resource-audit"))
    args = parser.parse_args()
    root = args.root
    tasks = load_execution_tasks(root / "inputs/tasks.jsonl")
    refs = load_references(root / "inputs/offline-references.jsonl", tasks)
    results = {}
    for name in ("3b-executor", "9b-actor-3b-analyzer"):
        directory = root / "failures" / name
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        records = read_jsonl(directory / "runs.jsonl")
        if len(records) != 32 or any(row["status"] != "error" for row in records):
            raise ValueError("Preserved failure bundle no longer matches the reported 32 errors")
        replay = audit_records(tasks, refs, manifest, records)
        errors = Counter(step["message"] for row in records for step in row["history"] if step["phase"] == "error")
        results[name] = {"audit": replay, "error_messages": dict(errors)}
    lease = json.loads((root / "gpu-lease-audit.json").read_text(encoding="utf-8"))
    if lease.get("owner_cuda_allocation_and_reuse") is not True or not lease.get("managed_second_backend_refused") or not lease.get("legacy_cuda_child_refused"):
        raise ValueError("Missing actual CUDA lease audit evidence")
    output = {"kind": "preserved_resource_failure_recomputation", "scope": "engineering", "runs": 64,
        "conditions": results, "warning": "Development failures retained, not formal milestone completion or efficacy evidence."}
    (root / "verification.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    sums = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file() and p.name != 'checksums.json'}
    (root / "checksums.json").write_text(json.dumps(sums, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({name: {"runs": row["audit"]["runs"], "errors": sum(row["error_messages"].values())}
                      for name, row in results.items()}, indent=2))


if __name__ == "__main__":
    main()
