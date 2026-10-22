"""Synthetic protocol fixtures exercise enforcement, never human review claims."""

from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import socket
import shutil
import tempfile
import unittest
from unittest.mock import patch

from intentlab.formal_data import export_reviewed, write_jsonl
from intentlab.matrix import configurations, process_exists, recover_lock, run_matrix
from intentlab.matrix_worker import wait_for_ack
from intentlab.protocol import EVIDENCE, check_spec, freeze, read_json, verify
from test_formal_data import case, review


def engineering_fixture(root, model=None, source=None):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cases, reviews = [], []
    for split in ("train", "validation", "test", "ood"):
        row = case("fixture-" + split, split, "source-" + split, "template-" + split, "family-" + split)
        row["public"]["request"] += " SYNTHETIC unit fixture " + split + "."
        cases.append(row)
        reviews += [review(row["case_id"], "unit-fixture-a"), review(row["case_id"], "unit-fixture-b")]
    write_jsonl(root / "cases.jsonl", cases)
    write_jsonl(root / "reviews.jsonl", reviews)
    export_reviewed(cases, reviews, [], root / "reviewed")
    if model is None:
        model = root / "fake-model"
        model.mkdir()
        for name in ("config.json", "tokenizer.json"):
            (model / name).write_text("{}", encoding="utf-8")
        (model / "chat_template.jinja").write_text("{{ fixture }}", encoding="utf-8")
        (model / "model.safetensors").write_bytes(b"unit-test-placeholder-not-a-model")
    if source is None:
        source = root / "source"
        (source / "intentlab").mkdir(parents=True)
        (source / "intentlab/neural.py").write_text("# unit fixture; not executed\n", encoding="utf-8")
    evidence = {}
    for name in EVIDENCE:
        path = root / (name + ".txt")
        path.write_text("SYNTHETIC UNIT TEST EVIDENCE. Not a human review or formal readiness result.\n", encoding="utf-8")
        evidence[name] = str(path)
    return {"schema_version": 1, "scope": "engineering", "source_root": str(source),
        "dataset": {"cases": str(root / "cases.jsonl"), "reviews": str(root / "reviews.jsonl"),
                    "adjudications": None, "export": str(root / "reviewed")},
        "models": {"actor": str(model), "analyzer_base": str(model)},
        "training": {"revision": None, "mode": "full", "device": "cpu", "steps": 2, "eval_every": 1,
            "batch_size": 1, "accumulation": 2, "max_length": 2048, "lr": 0.001, "minimum_lr": 0.000005,
            "rank": 4, "alpha": 8, "limit": 0, "threads": 1, "defer_test": True},
        "seeds": [0, 1, 2], "schedules": ["cosine", "plateau"],
        "minimum_tasks": {name: 1 for name in ("train", "validation", "test", "ood")},
        "conditions": ["A", "B", "C", "D", "E", "P1", "P2", "P3", "P4"],
        "few_shot_case_ids": ["fixture-validation"],
        "statistics": {"unit": "source_task_id", "primary": "RQ1", "primary_scoring": "normalized",
            "secondary_correction": "holm", "seed_reporting": "separate", "bootstrap_samples": 2000,
            "bootstrap_seed": 20261022, "confidence_level": 0.95},
        "budgets": {"token_budget": 8192, "max_new_tokens": 512, "max_repairs": 3, "context_limit": 2048},
        "evidence": evidence, "dependencies": []}


