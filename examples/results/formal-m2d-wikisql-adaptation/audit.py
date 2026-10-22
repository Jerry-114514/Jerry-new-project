"""Check public metadata; optionally reconstruct private source and raw runs."""

import argparse
import hashlib
import json
import re
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO))
from intentlab.core import canonical, digest, initial_state
from intentlab.contracts import public_solution
from intentlab.execution import replay_execution
from intentlab.execution_analysis import analyze_execution, execution_scope
from intentlab.execution_oracle import evaluate_execution
from intentlab.formal_data import read_jsonl
from intentlab.model_backend import LanguageModelActor
from intentlab.protocol import source_snapshot
from intentlab.report import summarize
from intentlab.runner import run_task
from scripts.adapt_wikisql_equality import build
from scripts.intake_wikisql import build_pool


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def hashes(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file()}


class RecordedBackend:
    def __init__(self, rows):
        self.rows = list(rows)

    def complete(self, prompt):
        if not self.rows:
            raise ValueError("Replay requested an unrecorded generation")
        row = self.rows.pop(0)
        if row["prompt_hash"] != digest(prompt):
            raise ValueError("Reconstructed actor prompt differs from recorded prompt")
        return row


def replay_smoke(private, tasks, refs, expected):
    if hashes(private) != expected["private_files_sha256"]:
        raise ValueError("Private raw-run files changed")
    records = read_jsonl(private / "runs.jsonl")
    manifest = read(private / "manifest.json")
    assert manifest["policies"] == ["none"] and manifest["max_repairs"] == 0
    assert manifest["redact_events"] is False and manifest["analyzer_mode"] == "rule"
    selected = tasks[:2]
    assert manifest["task_hash"] == digest(selected)
    by_id = {task["id"]: task for task in selected}
    assert len(records) == 2 and {row["task_id"] for row in records} == set(by_id)
    for row in records:
        task = by_id[row["task_id"]]
        backend = RecordedBackend(row["model_pool"]["generations"])
        result = run_task(task, LanguageModelActor(backend, envelope_mode=manifest["actor_envelope"]),
            "none", 0, False, analyzer=analyze_execution,
            hard_guard=manifest["hard_guard_enabled"],
            evaluator=lambda t, s: evaluate_execution(t, s, refs[t["id"]]),
            scope_selector=execution_scope, max_tool_steps=manifest["max_tool_steps"])
        keys = set(result) - {"interaction_seconds", "evaluation_seconds", "elapsed_seconds"}
        assert not backend.rows
        assert canonical({k: result[k] for k in keys}) == canonical({k: row[k] for k in keys})
    replay_execution(selected, refs, records)
    assert canonical(summarize(records)) == canonical(read(private / "summary.json"))
    assert sum(row["cost"]["actor_calls"] for row in records) == expected["actor_calls"]
    assert sum(row["metrics"]["compliant_success"] for row in records) == expected["candidate_reference_compliant_runs"]
    assert sum(row["status"] == "error" for row in records) == expected["program_exceptions"]
    return sum(row["cost"]["actor_calls"] for row in records)


