"""Extract unlabeled training/development views from recorded real-model runs.

This verifies replay and provenance consistency, not human identity, source
independence, model authenticity, or the semantic correctness of a reference.
It never loads offline references or transfers automatic judgments to reviewers.
"""

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .core import canonical, digest, replay_events
from .execution_data import load_execution_tasks, validate_tasks
from .formal_data import annotation_packet, read_jsonl, validate_cases, write_jsonl


def extract_views(tasks, manifest, records, raw_sha256):
    validate_tasks(tasks)
    if any(task["split"] not in {"train", "validation"} for task in tasks):
        raise ValueError("Development intake cannot publish or reuse test/OOD")
    if manifest.get("kind") != "public_contract_development_execution" or manifest.get("scope") != "development" \
            or manifest.get("status") != "completed" or manifest.get("actor") != "local_model" \
            or manifest.get("executor_is_language_model") is not True or manifest.get("task_hash") != digest(tasks):
        raise ValueError("Completed matching real-model development execution required")
    if not isinstance(raw_sha256, str) or len(raw_sha256) != 64 or any(c not in "0123456789abcdef" for c in raw_sha256):
        raise ValueError("Exact raw record SHA256 required")
    expected = {(policy, task["id"]) for policy in manifest["policies"] for task in tasks}
    actual = [(row["policy"], row["task_id"]) for row in records]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("Complete unique task/policy coverage required; retain failures")
    by_id = {task["id"]: task for task in tasks}
    cases, index = [], []
    for number, row in enumerate(records):
        task = by_id[row["task_id"]]
        pool = row.get("model_pool", {})
        if row.get("actor") != "LanguageModelActor" or row.get("split") != task["split"] \
                or row.get("source_task_id") != task["source_task_id"] \
                or pool.get("models") != manifest["model_paths"]:
            raise ValueError("Actor, source, split or model provenance changed")
        generations = pool.get("generations", [])
        if not isinstance(generations, list) or any(generation.get("role") != "actor"
                or generation.get("model_path") != manifest["model_paths"]["actor"]
                or not isinstance(generation.get("text"), str)
                or not isinstance(generation.get("prompt_hash"), str) for generation in generations):
            raise ValueError("Training intake requires preserved actor-only raw generations")
        if not generations and not pool.get("shared_token_ledger", {}).get("failed_reservations", 0):
            raise ValueError("No recorded generation or failed generation reservation")
        state = replay_events(task, row["final_state"]["events"])
        if canonical(state.files) != canonical(row["final_state"]["files"]):
            raise ValueError("Natural trajectory final snapshot does not replay")
        for visibility in ("events", "snapshot"):
            cid = "natural-" + digest([raw_sha256, number, visibility])[:24]
            source = deepcopy(task["source"])
            source.update(trajectory="natural", reference=source["reference"] + f"; raw-sha256:{raw_sha256}#row:{number}")
            cases.append({"case_id": cid, "source_task_id": task["source_task_id"], "split": task["split"],
                "family": task["family"], "template_id": task["template_id"], "source": source,
                "public": {"request": task["request"], "inputs": deepcopy(task["inputs"]),
                    "requirements": deepcopy(task["requirements"]), "execution_spec": deepcopy(task["spec"]),
                    "observation": {"files": deepcopy(state.files), "events": deepcopy(state.events) if visibility == "events" else None}}})
            index.append({"case_id": cid, "raw_record_index": number, "raw_record_hash": digest(row),
                          "task_id": task["id"], "policy": row["policy"], "visibility": visibility,
                          "execution_status": row["status"], "generation_count": len(generations)})
    validate_cases(cases)
    return cases, index


def build(tasks_path, execution_directory, out):
    tasks_path, execution_directory, out = Path(tasks_path), Path(execution_directory), Path(out)
    manifest_path, raw_path = execution_directory / "manifest.json", execution_directory / "runs.jsonl"
    tasks = load_execution_tasks(tasks_path)
    execution = json.loads(manifest_path.read_text(encoding="utf-8"))
    raw = raw_path.read_bytes()
    cases, index = extract_views(tasks, execution, read_jsonl(raw_path), hashlib.sha256(raw).hexdigest())
    # No output is created until coverage/provenance/replay validation succeeds.
    out.mkdir(parents=True, exist_ok=False)
    write_jsonl(out / "coordinator-cases.jsonl", cases)
    write_jsonl(out / "coordinator-provenance.jsonl", index)
    annotation_packet(cases, out / "reviewer-packet")
    # The shared packet writer follows platform text newlines. This archived
    # intake must reproduce byte-for-byte on Windows and Linux before hashing.
    readme = out / "reviewer-packet/README.md"
    readme.write_text(readme.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    result = {"kind": "unreviewed_natural_training_intake", "schema_version": 1, "scope": "development",
        "human_reviews_completed": 0, "protocol_frozen": False, "formal_training_started": False,
        "execution_manifest_hash": digest(execution), "raw_records_sha256": hashlib.sha256(raw).hexdigest(),
        "tasks_sha256": hashlib.sha256(tasks_path.read_bytes()).hexdigest(), "raw_runs": len(index) // 2,
        "views": len(cases), "requirement_judgments_per_reviewer": sum(len(row["public"]["requirements"]) for row in cases),
        "declared_source_clusters": len({row["source_task_id"] for row in cases}),
        "templates": len({row["template_id"] for row in cases}), "splits": sorted({row["split"] for row in cases}),
        "automatic_labels_exported": False,
        "warning": "Natural refers to recorded actor attempts, including failures, not human-authored tasks or proven independent sources. Two views share each raw run. No oracle, metrics, analyzer findings, method identity or raw model answer is in reviewer packets. Semantic dedup/provenance/release and independent human review remain required."}
    result["files_sha256"] = {p.relative_to(out).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in out.rglob("*") if p.is_file()}
    (out / "manifest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                                        encoding="utf-8", newline="\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", type=Path, required=True)
    parser.add_argument("--execution", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.tasks, args.execution, args.out), indent=2))


if __name__ == "__main__":
    main()