class ProtocolTests(unittest.TestCase):
    def test_draft_with_missing_reviews_and_evidence_cannot_freeze(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            spec = engineering_fixture(root / "fixture")
            Path(spec["dataset"]["reviews"]).unlink()
            report = check_spec(spec)
            self.assertFalse(report["ready"])
            with self.assertRaises(ValueError):
                freeze(spec, root / "lock.json")
            self.assertFalse((root / "lock.json").exists())

    def test_reviewed_manifest_cannot_hide_modified_supervision(self):
        with tempfile.TemporaryDirectory() as name:
            spec = engineering_fixture(name)
            training = Path(spec["dataset"]["export"]) / "train.jsonl"
            row = json.loads(training.read_text(encoding="utf-8"))
            row["completion"] = '{"findings":[]}'
            write_jsonl(training, [row])
            self.assertFalse(check_spec(spec)["ready"])

    def test_training_verification_never_opens_sealed_gold_or_reviews(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            spec = engineering_fixture(root / "fixture")
            lock = freeze(spec, root / "lock.json")
            gold = Path(spec["dataset"]["export"]) / "heldout/test/gold.jsonl"
            # Hide every annotation input and heldout gold after freezing. Train
            # preflight must remain independent of labels used only offline.
            gold.unlink()
            Path(spec["dataset"]["reviews"]).unlink()
            self.assertTrue(verify(lock, "training")["verified"])
            with self.assertRaises(OSError):
                verify(lock, "all")

    def test_changed_tokenizer_source_or_lock_is_rejected(self):
        for target in ("tokenizer", "chat_template", "source", "lock"):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as name:
                root = Path(name)
                spec = engineering_fixture(root / "fixture")
                lock = freeze(spec, root / "lock.json")
                if target == "tokenizer":
                    (Path(spec["models"]["actor"]) / "tokenizer.json").write_text('{"changed":true}', encoding="utf-8")
                elif target == "chat_template":
                    (Path(spec["models"]["actor"]) / "chat_template.jinja").write_text("{{ changed }}", encoding="utf-8")
                elif target == "source":
                    (Path(spec["source_root"]) / "intentlab/neural.py").write_text("# changed\n", encoding="utf-8")
                else:
                    lock["spec"]["training"]["lr"] = 1.0
                with self.assertRaises(ValueError):
                    verify(lock)

    def test_engineering_fixture_cannot_run_as_formal_matrix(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            lock = freeze(engineering_fixture(root / "fixture"), root / "lock.json")
            self.assertEqual(len(configurations(lock)), 6)
            with self.assertRaises(ValueError):
                run_matrix(lock, root / "matrix")

    def test_lock_recovery_requires_both_supervisor_and_child_missing(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            (root / "matrix.lock").write_text(json.dumps({"pid": 123, "host": socket.gethostname()}))
            (root / "matrix.json").write_text(json.dumps({"jobs": [{"status": "running", "pid": 456,
                                                                   "host": socket.gethostname()}]}))
            with patch("intentlab.matrix.process_exists", side_effect=[False, True]):
                with self.assertRaises(RuntimeError):
                    recover_lock(root)
            self.assertTrue((root / "matrix.lock").exists())
            with patch("intentlab.matrix.process_exists", return_value=False):
                self.assertTrue(recover_lock(root)["previous_process_verified_missing"])
            self.assertFalse((root / "matrix.lock").exists())

    def test_worker_never_starts_for_missing_or_other_process_ack(self):
        with tempfile.TemporaryDirectory() as name:
            ack = Path(name) / "attempt.ack.json"
            with self.assertRaises(TimeoutError):
                wait_for_ack(ack, timeout=0)
            ack.write_text(json.dumps({"pid": os.getpid() + 1, "attempt": "attempt"}))
            with self.assertRaises(ValueError):
                wait_for_ack(ack)
            ack.write_text(json.dumps({"pid": os.getpid(), "attempt": "attempt"}))
            wait_for_ack(ack)
        self.assertTrue(process_exists(os.getpid()))


AVAILABLE = all(importlib.util.find_spec(name) for name in ("torch", "transformers", "peft"))


@unittest.skipUnless(AVAILABLE, "Install optional ML dependencies for real matrix integration")
class MatrixIntegrationTests(unittest.TestCase):
    def test_six_real_training_processes_resume_without_test_access(self):
        from intentlab.neural import train_neural
        from intentlab.fixtures import build_tasks
        from intentlab.sft_data import export_sft
        from test_neural import configuration
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            export_sft(build_tasks(), root / "base-data")
            train_neural(dict(configuration(root / "base-data"), steps=2, eval_every=1, defer_test=True), root / "base")
            source = Path(__file__).resolve().parents[1]
            spec = engineering_fixture(root / "fixture", root / "base/model", source)
            lock = freeze(spec, root / "lock.json")
            # Delete gold and reviews entirely: neither scheduler nor any of the
            # six real children may read them during training or resumption.
            Path(spec["dataset"]["reviews"]).unlink()
            for path in (Path(spec["dataset"]["export"]) / "heldout").rglob("gold.jsonl"):
                path.unlink()
            partial = run_matrix(lock, root / "matrix", engineering=True, stop_after_updates=1)
            self.assertEqual(partial["status"], "interrupted")
            self.assertFalse((root / "matrix/matrix.lock").exists())
            with self.assertRaises(ValueError):
                run_matrix(lock, root / "matrix", engineering=True)
            completed = run_matrix(lock, root / "matrix", resume=True, engineering=True)
            if completed["status"] != "completed":
                logs = "\n".join(path.read_text(encoding="utf-8") for path in (root / "matrix").glob("*.log"))
                self.fail(logs)
            self.assertEqual(len(completed["paired_audit"]), 3)
            self.assertTrue(all(job["status"] == "completed" for job in completed["jobs"]))
            self.assertEqual(len(completed["jobs"][0]["attempts"]), 2)
            artifact_dir = os.environ.get("INTENTLAB_MATRIX_AUDIT_DIR")
            if artifact_dir:
                # Explicit engineering evidence export. Never publish synthetic
                # reviewer declarations as completed human annotation records.
                target = Path(artifact_dir)
                target.mkdir(parents=True, exist_ok=False)
                shutil.copyfile(root / "lock.json", target / "protocol.engineering.lock.json")
                for path in (root / "matrix").rglob("*"):
                    if path.is_file() and path.suffix in {".json", ".log"} and "model" not in path.parts:
                        relative = path.relative_to(root / "matrix")
                        destination = target / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(path, destination)
                (target / "engineering-scope.json").write_text(json.dumps({
                    "scope": "engineering", "human_reviews_completed": 0,
                    "formal_9b_training": False, "test_gold_and_reviews_deleted_before_training": True,
                    "warning": "Synthetic unit fixtures and a tiny model; no formal data or human annotation claim."},
                    indent=2) + "\n", encoding="utf-8")
