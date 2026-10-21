"""Export supervised text pairs without putting hidden labels in model inputs."""

import argparse
import json
from pathlib import Path

from .analysis import analyze
from .core import canonical, digest, load_tasks, public_task
from .fixtures import diagnostic_states
from .oracle import evaluate
from .report import save_json
from .requirements import extract_requirements


def analysis_prompt(task, state, events_visible=True):
    observation = {"files": state.files, "events": state.events if events_visible else None}
    return ("Inspect the user requirements and observed execution. Return only JSON with findings. "
            "Each finding needs id, status (satisfied/violated/unknown), and evidence event indices. "
            "Unknown history is not proof of compliance.\n"
            + canonical({"task": public_task(task), "observation": observation}) + "\nJSON:\n")


def export_sft(tasks, out):
    out.mkdir(parents=True, exist_ok=True)
    groups = {name: [] for name in ("train", "validation", "test")}
    for task in tasks:
        requirements = extract_requirements(task["request"])
        for kind, state in diagnostic_states(task).items():
            truth = evaluate(task, state)["requirements"]
            for visible in (True, False):
                observed = analyze(public_task(task), state, visible)
                findings = []
                for item in observed:
                    status = ("unknown" if item["status"] == "unknown" else
                              "satisfied" if truth[item["id"]] else "violated")
                    findings.append({"id": item["id"], "status": status,
                                     "evidence": item["evidence"]})
                groups[task["split"]].append({"task_id": task["id"], "family": task["family"],
                    "kind": kind, "events_visible": visible, "requirements": requirements,
                    "prompt": analysis_prompt(task, state, visible),
                    "completion": canonical({"findings": findings})})
    for split, records in groups.items():
        with (out / f"{split}.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
            for record in records:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    save_json(out / "manifest.json", {"task_hash": digest(tasks), "counts": {k: len(v) for k, v in groups.items()},
        "source": "synthetic executed diagnostic trajectories", "split_unit": "operation family",
        "warning": "Synthetic supervision; original test is a smoke holdout, not a newly human-verified benchmark."})
    return groups


def read_pairs(path):
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows:
        raise ValueError("Empty SFT dataset")
    for row in rows:
        if not all(isinstance(row.get(k), str) and row[k] for k in ("task_id", "prompt", "completion")):
            raise ValueError("SFT record requires task_id, prompt and completion")
    return rows


def validate_splits(splits):
    seen = {}
    for split, rows in splits.items():
        for row in rows:
            if row["task_id"] in seen and seen[row["task_id"]] != split:
                raise ValueError("SFT task group leaked across splits")
            seen[row["task_id"]] = split


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", type=Path, default=Path("data/tasks.json"))
    parser.add_argument("--out", type=Path, default=Path("data/sft"))
    args = parser.parse_args()
    groups = export_sft(load_tasks(args.tasks), args.out)
    print(json.dumps({k: len(v) for k, v in groups.items()}))


if __name__ == "__main__":
    main()
