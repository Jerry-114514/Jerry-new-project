"""Synthetic signatures test binding enforcement, never human-review completion."""

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_execution_development import development_tasks
from test_protocol import engineering_fixture
from intentlab.core import digest
from intentlab.execution_protocol import validate_execution_binding
from intentlab.formal_data import export_reviewed, read_jsonl, write_jsonl
from intentlab.protocol import check_spec, freeze, verify


def fixture(root, model=None, source=None):
    """All identities, declarations and labels below are synthetic test data."""
    root = Path(root)
    spec = engineering_fixture(root, model, source)
    tasks, reference_rows = development_tasks()
    cases, reviews = [], []
    for task, split in zip(tasks[:4], ("train", "validation", "test", "ood")):
        task["split"] = split
        case = {key: deepcopy(task[key]) for key in ("source_task_id", "family", "split", "template_id", "source")}
        case["source"]["reference"] = "SYNTHETIC UNIT FIXTURE, NOT A HUMAN BENCHMARK"
        case["case_id"] = "unit-view-" + split
        case["public"] = {"request": task["request"], "inputs": deepcopy(task["inputs"]),
            "requirements": deepcopy(task["requirements"]), "execution_spec": deepcopy(task["spec"]),
            "observation": {"files": deepcopy(task["inputs"]), "events": []}}
        cases.append(case)
        for reviewer in ("unit-fixture-a", "unit-fixture-b"):
            reviews.append({"case_id": case["case_id"], "reviewer": reviewer, "human_verified": True,
                            "findings": [{"id": req["id"], "status": "unknown", "evidence": []} for req in task["requirements"]]})
    write_jsonl(spec["dataset"]["cases"], cases)
    write_jsonl(spec["dataset"]["reviews"], reviews)
    spec["dataset"]["export"] = str(root / "reviewed-v2")
    export_reviewed(cases, reviews, [], spec["dataset"]["export"])
    spec["few_shot_case_ids"] = ["unit-view-validation"]
    selected = tasks[2:4]
    selected_refs = [row for row in reference_rows if row["task_id"] in {task["id"] for task in selected}]
    write_jsonl(root / "execution-tasks.jsonl", selected)
    write_jsonl(root / "execution-references.jsonl", selected_refs)
    settings = deepcopy(json.loads(Path("configs/formal-protocol.draft.json").read_text(encoding="utf-8"))["execution"]["settings"])
    spec["schema_version"] = 2
    spec["execution"] = {"tasks": str(root / "execution-tasks.jsonl"), "references": str(root / "execution-references.jsonl"), "settings": settings}
    audit = {"schema_version": 1, "tasks_hash": digest(selected),
        "references_hash": digest({row["task_id"]: row for row in selected_refs}),
        "reviews": [{"task_id": task["id"], "reviewer": reviewer, "human_verified": True,
                     "contract_verified": True, "reference_verified": True, "notes": "SYNTHETIC UNIT FIXTURE ONLY"}
                    for task in selected for reviewer in ("unit-fixture-a", "unit-fixture-b")]}
    Path(spec["evidence"]["execution_and_oracle_audit"]).write_text(json.dumps(audit), encoding="utf-8")
    return spec


