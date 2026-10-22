"""Isolation/attempt semantics with clearly synthetic backend and review fixtures."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from intentlab.budget import TokenLedger
from intentlab.diagnostic_protocol import CONDITIONS, backend_for, generate, reveal, verify_predictions, verify_reveal
from intentlab.protocol import freeze
from test_execution_protocol import fixture


class FakeBackend:
    def __init__(self, path, **kwargs):
        self.ledger = TokenLedger(kwargs["token_budget"])
        self.context = kwargs["context_limit"]

    def reset(self):
        self.ledger.reset()

    def complete(self, prompt, role):
        # Invalid interface is retained in denominators; no fabricated accuracy.
        return {"text": "{}", "usage": {"prompt_tokens": 0, "completion_tokens": 0}}

    def close(self):
        pass


def fake_loss(protocol, path, cases, gold):
    return [{"case_id": row["case_id"], "source_task_id": row["source_task_id"], "split": row["split"],
             "loss_sum": 12.0, "target_tokens": 6} for row in cases]


class DiagnosticProtocolTests(unittest.TestCase):
    def setup_fixture(self, root):
        spec = fixture(root / "fixture")
        lock = freeze(spec, root / "protocol.json")
        binding = {"binding_hash": "unit-placeholder-no-real-weights", "matrix": {"root": str(root / "matrix")}}
        return spec, lock, binding

    def test_every_formal_adapter_must_use_frozen_original_base_before_loading(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            _, lock, _ = self.setup_fixture(root)
            lock["scope"] = "formal"
            adapter = root / "redirected-adapter"
            adapter.mkdir()
            (adapter / "adapter_config.json").write_text(json.dumps({"peft_type": "LORA", "base_model_name_or_path": str(root / "other-base")}))
            with self.assertRaisesRegex(ValueError, "frozen original base"):
                backend_for(lock, adapter)

    @patch("intentlab.diagnostic_protocol.verify_execution_models", return_value={"verified": True})
    def test_nine_conditions_generate_without_gold_then_claim_precedes_reveal(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            spec, lock, binding = self.setup_fixture(root)
            hidden = [Path(spec["dataset"]["reviews"]), Path(spec["execution"]["references"]),
                      Path(spec["evidence"]["execution_and_oracle_audit"])]
            gold_paths = list(Path(spec["dataset"]["export"]).glob("heldout/*/gold.jsonl"))
            saved = {p: p.read_bytes() for p in gold_paths}
            for path in hidden + gold_paths:
                path.unlink()
            manifest = generate(lock, binding, root / "predictions", True, FakeBackend)
            self.assertEqual(manifest["status"], "sealed")
            self.assertEqual(manifest["conditions"], CONDITIONS)
            self.assertFalse(manifest["gold_loaded"])
            self.assertEqual(verify_predictions(lock, binding, root / "predictions", True)[0], manifest)
            with self.assertRaises(FileExistsError):
                generate(lock, binding, root / "different-predictions", True, FakeBackend)
            for path, raw in saved.items():
                path.write_bytes(raw)
            original = Path.open
            reads = []
            def guarded(path, *args, **kwargs):
                if path in saved:
                    marker = Path(spec["dataset"]["export"]).parent / f"diagnostic-{lock['lock_hash']}-reveal.claim.json"
                    self.assertTrue(marker.is_file())
                    reads.append(str(path))
                return original(path, *args, **kwargs)
            with patch.object(Path, "open", guarded):
                receipt = reveal(lock, binding, root / "predictions", root / "scores", True, fake_loss)
            self.assertEqual(receipt["status"], "completed")
            self.assertTrue(reads)
            scores = json.loads((root / "scores/scores.json").read_text())
            self.assertEqual(scores["A"]["test"]["task_mean_error_rate"], 1.0)
            self.assertEqual(json.loads((root / "scores/losses.json").read_text())["D-seed-0"]["test"]["loss"], 2.0)
            for path in saved:
                path.unlink()
            self.assertFalse(verify_reveal(lock, binding, root / "predictions", root / "scores", True)["gold_reopened"])
            with self.assertRaises(FileExistsError):
                reveal(lock, binding, root / "predictions", root / "other-scores", True, fake_loss)
            loss_path = root / "scores/D-seed-0-loss.jsonl"
            loss_path.write_bytes(loss_path.read_bytes() + b" ")
            with self.assertRaises(ValueError):
                verify_reveal(lock, binding, root / "predictions", root / "scores", True)

    @patch("intentlab.diagnostic_protocol.verify_execution_models", return_value={"verified": True})
    def test_sealed_raw_prediction_tampering_rejected_before_gold_claim(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            _, lock, binding = self.setup_fixture(root)
            generate(lock, binding, root / "predictions", True, FakeBackend)
            path = root / "predictions/D-seed-0/predictions.jsonl"
            path.write_text(path.read_text() + "\n")
            with self.assertRaises(ValueError):
                reveal(lock, binding, root / "predictions", root / "scores", True, fake_loss)
            self.assertFalse((root / "scores").exists())

    @patch("intentlab.diagnostic_protocol.verify_execution_models", return_value={"verified": True})
    def test_failed_claim_is_preserved_and_cannot_restart_at_another_output(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            spec, lock, binding = self.setup_fixture(root)
            Path(spec["execution"]["tasks"]).write_text("changed")
            with self.assertRaises(ValueError):
                generate(lock, binding, root / "predictions", True, FakeBackend)
            self.assertEqual(json.loads((root / "predictions/manifest.json").read_text())["status"], "failed")
            with self.assertRaises(FileExistsError):
                generate(lock, binding, root / "other", True, FakeBackend)

    @patch("intentlab.diagnostic_protocol.verify_execution_models", return_value={"verified": True})
    def test_test_backend_cannot_be_used_in_formal_scope(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            _, lock, binding = self.setup_fixture(root)
            altered = deepcopy(lock)
            altered["scope"] = "formal"
            with self.assertRaisesRegex(ValueError, "Injected"):
                generate(altered, binding, root / "predictions", backend_factory=FakeBackend)
            self.assertFalse((root / "predictions").exists())

    @patch("intentlab.diagnostic_protocol.verify_execution_models", return_value={"verified": True})
    def test_gold_change_fails_after_durable_reveal_marker_and_preserves_failure(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            spec, lock, binding = self.setup_fixture(root)
            generate(lock, binding, root / "predictions", True, FakeBackend)
            path = Path(spec["dataset"]["export"]) / "heldout/test/gold.jsonl"
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaises(ValueError):
                reveal(lock, binding, root / "predictions", root / "scores", True, fake_loss)
            self.assertEqual(json.loads((root / "scores/manifest.json").read_text())["status"], "failed")

    @patch("intentlab.diagnostic_protocol.verify_execution_models", return_value={"verified": True})
    def test_unequal_target_tokens_across_models_rejected(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            _, lock, binding = self.setup_fixture(root)
            generate(lock, binding, root / "predictions", True, FakeBackend)
            def inconsistent(protocol, path, cases, gold):
                rows = fake_loss(protocol, path, cases, gold)
                if "seed-1" in path:
                    rows[0]["target_tokens"] += 1
                return rows
            with self.assertRaisesRegex(ValueError, "populations"):
                reveal(lock, binding, root / "predictions", root / "scores", True, inconsistent)
            self.assertTrue((root / "scores/D-seed-0-loss.jsonl").exists())
