"""Metadata audit or private reconstruction/replay of twelve development runs."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO))
from intentlab.core import canonical, digest
from intentlab.execution import replay_execution
from intentlab.execution_analysis import analyze_execution, execution_scope
from intentlab.execution_oracle import evaluate_execution
from intentlab.formal_data import annotation_packet, read_jsonl, write_jsonl
from intentlab.model_backend import LanguageModelActor
from intentlab.protocol import source_snapshot
from intentlab.report import summarize
from intentlab.runner import run_task
from intentlab.trajectory_intake import build as intake
from scripts.intake_wikisql import build_pool
from scripts.adapt_wikisql_equality import adapt

prior = runpy.run_path(str(ROOT.parent / "formal-m2d-wikisql-adaptation/audit.py"))
RecordedBackend = prior["RecordedBackend"]
hashes = prior["hashes"]
read = prior["read"]


def replay(tasks, refs, directory):
    records = read_jsonl(directory / "runs.jsonl")
    manifest = read(directory / "manifest.json")
    assert manifest["task_hash"] == digest(tasks)
    assert manifest["offline_reference_hash"] == digest({t["id"]: refs[t["id"]] for t in tasks})
    assert manifest["status"] == "completed" and manifest["policies"] == ["none"]
    assert manifest["max_repairs"] == 0 and manifest["redact_events"] is False
    assert manifest["analyzer_mode"] == "rule" and manifest["actor_envelope"] == "extract"
    by_id = {t["id"]: t for t in tasks}
    assert len(records) == len(tasks) and {r["task_id"] for r in records} == set(by_id)
    for row in records:
        backend = RecordedBackend(row["model_pool"]["generations"])
        result = run_task(by_id[row["task_id"]], LanguageModelActor(backend, envelope_mode="extract"),
            "none", 0, False, analyzer=analyze_execution, hard_guard=manifest["hard_guard_enabled"],
            evaluator=lambda t, s: evaluate_execution(t, s, refs[t["id"]]),
            scope_selector=execution_scope, max_tool_steps=manifest["max_tool_steps"])
        keys = set(result) - {"interaction_seconds", "evaluation_seconds", "elapsed_seconds"}
        assert not backend.rows
        assert canonical({k: result[k] for k in keys}) == canonical({k: row[k] for k in keys})
    replay_execution(tasks, refs, records)
    assert canonical(summarize(records)) == canonical(read(directory / "summary.json"))
    return records


def audit(archive=None, private_root=None):
    if private_root is not None and archive is None:
        raise ValueError("Private replay requires --archive to reconstruct exact tasks")
    launch = read(ROOT / "launch.json")
    assert launch["source_commit"] == "2e127573e6aefb4f51f1c558ce3adb7606ec4b0f"
    assert launch["source_normalized_sha256"] == source_snapshot(REPO)
    assert launch["human_reviews_completed"] == 0 and launch["formal_training_started"] is False
    assets = read(ROOT / "official-assets-after-run.json")
    assert assets["model"] == "Qwen/Qwen3.5-9B"
    assert assets["revision"] == "c202236235762e1c871ad0ccb60c8ee5ba337b9a" and len(assets["verified_assets"]) == 13
    summary = read(ROOT / "collection-summary.json")
    assert summary["runs"] == 12 and summary["previous_runs"] == 2 and summary["new_runs"] == 10
    assert summary["natural_views"] == 24 and summary["shared_templates"] == 1
    assert summary["human_accuracy"] is None and summary["formal_M6_complete"] is False
    manifests = {batch: read(ROOT / (batch + "-intake-manifest.json")) for batch in ("first-two", "remaining-ten")}
    for batch, count in (("first-two", 2), ("remaining-ten", 10)):
        m = manifests[batch]
        assert m["raw_runs"] == count and m["views"] == count * 2
        assert m["splits"] == ["train"] and m["templates"] == 1
        assert m["human_reviews_completed"] == 0 and m["automatic_labels_exported"] is False
        assert m["formal_training_started"] is m["protocol_frozen"] is False
    package = read(ROOT / "reviewer-package.json")
    assert package["views"] == package["records_per_reviewer"] == 24
    assert package["judgments_per_reviewer"] == 96 and package["human_reviews_completed"] == 0
    assert package["distributed"] is False
    assert package["source_fidelity_and_release_review_complete"] is False
    failures = read(ROOT / "failure-audit.json")
    assert failures["schema_error_runs"] == failures["json_parse_error_runs"] == 1
    assert failures["hard_violation_runs"] == failures["error_status_runs"] == 2
    assert failures["all_runs_included_in_denominator"] is True
    calls = None
    if archive is not None:
        with tempfile.TemporaryDirectory() as temporary:
            temp = Path(temporary)
            original = read(ROOT.parent / "formal-m2c-wikisql-source-intake/pool/manifest.json")
            rebuilt = build_pool(archive, read(REPO / "configs/wikisql-source.json"), temp / "pool",
                                 original["requested_candidates"], original["selection_seed"])
            assert canonical(rebuilt) == canonical(original)
            tasks, references, _, _ = adapt(read_jsonl(temp / "pool/coordinator-pool.jsonl"), rebuilt)
            parent = read(ROOT.parent / "formal-m2d-wikisql-adaptation/adapter-manifest.json")
            assert digest(tasks) == parent["tasks_hash"] and digest(references) == parent["references_hash"]
            if private_root is not None:
                private_root = Path(private_root)
                assert hashes(private_root) == read(ROOT / "private-file-sha256.json")
                assert read_jsonl(private_root / "tasks.jsonl") == tasks
                assert read_jsonl(private_root / "candidate-references.jsonl") == references
                refs = {r["task_id"]: r for r in references}
                records, cases = [], []
                for batch, selected in (("first-two", tasks[:2]), ("remaining-ten", tasks[2:])):
                    folder = private_root / batch
                    assert read_jsonl(folder / "tasks.jsonl") == selected
                    records.extend(replay(selected, refs, folder / "execution"))
                    out = temp / batch
                    reproduced = intake(folder / "tasks.jsonl", folder / "execution", out)
                    assert canonical(reproduced) == canonical(manifests[batch])
                    assert hashes(out) == hashes(folder / "intake")
                    cases.extend(read_jsonl(out / "coordinator-cases.jsonl"))
                assert len({r["task_id"] for r in records}) == 12
                assert canonical(summarize(records)) == canonical(read(ROOT / "execution-summary.json"))
                assert sum(r["metrics"]["compliant_success"] for r in records) == summary["candidate_reference_compliant_runs"]
                assert sum(r["status"] == "error" for r in records) == summary["program_exceptions"]
                messages = [h["message"] for r in records for h in r["history"] if h["phase"] == "error"]
                assert messages.count("Tool action does not match the declared schema") == failures["schema_error_runs"]
                assert messages.count("Language model did not return a valid JSON action proposal") == failures["json_parse_error_runs"]
                assert sum(r["metrics"]["hard_violations"] > 0 for r in records) == failures["hard_violation_runs"]
                calls = sum(r["cost"]["actor_calls"] for r in records)
                assert calls == summary["actor_calls"]
                assert len(cases) == len({c["case_id"] for c in cases}) == 24
                annotation_packet(cases, temp / "combined")
                readme = temp / "combined/README.md"
                readme.write_text(readme.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
                for name, fingerprint in hashes(temp / "combined").items():
                    assert fingerprint == package["files_sha256"][name]
                    assert (temp / "combined" / name).read_bytes() == (private_root / "reviewer-packet" / name).read_bytes()
                assert all(r["human_verified"] is False and r["reviewer"] == "" and
                    all(f["status"] == "" and f["evidence"] == [] for f in r["findings"])
                    for r in read_jsonl(temp / "combined/review-template.jsonl"))
    return {"scope": "unreviewed_train_natural_trajectory_collection", "runs": 12, "natural_views": 24,
        "shared_templates": 1, "source_rebuilt": archive is not None,
        "recorded_actor_calls_replayed": calls, "fresh_inference_performed": False,
        "human_reviews_completed": 0, "formal_training_started": False, "formal_M6_complete": False,
        "warning": "Metadata only by default. Natural means recorded actor attempts, not human-authored tasks or independence; references unreviewed. This is not original WikiSQL accuracy or a formal method comparison."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--private-root", type=Path)
    args = parser.parse_args()
    report = audit(args.archive, args.private_root)
    name = "raw-replay-verification.json" if args.private_root else "source-replay-verification.json" if args.archive else "verification.json"
    (ROOT / name).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
