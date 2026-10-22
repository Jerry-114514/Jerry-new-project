"""Controlled M7 stage/isolation checks; synthetic data and injected models."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from intentlab.core import digest
from intentlab.diagnostic_protocol import generate, reveal as reveal_diagnostics
from intentlab.formal_data import read_jsonl
from intentlab.frozen_execution import interact as interact_m6, reveal as reveal_m6
from intentlab.frozen_ablation import interact, reveal, verify_interactions, verify_scoring
from intentlab.protocol import freeze
from test_controller_plan import prepare_controller_plan
from test_diagnostic_protocol import FakeBackend, fake_loss
from test_execution_protocol import fixture
from test_frozen_execution import FakePool


def prepare(root, with_m6=True):
    spec = fixture(root / "fixture")
    prepare_controller_plan(spec, root, FakePool)
    lock = freeze(spec, root / "protocol.json")
    binding = {"binding_hash": "synthetic-unit-no-model-weights", "matrix": {"root": str(root / "matrix")},
               "models": {"actor": lock["models"]["actor"], "analyzer": lock["models"]["analyzer_base"]}}
    generate(lock, binding, root / "predictions", True, FakeBackend)
    reveal_diagnostics(lock, binding, root / "predictions", root / "diagnostics", True, fake_loss)
    if with_m6:
        interact_m6(lock, binding, root / "predictions", root / "diagnostics", root / "m6-interactions", True, FakePool)
        reveal_m6(lock, binding, root / "predictions", root / "diagnostics", root / "m6-interactions", root / "m6-reveal", True)
    return spec, lock, binding


def arguments(root, lock, binding):
    return lock, binding, root / "predictions", root / "diagnostics", root / "m6-interactions", root / "m6-reveal"


@patch("intentlab.diagnostic_protocol.verify_execution_models", return_value={"verified": True})
class FrozenAblationTests(unittest.TestCase):
    def test_all_controls_and_private_file_isolation_and_stage_claims(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            spec, lock, binding = prepare(root)
            refs = Path(spec["execution"]["references"])
            original = refs.read_bytes()
            for path in (refs, Path(spec["dataset"]["reviews"]), *Path(spec["dataset"]["export"]).glob("heldout/*/gold.jsonl")):
                path.unlink()
            for record in lock["controller_binding"]["files"].values():
                Path(record["path"]).unlink()
            common = arguments(root, lock, binding)
            manifest = interact(*common, root / "interactions", True, FakePool)
            self.assertEqual(manifest["kind"], "frozen_ablation_interactions")
            self.assertEqual(manifest["upstream"]["strong_fixed_condition"], "fixed-k-1")
            rows = read_jsonl(root / "interactions/interactions.jsonl")
            self.assertEqual(len(rows), 12)
            self.assertEqual(len({row["condition"] for row in rows}), 6)
            self.assertTrue(all(row["hard_guard_enabled"] and row["status"] == "finished" and "metrics" not in row for row in rows))
            for row in rows:
                if row["condition"].startswith("fixed-k-"):
                    self.assertTrue(all(step["intensity_decision"]["requested_k"] == int(row["condition"][-1])
                        for step in row["history"] if step["phase"] == "repair"))
            refs.write_bytes(original)
            real_open, accesses = Path.open, []
            def guarded(path, *args, **kwargs):
                if path == refs:
                    marker = Path(spec["dataset"]["export"]).parent / f"diagnostic-{lock['lock_hash']}-ablation-reveal.claim.json"
                    self.assertTrue(marker.exists())
                    accesses.append(True)
                return real_open(path, *args, **kwargs)
            with patch.object(Path, "open", guarded):
                receipt = reveal(*common, root / "interactions", root / "scores", True)
            self.assertEqual(receipt["kind"], "frozen_ablation_reveal")
            self.assertTrue(accesses)
            refs.unlink()
            self.assertFalse(verify_scoring(*common, root / "interactions", root / "scores", True)["references_reopened"])
            self.assertEqual(len(json.loads((root / "scores/summary.json").read_text())), 6)
            with self.assertRaises(FileExistsError):
                interact(*common, root / "other-interactions", True, FakePool)
            with self.assertRaises(FileExistsError):
                reveal(*common, root / "interactions", root / "other-scores", True)

    def test_no_m6_completion_prevents_any_ablation_claim(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            _, lock, binding = prepare(root, with_m6=False)
            with self.assertRaises(OSError):
                interact(*arguments(root, lock, binding), root / "interactions", True, FakePool)
            self.assertFalse((root / "interactions").exists())

    def test_missing_controller_binding_prevents_ablation_claim(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            _, lock, binding = prepare(root)
            altered = deepcopy(lock)
            del altered["controller_binding"]
            with self.assertRaisesRegex(ValueError, "controller binding"):
                interact(*arguments(root, altered, binding), root / "interactions", True, FakePool)
            self.assertFalse((root / "interactions").exists())

    def test_sealed_condition_override_is_rejected_even_if_rehashed(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            _, lock, binding = prepare(root)
            common = arguments(root, lock, binding)
            interact(*common, root / "interactions", True, FakePool)
            path = root / "interactions/manifest.json"
            manifest = json.loads(path.read_text())
            manifest["conditions"]["fixed-k-1"]["hard_guard"] = False
            manifest["seal_hash"] = digest({key: value for key, value in manifest.items() if key != "seal_hash"})
            path.write_text(json.dumps(manifest))
            with self.assertRaises(ValueError):
                verify_interactions(*common, root / "interactions", True)
