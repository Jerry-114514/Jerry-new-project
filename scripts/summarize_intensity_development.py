"""Rebuild the M1e development bundle; not a general confirmatory analysis."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.execution_audit import audit_records
from intentlab.execution_data import load_execution_tasks, load_references
from intentlab.formal_data import read_jsonl
from intentlab.report import summarize


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("examples/results/formal-m1e-intensity"))
    parser.add_argument("--source-root", type=Path, help="Exact interaction source snapshot; defaults to the bundled snapshot")
    args = parser.parse_args()
    root = args.root
    tasks = load_execution_tasks(root / "inputs/tasks.jsonl")
    references = load_references(root / "inputs/offline-references.jsonl", tasks)
    reports = {}
    for name in ("model", "controlled/fixed-1", "controlled/fixed-2", "controlled/fixed-3"):
        directory = root / name
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        rows = read_jsonl(directory / "runs.jsonl")
        audit = audit_records(tasks, references, manifest, rows)
        if summarize(rows) != json.loads((directory / "summary.json").read_text(encoding="utf-8")):
            raise ValueError("Summary differs from raw records: " + name)
        reports[name] = {"audit": audit, "summary": summarize(rows),
            "repair_opportunity_runs": sum(any(step["phase"] == "repair" for step in row["history"]) for row in rows),
            "intensity_decisions": [step["intensity_decision"] for row in rows for step in row["history"] if step["phase"] == "repair"]}
    identity = json.loads((root / "runtime-identity.json").read_text(encoding="utf-8"))
    source = args.source_root or root / "interaction-source"
    runtime = {name: sha for name, sha in identity["source_normalized_utf8_sha256"].items() if name.startswith("intentlab/")}
    if not runtime or any(hashlib.sha256((source / name).read_text(encoding="utf-8").encode("utf-8")).hexdigest() != sha for name, sha in runtime.items()):
        raise ValueError("Run this report at its matching interaction implementation")
    output = {"kind": "intensity_development_recomputation", "scope": "development", "runtime_modules_verified": len(runtime),
        "runs": sum(row["audit"]["runs"] for row in reports.values()), "source_task_groups": len({task["source_task_id"] for task in tasks}),
        "conditions": reports, "warning": "Repeated public development tasks and controlled injected omissions. Human reviews: 0. No confirmatory or adaptive-efficiency claim."}
    (root / "verification.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    checksums = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                 for path in sorted(root.rglob('*')) if path.is_file() and path.name != 'checksums.json'}
    (root / "checksums.json").write_text(json.dumps(checksums, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"runs": output["runs"], "source_task_groups": output["source_task_groups"],
                      "runtime_modules_verified": len(runtime), "files_hashed": len(checksums)}, indent=2))


if __name__ == "__main__":
    main()
