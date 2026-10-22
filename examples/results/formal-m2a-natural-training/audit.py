"""Replay public train-only raw model responses, tool actions and blank packets."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from intentlab.core import canonical, digest
from intentlab.execution import replay_execution
from intentlab.execution_analysis import analyze_execution, execution_scope
from intentlab.execution_data import load_execution_tasks, load_references
from intentlab.execution_oracle import evaluate_execution
from intentlab.formal_data import read_jsonl
from intentlab.model_backend import LanguageModelActor
from intentlab.report import summarize
from intentlab.runner import run_task
from intentlab.trajectory_intake import build


class RecordedBackend:
    def __init__(self, generations):
        self.generations = list(generations)

    def complete(self, prompt):
        if not self.generations:
            raise AssertionError("Replay asked for an unrecorded model generation")
        row = self.generations.pop(0)
        if row["prompt_hash"] != digest(prompt):
            raise AssertionError("Raw model response does not match the reconstructed public prompt")
        return row


def audit(root):
    root = Path(root)
    tasks = load_execution_tasks(root / "tasks.jsonl")
    refs = load_references(root / "offline-references.jsonl", tasks)
    records = read_jsonl(root / "execution/runs.jsonl")
    manifest = json.loads((root / "execution/manifest.json").read_text(encoding="utf-8"))
    if manifest["policies"] != ["none"] or manifest["max_repairs"] != 0 or manifest["redact_events"]:
        raise ValueError("Expected initial-attempt train-only collection")
    by_id = {task["id"]: task for task in tasks}
    calls = 0
    for row in records:
        task = by_id[row["task_id"]]
        backend = RecordedBackend(row["model_pool"]["generations"])
        actor = LanguageModelActor(backend, envelope_mode=manifest["actor_envelope"])
        result = run_task(task, actor, "none", 0, False, analyzer=analyze_execution,
            hard_guard=manifest["hard_guard_enabled"], evaluator=lambda t, s: evaluate_execution(t, s, refs[t["id"]]),
            scope_selector=execution_scope, max_tool_steps=manifest["max_tool_steps"])
        if backend.generations:
            raise ValueError("Unused raw model generations in replay")
        keys = set(result) - {"interaction_seconds", "evaluation_seconds", "elapsed_seconds"}
        if canonical({key: result[key] for key in keys}) != canonical({key: row[key] for key in keys}):
            raise ValueError("Raw generations do not reproduce recorded actor parsing, tools, findings or metrics")
        calls += row["cost"]["actor_calls"]
    replay = replay_execution(tasks, refs, records)
    if canonical(summarize(records)) != canonical(json.loads((root / "execution/summary.json").read_text(encoding="utf-8"))):
        raise ValueError("Summary differs from preserved records")
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "reproduced"
        result = build(root / "tasks.jsonl", root / "execution", out)
        archived = root / "annotation-intake"
        if {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()} != \
                {p.relative_to(archived).as_posix() for p in archived.rglob("*") if p.is_file()}:
            raise ValueError("Annotation artifact coverage changed")
        for p in out.rglob("*"):
            if p.is_file() and p.read_bytes() != (archived / p.relative_to(out)).read_bytes():
                raise ValueError("Blind packet/provenance differs from raw-run reproduction: " + str(p.relative_to(out)))
    return {"scope": "development", "raw_model_prompt_response_calls_replayed": calls,
        "tool_runs_replayed": replay["replayed"], "unlabeled_views_reproduced": result["views"],
        "declared_conservative_clusters": result["declared_source_clusters"], "human_reviews_completed": 0,
        "formal_training_started": False,
        "warning": "Recorded raw-response replay, not fresh model inference or proof of independent tasks/human reference correctness. Only public synthetic train data."}


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    report = audit(root)
    (root / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    sums = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and p.name != "checksums.json" and "__pycache__" not in p.parts}
    (root / "checksums.json").write_text(json.dumps(sums, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
