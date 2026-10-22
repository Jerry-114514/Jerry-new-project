"""Synthetic oracle-blind P1-P4 control tests; not efficacy experiments."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from intentlab.budget import TokenLedger
from intentlab.contracts import public_solution
from intentlab.core import State, canonical
from intentlab.diagnostic_protocol import generate, reveal as diagnostic_reveal
from intentlab.execution_analysis import analyze_execution
from intentlab.formal_data import read_jsonl
from intentlab.frozen_execution import interact, reveal, verify_scoring
from intentlab.protocol import freeze
from test_diagnostic_protocol import FakeBackend, fake_loss
from test_execution_protocol import fixture


class FakeRole:
    def __init__(self, pool, role):
        self.pool, self.role = pool, role

    def complete(self, prompt):
        value = json.loads(prompt.rsplit("\nJSON:", 1)[0].rsplit("\n", 1)[-1])
        if self.role == "actor":
            task = value["task"]
            actions = ([{"op": "validate", "ok": True}] if value["phase"] == "initial" else
                public_solution(task) + [{"op": "write", "path": next(iter(task["inputs"])),
                                         "value": next(iter(task["inputs"].values()))}])
            text = canonical({"actions": actions, "done": True})
        else:
            public = value["public"]
            task = dict(request=public["request"], inputs=public["inputs"], requirements=public["requirements"],
                spec=public["execution_spec"], output_path="output/data.json", report_path="output/report.json")
            # Fixed paths of this synthetic development fixture only.
            findings = analyze_execution(task, State(public["observation"]["files"], public["observation"]["events"] or []),
                                         public["observation"]["events"] is not None)
            for finding in findings:
                if task["spec"]["requirement_rules"][finding["id"]] == "preserve_inputs":
                    finding.update(status="satisfied", evidence=["request", "snapshot_paths"])
            text = canonical({"findings": [{key: row[key] for key in ("id", "status", "evidence")} for row in findings]})
        ticket, _ = self.pool.ledger.begin(self.role, 1, 1, self.pool.context, "synthetic-unit-prompt")
        self.pool.ledger.finish(ticket, 1)
        return {"text": text, "usage": {"prompt_tokens": 1, "completion_tokens": 1}}


class FakePool:
    def __init__(self, paths, device, max_new_tokens, token_budget, context_limit):
        self.paths = {role: str(Path(path).resolve()) for role, path in paths.items()}
        self.context = context_limit
        self.ledger = TokenLedger(token_budget)

    def reset(self):
        self.ledger.reset()

    def role(self, role):
        return FakeRole(self, role)

    def close(self):
        pass

    def snapshot(self):
        return {"models": self.paths, "resident_model_limit": 1, "context_limit": self.context,
                "shared_token_ledger": self.ledger.snapshot(), "model_loads": [], "generations": []}


def prepare(root):
    spec = fixture(root / "fixture")
    lock = freeze(spec, root / "protocol.json")
    binding = {"binding_hash": "synthetic-unit-no-model-weights", "matrix": {"root": str(root / "matrix")},
               "models": {"actor": lock["models"]["actor"], "analyzer": lock["models"]["analyzer_base"]}}
    generate(lock, binding, root / "predictions", True, FakeBackend)
    diagnostic_reveal(lock, binding, root / "predictions", root / "diagnostics", True, fake_loss)
    return spec, lock, binding


@patch("intentlab.diagnostic_protocol.verify_execution_models", return_value={"verified": True})
class FrozenExecutionTests(unittest.TestCase):
    def test_paired_guard_control_and_all_interactions_before_reference_access(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            spec, lock, binding = prepare(root)
            refs = Path(spec["execution"]["references"])
            original = refs.read_bytes()
            for path in (refs, Path(spec["dataset"]["reviews"]), *Path(spec["dataset"]["export"]).glob("heldout/*/gold.jsonl")):
                path.unlink()
            sealed = interact(lock, binding, root / "predictions", root / "diagnostics", root / "interactions", True, FakePool)
            self.assertEqual(sealed["status"], "sealed")
            rows = read_jsonl(root / "interactions/interactions.jsonl")
            self.assertEqual(len(rows), 8)
            self.assertTrue(all("metrics" not in row and row["offline_metrics_pending"] for row in rows))
            self.assertTrue(all(row["status"] == "finished" for row in rows))
            refs.write_bytes(original)
            real_open, accesses = Path.open, []
            def guarded(path, *args, **kwargs):
                if path == refs:
                    marker = Path(spec["dataset"]["export"]).parent / f"diagnostic-{lock['lock_hash']}-execution-reveal.claim.json"
                    self.assertTrue(marker.exists())
                    accesses.append(True)
                return real_open(path, *args, **kwargs)
            with patch.object(Path, "open", guarded):
                result = reveal(lock, binding, root / "predictions", root / "diagnostics", root / "interactions", root / "scores", True)
            self.assertEqual(result["status"], "completed")
            self.assertTrue(accesses)
            refs.unlink()
            self.assertFalse(verify_scoring(lock, binding, root / "predictions", root / "diagnostics", root / "interactions", root / "scores", True)["references_reopened"])
            scored = read_jsonl(root / "scores/runs.jsonl")
            for row in scored:
                if row["condition"] in {"P1", "P2"}:
                    self.assertTrue(row["repair_introduced_hard_violations"])
                    self.assertTrue(row["metrics"]["task_complete"])
                else:
                    self.assertFalse(row["repair_introduced_hard_violations"])
                    self.assertGreater(row["cost"]["hard_rejections"], 0)
            with self.assertRaises(FileExistsError):
                interact(lock, binding, root / "predictions", root / "diagnostics", root / "other-interactions", True, FakePool)
            with self.assertRaises(FileExistsError):
                reveal(lock, binding, root / "predictions", root / "diagnostics", root / "interactions", root / "other-scores", True)

    def test_missing_m5_receipt_prevents_interaction_claim(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            _, lock, binding = prepare(root)
            (root / "diagnostics/manifest.json").unlink()
            with self.assertRaises(OSError):
                interact(lock, binding, root / "predictions", root / "diagnostics", root / "interactions", True, FakePool)
            self.assertFalse((root / "interactions").exists())

    def test_tampering_is_rejected_before_execution_reference_reveal(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            _, lock, binding = prepare(root)
            interact(lock, binding, root / "predictions", root / "diagnostics", root / "interactions", True, FakePool)
            path = root / "interactions/interactions.jsonl"
            path.write_bytes(path.read_bytes() + b" ")
            with self.assertRaises(ValueError):
                reveal(lock, binding, root / "predictions", root / "diagnostics", root / "interactions", root / "scores", True)
            self.assertFalse((root / "scores").exists())

    def test_wrong_reference_fails_after_claim_without_retry(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            spec, lock, binding = prepare(root)
            interact(lock, binding, root / "predictions", root / "diagnostics", root / "interactions", True, FakePool)
            path = Path(spec["execution"]["references"])
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.assertRaises(ValueError):
                reveal(lock, binding, root / "predictions", root / "diagnostics", root / "interactions", root / "scores", True)
            self.assertEqual(json.loads((root / "scores/manifest.json").read_text())["status"], "failed")
            path.write_bytes(original)
            with self.assertRaises(FileExistsError):
                reveal(lock, binding, root / "predictions", root / "diagnostics", root / "interactions", root / "other", True)

    def test_formal_pool_injection_is_rejected(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            _, lock, binding = prepare(root)
            lock = deepcopy(lock)
            lock["scope"] = "formal"
            with self.assertRaisesRegex(ValueError, "Injected"):
                interact(lock, binding, root / "predictions", root / "diagnostics", root / "interactions", pool_factory=FakePool)