def audit(archive=None, private_smoke=None):
    if private_smoke is not None and archive is None:
        raise ValueError("Raw-run replay requires --archive to reconstruct exact tasks")
    manifest = read(ROOT / "adapter-manifest.json")
    assert manifest["scope"] == "train_development_only"
    assert [manifest[k] for k in ("candidate_tasks", "injected_views", "provisional_page_groups", "shared_project_templates")] == [12, 48, 12, 1]
    assert manifest["human_verified_project_tasks"] == manifest["human_labels_created"] == 0
    assert all(manifest[k] is False for k in ("source_fidelity_review_complete", "release_review_complete", "formal_protocol_frozen"))
    identity = read(ROOT / "runtime-identity.json")
    assert identity["tests"] == 195 and identity["formal_training_started"] is False
    assert source_snapshot(REPO) == identity["source_normalized_sha256"]
    assert identity["official_assets_verified_after_run"]["revision"] == "c202236235762e1c871ad0ccb60c8ee5ba337b9a"
    assert len(identity["official_assets_verified_after_run"]["verified_assets"]) == 13
    for name, ending in (("tests-autodl.log", "OK"), ("tests-local.log", "OK (skipped=10)")):
        log = (ROOT / name).read_text(encoding="utf-8")
        assert re.findall(r"Ran (\d+) tests", log)[-1] == "195" and log.rstrip().endswith(ending)
    assert "GpuBusy" in (ROOT / "execution-smoke.log").read_text(encoding="utf-8")
    package = read(ROOT / "reviewer-package.json")
    assert package["views"] == package["records_per_reviewer"] == 48
    assert package["judgments_per_reviewer"] == 192 and package["human_reviews_completed"] == 0
    assert package["distributed"] is package["source_fidelity_and_release_review_complete"] is False
    assert package["contains_candidate_answers_or_model_results"] is False
    lineage = read_jsonl(ROOT / "lineage-public.jsonl")
    index = {r["candidate_id"]: r for r in read_jsonl(ROOT.parent / "formal-m2c-wikisql-source-intake/pool/public-index.jsonl")}
    assert len(lineage) == len({r["task_id"] for r in lineage}) == 12
    assert len({r["page_hash"] for r in lineage}) == len({r["table_payload_hash"] for r in lineage}) == 12
    for row in lineage:
        assert "private_view_mapping" not in row
        assert row["human_verified"] is row["original_question_fidelity_human_verified"] is False
        assert row["public_clarification_derived_from_upstream_sql_annotation"] is True
        for key in ("upstream_record_sha256", "table_record_sha256"):
            assert row[key] == index[row["source_candidate_id"]][key]
    consistency = read(ROOT / "program-reference-consistency.json")
    assert consistency == {"checked_contracts": 12, "public_rule_matches_separate_sqlite_reference": True, "human_truth_claim": False}
    smoke = read(ROOT / "smoke-summary.json")
    assert [smoke[k] for k in ("tasks", "runs", "actor_calls", "program_exceptions", "candidate_reference_compliant_runs")] == [2, 2, 4, 0, 1]
    assert smoke["human_accuracy"] is None and smoke["formal_M6_complete"] is False
    calls = None
    if archive is not None:
        source = read(REPO / "configs/wikisql-source.json")
        original = read(ROOT.parent / "formal-m2c-wikisql-source-intake/pool/manifest.json")
        with tempfile.TemporaryDirectory() as directory:
            pool, adapted = Path(directory) / "pool", Path(directory) / "adapted"
            rebuilt = build_pool(archive, source, pool, original["requested_candidates"], original["selection_seed"])
            assert canonical(rebuilt) == canonical(original)
            assert canonical(build(pool / "coordinator-pool.jsonl", pool / "manifest.json", adapted)) == canonical(manifest)
            assert hashes(adapted) == read(ROOT / "private-file-sha256.json")
            for name in ("cases.jsonl", "review-template.jsonl", "README.md"):
                assert hashlib.sha256((adapted / "reviewer-packet" / name).read_bytes()).hexdigest() == package["files_sha256"][name]
            blanks = read_jsonl(adapted / "reviewer-packet/review-template.jsonl")
            assert len(blanks) == 48
            assert all(row["human_verified"] is False and row["reviewer"] == "" and
                       len(row["findings"]) == 4 and all(f["status"] == "" and f["evidence"] == [] for f in row["findings"]) for row in blanks)
            stripped = [{k: v for k, v in r.items() if k != "private_view_mapping"}
                        for r in read_jsonl(adapted / "coordinator-lineage.jsonl")]
            assert canonical(stripped) == canonical(lineage)
            tasks = read_jsonl(adapted / "tasks.jsonl")
            refs = {r["task_id"]: r for r in read_jsonl(adapted / "candidate-references.jsonl")}
            for task in tasks:
                state = initial_state(task); state.apply(public_solution(task))
                assert evaluate_execution(task, state, refs[task["id"]])["compliant_success"]
            if private_smoke is not None:
                calls = replay_smoke(Path(private_smoke), tasks, refs, smoke)
    return {"scope": "unreviewed_train_development_adaptation", "candidate_contracts": 12,
        "injected_views": 48, "shared_project_templates": 1, "human_verified_tasks": 0,
        "full_source_and_adapter_rebuilt": archive is not None,
        "recorded_actor_calls_replayed": calls, "fresh_inference_performed": False,
        "formal_training_started": False, "formal_M6_complete": False,
        "warning": "Default checks metadata only. Rebuilding and replaying prove reproducibility, not human truth, original WikiSQL accuracy, task independence or method benefit."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--private-smoke", type=Path)
    args = parser.parse_args()
    result = audit(args.archive, args.private_smoke)
    name = "raw-replay-verification.json" if args.private_smoke else "source-replay-verification.json" if args.archive else "verification.json"
    (ROOT / name).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result, indent=2))