class ExecutionProtocolTests(unittest.TestCase):
    def test_valid_v2_records_exact_tasks_and_condition_map(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            spec = fixture(root / "fixture")
            self.assertTrue(check_spec(spec)["ready"])
            lock = freeze(spec, root / "lock.json")
            info = lock["execution_binding"]["summary"]
            self.assertEqual(info["tasks"], 2)
            self.assertEqual(info["condition_map"]["P2"], {"policy": "dynamic-k", "hard_guard": False})
            self.assertEqual(info["condition_map"]["P3"], {"policy": "fixed-full", "hard_guard": True})
            self.assertTrue(verify(lock, "all")["verified"])

    def test_training_verification_never_opens_execution_inputs_or_reference_audit(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            spec = fixture(root / "fixture")
            lock = freeze(spec, root / "lock.json")
            for path in (spec["execution"]["tasks"], spec["execution"]["references"],
                         spec["evidence"]["execution_and_oracle_audit"], spec["dataset"]["reviews"]):
                Path(path).unlink()
            self.assertTrue(verify(lock, "training")["verified"])
            with self.assertRaises(OSError):
                verify(lock, "all")

    def test_changed_reference_after_freeze_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            spec = fixture(root / "fixture")
            lock = freeze(spec, root / "lock.json")
            path = Path(spec["execution"]["references"])
            rows = read_jsonl(path)
            rows[0]["files"]["output/data.json"] = []
            write_jsonl(path, rows)
            self.assertTrue(verify(lock, "training")["verified"])
            with self.assertRaises(ValueError):
                verify(lock, "all")

    def test_changed_public_contract_even_with_updated_audit_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            spec = fixture(name)
            path = Path(spec["execution"]["tasks"])
            rows = read_jsonl(path)
            rows[0]["inputs"]["input/data.json"] = [{"name": "other"}]
            write_jsonl(path, rows)
            audit_path = Path(spec["evidence"]["execution_and_oracle_audit"])
            audit = json.loads(audit_path.read_text())
            audit["tasks_hash"] = digest(rows)
            audit_path.write_text(json.dumps(audit))
            self.assertFalse(check_spec(spec)["ready"])

    def test_duplicate_or_unverified_contract_review_is_rejected(self):
        for kind in ("duplicate", "unverified", "missing"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as name:
                spec = fixture(name)
                path = Path(spec["evidence"]["execution_and_oracle_audit"])
                audit = json.loads(path.read_text())
                if kind == "duplicate":
                    audit["reviews"][1]["reviewer"] = audit["reviews"][0]["reviewer"]
                elif kind == "unverified":
                    audit["reviews"][0]["reference_verified"] = False
                else:
                    audit["reviews"].pop()
                path.write_text(json.dumps(audit))
                self.assertFalse(check_spec(spec)["ready"])

    def test_bad_selection_or_ablation_settings_cannot_freeze(self):
        for key, value in (("checkpoint_selection", "best_test_loss"), ("fixed_k_values", [1]),
                           ("analyzer_seed", True), ("max_tool_steps", False), ("analyzer_mode", "auto")):
            with self.subTest(key=key), tempfile.TemporaryDirectory() as name:
                spec = fixture(name)
                spec["execution"]["settings"][key] = value
                self.assertFalse(check_spec(spec)["ready"])

    def test_legacy_formal_spec_cannot_silently_omit_execution(self):
        with tempfile.TemporaryDirectory() as name:
            spec = engineering_fixture(name)
            spec["scope"] = "formal"
            self.assertIn("Formal protocols require schema_version=2 with an execution binding", check_spec(spec)["blockers"])

    def test_formal_freezer_cannot_pin_a_different_implementation_checkout(self):
        with tempfile.TemporaryDirectory() as name:
            spec = fixture(name)
            spec["scope"] = "formal"
            self.assertIn("Formal source_root must be the active protocol implementation checkout", check_spec(spec)["blockers"])

    def test_multiple_reviewed_variants_keep_the_same_source_group(self):
        with tempfile.TemporaryDirectory() as name:
            spec = fixture(name)
            cases = read_jsonl(spec["dataset"]["cases"])
            tasks = read_jsonl(spec["execution"]["tasks"])
            refs = read_jsonl(spec["execution"]["references"])
            variant = deepcopy(tasks[0])
            variant["id"] += "-unit-variant"
            variant["request"] += " Additional SYNTHETIC UNIT variant."
            tasks.append(variant)
            view = deepcopy(next(case for case in cases if case["source_task_id"] == variant["source_task_id"]))
            view["case_id"] += "-unit-variant"
            view["public"]["request"] = variant["request"]
            cases.append(view)
            ref = deepcopy(refs[0])
            ref["task_id"] = variant["id"]
            refs.append(ref)
            write_jsonl(spec["execution"]["tasks"], tasks)
            write_jsonl(spec["execution"]["references"], refs)
            path = Path(spec["evidence"]["execution_and_oracle_audit"])
            audit = json.loads(path.read_text())
            audit["tasks_hash"] = digest(tasks)
            audit["references_hash"] = digest({row["task_id"]: row for row in refs})
            for reviewer in ("unit-fixture-a", "unit-fixture-b"):
                audit["reviews"].append({"task_id": variant["id"], "reviewer": reviewer, "human_verified": True,
                    "contract_verified": True, "reference_verified": True, "notes": "SYNTHETIC UNIT FIXTURE ONLY"})
            path.write_text(json.dumps(audit))
            result = validate_execution_binding(spec["execution"], cases, path)
            self.assertEqual(result["tasks"], 3)
            self.assertEqual(result["source_task_groups"], 2)
            write_jsonl(spec["execution"]["tasks"], tasks[:-1])
            write_jsonl(spec["execution"]["references"], refs[:-1])
            with self.assertRaisesRegex(ValueError, "variants"):
                validate_execution_binding(spec["execution"], cases, path)


AVAILABLE = all(importlib.util.find_spec(name) for name in ("torch", "transformers", "peft"))


@unittest.skipUnless(AVAILABLE, "Install optional ML dependencies for real v2 worker integration")
class ExecutionMatrixIntegrationTests(unittest.TestCase):
    def test_v2_six_real_workers_resume_without_execution_references_or_reviews(self):
        from intentlab.fixtures import build_tasks
        from intentlab.matrix import run_matrix
        from intentlab.neural import train_neural
        from intentlab.sft_data import export_sft
        from test_neural import configuration
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            export_sft(build_tasks(), root / "base-data")
            train_neural(dict(configuration(root / "base-data"), steps=2, eval_every=1, defer_test=True), root / "base")
            spec = fixture(root / "fixture", root / "base/model", Path(__file__).resolve().parents[1])
            lock = freeze(spec, root / "lock.json")
            for path in (spec["execution"]["tasks"], spec["execution"]["references"],
                         spec["evidence"]["execution_and_oracle_audit"], spec["dataset"]["reviews"]):
                Path(path).unlink()
            for path in (Path(spec["dataset"]["export"]) / "heldout").rglob("gold.jsonl"):
                path.unlink()
            partial = run_matrix(lock, root / "matrix", engineering=True, stop_after_updates=1)
            self.assertEqual(partial["status"], "interrupted")
            complete = run_matrix(lock, root / "matrix", engineering=True, resume=True)
            if complete["status"] != "completed":
                self.fail("\n".join(path.read_text(encoding="utf-8") for path in (root / "matrix").glob("*.log")))
            self.assertEqual(len(complete["paired_audit"]), 3)
            self.assertEqual(len(complete["jobs"][0]["attempts"]), 2)
            self.assertTrue(all(job["status"] == "completed" for job in complete["jobs"]))
            from intentlab.execution_models import bind_execution_models, verify_execution_models
            matrix_file = root / "matrix/matrix.json"
            original_matrix = matrix_file.read_bytes()
            try:
                invalid = deepcopy(complete)
                invalid["status"] = "running"
                matrix_file.write_text(json.dumps(invalid))
                with self.assertRaises(ValueError):
                    bind_execution_models(lock, root / "matrix", root / "incomplete-model-lock.json", engineering=True)
                invalid = deepcopy(complete)
                invalid["jobs"][-1]["config"]["seed"] = 99
                matrix_file.write_text(json.dumps(invalid))
                with self.assertRaises(ValueError):
                    bind_execution_models(lock, root / "matrix", root / "different-plan-model-lock.json", engineering=True)
            finally:
                matrix_file.write_bytes(original_matrix)
            with self.assertRaises(ValueError):
                bind_execution_models(lock, root / "matrix", root / "forbidden-model-lock.json")
            binding = bind_execution_models(lock, root / "matrix", root / "execution-model-lock.json", engineering=True)
            self.assertEqual(binding["selected_job"], "cosine-seed-0")
            self.assertFalse(binding["hidden_inputs_opened"])
            self.assertTrue(verify_execution_models(lock, binding, engineering=True)["verified"])
            # The model binding must continue checking completed export assets.
            proof_path = root / "matrix/cosine-seed-0/model/selection.json"
            original = proof_path.read_bytes()
            try:
                proof_path.write_bytes(original + b" ")
                with self.assertRaises(ValueError):
                    verify_execution_models(lock, binding, engineering=True)
            finally:
                proof_path.write_bytes(original)
            self.assertTrue(verify_execution_models(lock, binding, engineering=True)["verified"])
            target = os.environ.get("INTENTLAB_EXECUTION_MATRIX_AUDIT_DIR")
            if target:
                target = Path(target)
                target.mkdir(parents=True, exist_ok=False)
                shutil.copyfile(root / "lock.json", target / "protocol.engineering.lock.json")
                shutil.copyfile(root / "execution-model-lock.json", target / "execution-model-lock.json")
                for path in (root / "matrix").rglob("*"):
                    if path.is_file() and path.suffix in {".json", ".log"} and "model" not in path.parts:
                        destination = target / path.relative_to(root / "matrix")
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, destination)
                (target / "engineering-scope.json").write_text(json.dumps({
                    "scope": "engineering", "schema_version": 2, "human_reviews_completed": 0,
                    "formal_9b_training": False, "execution_tasks_references_and_reviews_deleted_before_training": True,
                    "warning": "Tiny CPU model and synthetic unit identities, not formal data or human annotation."}, indent=2) + "\n", encoding="utf-8")
