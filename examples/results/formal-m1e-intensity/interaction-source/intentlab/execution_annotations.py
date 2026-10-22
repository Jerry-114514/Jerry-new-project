"""Reconstruct and deduplicate blind annotation views from real tool records.

Offline references, model findings, acceptance decisions and evaluation labels
are never included in a reviewer's packet.
"""

import argparse
from copy import deepcopy
import json
from pathlib import Path

from .core import canonical, digest, initial_state
from .execution_data import load_execution_tasks, validate_tasks
from .formal_data import annotation_packet, read_jsonl, validate_cases, write_jsonl
from .report import save_json


def export_execution_annotations(tasks, sources, out):
    validate_tasks(tasks)
    by_id = {task["id"]: task for task in tasks}
    views, provenance = {}, {}
    records_count = 0
    for source in sources:
        records = source["records"]
        ids = {record["task_id"] for record in records}
        if not ids <= set(by_id):
            raise ValueError("Unknown recorded execution task")
        selected_tasks = [task for task in tasks if task["id"] in ids]
        if source["manifest"]["task_hash"] not in {digest(tasks), digest(selected_tasks)}:
            raise ValueError("Annotation task definitions differ from executed inputs")
        for record in records:
            records_count += 1
            task = by_id[record["task_id"]]
            state = initial_state(task)
            visible = not source["manifest"]["redact_events"]
            def emit(observed, history_index):
                public = {"request": task["request"], "inputs": deepcopy(task["inputs"]),
                    "requirements": deepcopy(task["requirements"]), "execution_spec": deepcopy(task["spec"]),
                    "observation": {"files": deepcopy(observed.files), "events": deepcopy(observed.events) if visible else None}}
                fingerprint = digest(public)
                cid = task["id"] + "-trace-" + fingerprint[:16]
                if cid in views and canonical(views[cid]["public"]) != canonical(public):
                    raise ValueError("Annotation view fingerprint collision")
                row = {"case_id": cid, "source_task_id": task["source_task_id"], "family": task["family"],
                    "split": task["split"], "template_id": task["template_id"],
                    "source": {**deepcopy(task["source"]), "reference": "execution trace; separate audit provenance",
                               "trajectory": "natural" if record["actor"] == "LanguageModelActor" else "injected"},
                    "public": public}
                if cid not in views or record["actor"] == "LanguageModelActor":
                    views[cid] = row
                provenance.setdefault(cid, []).append({"source": source["name"], "task_id": task["id"],
                    "policy": record["policy"], "history_index": history_index})
            for index, step in enumerate(record["history"]):
                if step["phase"] == "initial":
                    state.apply(step["actions"])
                    emit(state, index)
                elif step["phase"] == "verify":
                    visible = True
                    emit(state, index)
                elif step["phase"] == "repair":
                    candidate = state.clone()
                    candidate.apply(step["actions"])
                    emit(candidate, index)
                    if step["accepted"]:
                        state = candidate
            if canonical(state.files) != canonical(record["final_state"]["files"]) or canonical(state.events) != canonical(record["final_state"]["events"]):
                raise ValueError("Reconstructed committed execution differs from raw record")
            emit(state, len(record["history"]))
    cases = list(views.values())
    if not cases:
        raise ValueError("No execution views to annotate")
    validate_cases(cases)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    write_jsonl(out / "cases.jsonl", cases)
    annotation_packet(cases, out / "packet")
    save_json(out / "private-provenance.json", provenance)
    manifest = {"kind": "unreviewed_execution_annotation_candidates", "views": len(cases),
        "recorded_runs": records_count, "source_task_groups": len({case["source_task_id"] for case in cases}),
        "human_reviews_completed": 0, "case_hash": digest(cases),
        "warning": "Only give packet/ to independent reviewers. Keep model results and private provenance separate. More views do not create independent tasks."}
    save_json(out / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--records", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    sources = [{"name": str(path), "records": read_jsonl(path),
                "manifest": json.loads((path.parent / "manifest.json").read_text(encoding="utf-8"))}
               for path in args.records]
    print(json.dumps(export_execution_annotations(load_execution_tasks(args.tasks), sources, args.out), indent=2))


if __name__ == "__main__":
    main()
