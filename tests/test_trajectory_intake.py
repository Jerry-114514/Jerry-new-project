"""Intake invariants using explicitly synthetic provenance declarations."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from intentlab.core import digest, initial_state
from intentlab.contracts import public_solution
from intentlab.execution_oracle import evaluate_execution
from intentlab.formal_data import read_jsonl, write_jsonl
from intentlab.trajectory_intake import build, extract_views
from scripts.build_training_candidates import training_tasks


def fixture():
    tasks, _ = training_tasks()
    tasks = tasks[:1]
    models = {"actor": "/synthetic-unit-model-not-real"}
    manifest = {"kind": "public_contract_development_execution", "scope": "development", "status": "completed",
        "actor": "local_model", "executor_is_language_model": True, "task_hash": digest(tasks),
        "policies": ["none"], "model_paths": models}
    # Deliberately failed initial attempt. No generated tool actions or truth.
    row = {"task_id": tasks[0]["id"], "source_task_id": tasks[0]["source_task_id"], "split": "train",
        "policy": "none", "actor": "LanguageModelActor", "status": "error",
        "final_state": {"files": deepcopy(tasks[0]["inputs"]), "events": []},
        "metrics": {"NEVER_EXPORT_AUTOMATIC_TRUTH": True}, "history": [{"findings": ["NEVER_EXPORT"]}],
        "model_pool": {"models": models, "generations": [{"role": "actor", "model_path": models["actor"],
            "text": "SYNTHETIC invalid response, not a real model", "prompt_hash": "unit-fixture-only"}]}}
    return tasks, manifest, [row]


class TrajectoryIntakeTests(unittest.TestCase):
    def test_training_variants_are_conservatively_grouped_and_static_references_consistent(self):
        tasks, refs = training_tasks()
        self.assertEqual(len(tasks), 12)
        self.assertEqual(len({task["source_task_id"] for task in tasks}), 4)
        self.assertEqual({task["split"] for task in tasks}, {"train"})
        for task, reference in zip(tasks, refs):
            state = initial_state(task)
            state.apply(public_solution(task))
            # A consistency check, not independent human oracle validation.
            self.assertTrue(evaluate_execution(task, state, reference)["compliant_success"])

    def test_failures_and_two_visibility_views_survive_without_automatic_labels(self):
        tasks, manifest, records = fixture()
        cases, index = extract_views(tasks, manifest, records, "a" * 64)
        self.assertEqual(len(cases), 2)
        self.assertEqual({row["source_task_id"] for row in cases}, {tasks[0]["source_task_id"]})
        self.assertEqual(cases[0]["public"]["observation"]["events"], [])
        self.assertIsNone(cases[1]["public"]["observation"]["events"])
        self.assertNotIn("NEVER_EXPORT", json.dumps(cases))
        self.assertEqual({row["execution_status"] for row in index}, {"error"})

    def test_missing_duplicate_or_foreign_run_rejected(self):
        tasks, manifest, records = fixture()
        for bad in ([], records * 2, [dict(records[0], task_id="unlisted-task")]):
            with self.assertRaisesRegex(ValueError, "coverage"):
                extract_views(tasks, manifest, bad, "a" * 64)

    def test_test_ood_and_scripted_actor_cannot_become_natural_training_data(self):
        for split in ("test", "ood"):
            tasks, manifest, records = fixture()
            tasks[0]["split"] = split
            manifest["task_hash"] = digest(tasks)
            with self.assertRaisesRegex(ValueError, "test/OOD"):
                extract_views(tasks, manifest, records, "a" * 64)
        tasks, manifest, records = fixture()
        manifest["executor_is_language_model"] = False
        with self.assertRaisesRegex(ValueError, "real-model"):
            extract_views(tasks, manifest, records, "a" * 64)

    def test_changed_snapshot_models_or_absent_generation_rejected(self):
        for field in ("snapshot", "models", "generation"):
            tasks, manifest, records = fixture()
            if field == "snapshot":
                records[0]["final_state"]["files"]["extra.json"] = []
            elif field == "models":
                records[0]["model_pool"]["models"] = {"actor": "/different-model"}
            else:
                records[0]["model_pool"]["generations"] = []
            with self.assertRaises(ValueError):
                extract_views(tasks, manifest, records, "a" * 64)

    def test_packet_is_blank_blind_and_immutable_output_does_not_load_references(self):
        tasks, manifest, records = fixture()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_jsonl(root / "tasks.jsonl", tasks)
            write_jsonl(root / "runs.jsonl", records)
            (root / "manifest.json").write_text(json.dumps(manifest))
            (root / "offline-references.jsonl").write_text("MUST NOT BE OPENED AS JSON")
            result = build(root / "tasks.jsonl", root, root / "intake")
            self.assertEqual(result["human_reviews_completed"], 0)
            packet = root / "intake/reviewer-packet"
            self.assertTrue(all(b"\r\n" not in p.read_bytes() for p in (root / "intake").rglob("*") if p.is_file()))
            self.assertEqual(set(read_jsonl(packet / "cases.jsonl")[0]), {"case_id", "public"})
            for row in read_jsonl(packet / "review-template.jsonl"):
                self.assertFalse(row["human_verified"])
                self.assertTrue(all(finding["status"] == "" for finding in row["findings"]))
            self.assertNotIn("NEVER_EXPORT", (packet / "cases.jsonl").read_text())
            with self.assertRaises(FileExistsError):
                build(root / "tasks.jsonl", root, root / "intake")


if __name__ == "__main__":
    unittest.main()
