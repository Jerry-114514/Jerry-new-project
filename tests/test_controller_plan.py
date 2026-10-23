"""Synthetic development-selection fixtures are never real human review."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from intentlab.controller_plan import absolute_record_path, condition_map, file_hash, rank_fixed_arms, run_selection, validate_selection
from intentlab.core import digest
from intentlab.formal_data import read_jsonl
from intentlab.protocol import check_spec, freeze, verify
from test_execution_protocol import fixture
from test_frozen_execution import FakePool
from build_execution_development import development_tasks


def prepare_controller_plan(spec, root, pool_factory=None):
    root = Path(root)
    cases = read_jsonl(spec["dataset"]["cases"])
    sources = {row["source_task_id"] for row in cases if row["split"] == "validation"}
    tasks, rows = development_tasks()
    tasks = [task for task in tasks if task["source_task_id"] in sources]
    for task in tasks:
        task["split"] = "validation"
    references = {row["task_id"]: row for row in rows if row["task_id"] in {task["id"] for task in tasks}}
    result = run_selection(tasks, references, {"actor": spec["models"]["actor"], "analyzer": spec["models"]["analyzer_base"]},
        spec["execution"]["settings"], spec["budgets"], root / "controller-development", engineering=True, pool_factory=pool_factory)
    path = root / "controller-development/selection.json"
    plan = {"schema_version": 1, "stage": "first_stage_execution_intensity",
        "selection_report": {"path": str(path.resolve()), "sha256": file_hash(path)},
        "risk_controls": ["remove_hard_weight", "remove_unknown_weight"],
        "lr_risk_feedback": "deferred_exploratory_requires_new_unseen_test",
        "reviewers": [{"reviewer": name, "human_verified": True, "notes": "SYNTHETIC UNIT DECLARATION; NOT HUMAN REVIEW"}
                      for name in ("unit-controller-a", "unit-controller-b")]}
    Path(spec["evidence"]["controller_ablation_audit"]).write_text(json.dumps(plan), encoding="utf-8")
    return result


class ControllerPlanTests(unittest.TestCase):
    def test_gpu_refusal_is_preserved_then_aborts_selection_without_ranking(self):
        from intentlab.gpu_lease import GpuBusy
        class BusyPool(FakePool):
            def role(self, role):
                class BusyRole:
                    def complete(self, prompt):
                        raise GpuBusy("Other CUDA compute processes are active (PIDs 123)")
                return BusyRole()
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            spec = fixture(root / "fixture")
            with self.assertRaises(GpuBusy):
                prepare_controller_plan(spec, root, BusyPool)
            report = json.loads((root / "controller-development/selection.json").read_text())
            self.assertEqual(report["status"], "failed")
            self.assertNotIn("selection", report)
            arm = root / "controller-development/fixed-k-1"
            self.assertEqual(json.loads((arm / "manifest.json").read_text())["status"], "failed")
            rows = read_jsonl(arm / "runs.jsonl")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["history"][-1]["error_type"], "GpuBusy")
            self.assertFalse((root / "controller-development/fixed-k-2").exists())

    def test_rank_weights_source_tasks_equally_then_tokens_then_k(self):
        self.assertTrue(absolute_record_path("/root/model"))
        self.assertTrue(absolute_record_path("D:/model"))
        self.assertFalse(absolute_record_path("model"))
        self.assertFalse(absolute_record_path("D:model"))
        def row(source, success, tokens):
            return {"source_task_id": source, "metrics": {"compliant_success": success},
                    "model_pool": {"shared_token_ledger": {"charged_tokens": tokens}}}
        arms = [{"k": 1, "records": [row("a", True, 20)] * 9 + [row("b", False, 20)]},
                {"k": 2, "records": [row("a", False, 10)] * 9 + [row("b", True, 10)]}]
        result = rank_fixed_arms(arms)
        self.assertEqual(result["selected_k"], 2)
        self.assertEqual([score["source_task_mean_compliant_success"] for score in result["scores"]], [0.5, 0.5])
        tied = [{"k": k, "records": [row("a", False, 10)]} for k in (3, 2, 1)]
        self.assertEqual(rank_fixed_arms(tied)["selected_k"], 1)

    def test_development_report_binds_and_training_does_not_read_controller_files(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            spec = fixture(root / "fixture")
            report = prepare_controller_plan(spec, root, FakePool)
            self.assertTrue(check_spec(spec)["ready"])
            lock = freeze(spec, root / "lock.json")
            self.assertEqual(lock["controller_binding"]["selection"], report["selection"])
            conditions = condition_map(lock["controller_binding"], spec["execution"]["settings"])
            self.assertEqual(len(conditions), 6)
            self.assertTrue(all(config["hard_guard"] for config in conditions.values()))
            self.assertEqual(conditions["dynamic-k-remove_hard_weight"]["intensity"]["hard_weight"], 1)
            self.assertEqual(conditions["dynamic-k-remove_unknown_weight"]["intensity"]["unknown_weight"], 0)
            self.assertTrue(verify(lock, "all")["verified"])
            for record in lock["controller_binding"]["files"].values():
                Path(record["path"]).unlink()
            Path(spec["dataset"]["reviews"]).unlink()
            self.assertTrue(verify(lock, "training")["verified"])
            with self.assertRaises(OSError):
                verify(lock, "all")

    def test_invalid_or_heldout_selection_cannot_be_accepted_after_rehash(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            spec = fixture(root / "fixture")
            report = prepare_controller_plan(spec, root, FakePool)
            settings, cases = spec["execution"]["settings"], read_jsonl(spec["dataset"]["cases"])
            for change in ("heldout", "missing_arm", "unguarded", "metrics", "wrong_selection", "different_models", "boolean_k", "boolean_schema"):
                altered = deepcopy(report)
                if change == "heldout":
                    altered["tasks"][0]["split"] = "test"
                elif change == "missing_arm":
                    altered["arms"].pop()
                elif change == "unguarded":
                    altered["arms"][0]["records"][0]["hard_guard_enabled"] = False
                elif change == "metrics":
                    altered["arms"][0]["records"][0]["metrics"]["compliant_success"] = True
                elif change == "wrong_selection":
                    altered["selection"]["selected_k"] = 3
                elif change == "different_models":
                    altered["model_assets_after"]["actor"]["path"] += "-other"
                elif change == "boolean_k":
                    altered["arms"][0]["k"] = True
                else:
                    altered["schema_version"] = True
                altered["report_hash"] = digest({k: v for k, v in altered.items() if k != "report_hash"})
                with self.subTest(change=change), self.assertRaises(ValueError):
                    validate_selection(altered, settings, cases)
            with self.assertRaises(ValueError):
                validate_selection(report, settings, cases, formal=True)

    def test_changed_selection_file_and_incomplete_risk_controls_block_freeze(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            spec = fixture(root / "fixture")
            prepare_controller_plan(spec, root, FakePool)
            path = root / "controller-development/selection.json"
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            self.assertFalse(check_spec(spec)["ready"])
            path.write_bytes(original)
            plan_path = Path(spec["evidence"]["controller_ablation_audit"])
            plan = json.loads(plan_path.read_text())
            plan["risk_controls"].pop()
            plan_path.write_text(json.dumps(plan))
            self.assertFalse(check_spec(spec)["ready"])
