from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_execution_development import development_tasks

from intentlab.intensity import DEFAULT_INTENSITY, choose_intensity, validate_intensity
from intentlab.execution_analysis import ContractRuleActor, analyze_execution
from intentlab.execution_audit import audit_intensity, audit_records
from intentlab.execution import run_execution
from intentlab.execution_oracle import evaluate_execution
from intentlab.runner import run_task


class IntensityTests(unittest.TestCase):
    def setUp(self):
        self.tasks, references = development_tasks()
        self.references = {row["task_id"]: row for row in references}
        self.task = self.tasks[0]
        self.config = deepcopy(DEFAULT_INTENSITY)

    def test_exact_thresholds_weights_and_root_bound(self):
        task = {"requirements": [{"id": str(i), "hard": False} for i in range(4)],
                "spec": {"dependencies": {str(i): [] for i in range(4)}}}
        rows = [{"id": str(i), "hard": False, "status": "satisfied"} for i in range(4)]
        self.assertEqual(choose_intensity(task, rows, "dynamic-k", self.config)["requested_k"], 1)
        rows[0]["status"] = "violated"
        at_quarter = choose_intensity(task, rows, "dynamic-k", self.config)
        self.assertEqual(at_quarter["requested_k"], 2)
        self.assertEqual(at_quarter["selected_root_count"], 1)
        rows[1]["status"] = "violated"
        self.assertEqual(choose_intensity(task, rows, "dynamic-k", self.config)["requested_k"], 3)
        rows[0]["status"], rows[1]["status"] = "unknown", "unknown"
        decision = choose_intensity(task, rows, "dynamic-k", self.config)
        self.assertEqual(decision["severity_index"], 0.25)
        self.assertEqual(decision["roots"], [])  # Unknown is observed, never silently repaired as violated.
        task["requirements"][0]["hard"] = rows[0]["hard"] = True
        rows[0]["status"] = "violated"
        self.assertEqual(choose_intensity(task, rows, "dynamic-k", self.config)["weighted_failure_mass"], 2.5)

    def test_both_arms_share_order_and_transitive_dependencies(self):
        task = {"requirements": [{"id": rid, "hard": rid == "c"} for rid in "abcd"],
                "spec": {"dependencies": {"a": [], "b": [], "c": ["d"], "d": ["a"]}}}
        rows = [{"id": req["id"], "hard": req["hard"], "status": "violated", "risk_score": -999}
                for req in reversed(task["requirements"])]
        fixed = choose_intensity(task, rows, "fixed-k", self.config)
        dynamic = choose_intensity(task, rows, "dynamic-k", self.config)
        self.assertEqual(fixed["roots"], ["c"])
        self.assertEqual(dynamic["roots"][:1], fixed["roots"])
        self.assertEqual(fixed["target"], ["a", "c", "d"])
        self.assertGreater(fixed["expanded_target_count"], fixed["requested_k"])
        altered = deepcopy(task)
        altered["oracle"] = {"fake": True}
        self.assertEqual(fixed, choose_intensity(altered, rows, "fixed-k", self.config))

    def test_invalid_config_and_public_findings_fail_closed(self):
        for key, value in [("fixed_k", True), ("max_k", 0), ("thresholds", [0.5, 0.25]),
                           ("thresholds", [0.25, float("nan")]), ("hard_weight", float("inf")),
                           ("unknown_weight", -1), ("schema_version", True)]:
            config = deepcopy(self.config)
            config[key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                validate_intensity(config)
        rows = [{"id": req["id"], "hard": req["hard"], "status": "satisfied"} for req in self.task["requirements"]]
        for bad in (rows[:-1], rows[:-1] + [rows[0]], [dict(row, hard=not row["hard"]) for row in rows]):
            with self.assertRaises(ValueError):
                choose_intensity(self.task, bad, "dynamic-k", self.config)

    def test_controlled_joint_repair_and_decision_tamper_audit(self):
        class Actor(ContractRuleActor):
            def propose(self, task, state, phase, target=None, attempt=0):
                if phase == "initial":
                    return {"actions": [{"op": "validate", "ok": True}]}
                return super().propose(task, state, phase, target, attempt)
        records = []
        for policy in ("fixed-k", "dynamic-k"):
            row = run_task(self.task, Actor(), policy, analyzer=analyze_execution,
                evaluator=lambda task, state: evaluate_execution(task, state, self.references[task["id"]]),
                intensity_config=self.config)
            records.append(row)
            self.assertEqual(audit_intensity(self.task, row, {"intensity_config": self.config}), row["cost"]["actor_calls"] - 1)
        # Controlled failure: choosing the report alone cannot repair missing data.
        self.assertFalse(records[0]["metrics"]["compliant_success"])
        self.assertTrue(records[1]["metrics"]["compliant_success"])
        self.assertEqual(records[1]["history"][1]["intensity_decision"]["requested_k"], 2)
        # A stronger fixed count also repairs jointly; do not claim adaptivity
        # from comparison against the deliberately weak fixed-one arm alone.
        fixed_two = run_task(self.task, Actor(), "fixed-k", analyzer=analyze_execution,
            evaluator=lambda task, state: evaluate_execution(task, state, self.references[task["id"]]),
            intensity_config=dict(self.config, fixed_k=2))
        self.assertTrue(fixed_two["metrics"]["compliant_success"])
        self.assertEqual(fixed_two["cost"]["actor_calls"], records[1]["cost"]["actor_calls"])
        records[1]["history"][1]["intensity_decision"]["requested_k"] = 1
        with self.assertRaises(ValueError):
            audit_intensity(self.task, records[1], {"intensity_config": self.config})

    def test_k_arms_share_hidden_history_acquisition_and_no_oracle_in_loop(self):
        calls = []
        def judge(task, state):
            calls.append("judge")
            return evaluate_execution(task, state, self.references[task["id"]])
        def analyzer(task, state, visible):
            self.assertEqual(calls, [])
            return analyze_execution(task, state, visible)
        for policy in ("fixed-k", "dynamic-k"):
            calls.clear()
            result = run_task(self.task, ContractRuleActor(), policy, redact_events=True,
                analyzer=analyzer, evaluator=judge, intensity_config=self.config)
            self.assertEqual(result["cost"]["verifications"], 1)
            self.assertEqual(result["cost"]["checks"], 2)
            self.assertEqual(calls, ["judge", "judge"])

    def test_driver_requires_config_and_audits_all_k_runs(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            with self.assertRaises(ValueError):
                run_execution(self.tasks, self.references, root / "bad", rule_actor=True, policies=["dynamic-k"])
            self.assertFalse((root / "bad").exists())
            result = run_execution(self.tasks, self.references, root / "run", rule_actor=True,
                policies=["fixed-k", "dynamic-k"], intensity_config=self.config)
            records = [json.loads(line) for line in (root / "run/runs.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(audit_records(self.tasks, self.references, result["manifest"], records)["runs"], 16)
            records[0]["intensity_config"]["fixed_k"] = 2
            with self.assertRaises(ValueError):
                audit_records(self.tasks, self.references, result["manifest"], records)

    def test_intensity_never_bypasses_the_shared_hard_guard(self):
        class UnsafeActor(ContractRuleActor):
            def propose(self, task, state, phase, target=None, attempt=0):
                if phase == "initial":
                    return {"actions": [{"op": "validate", "ok": True}]}
                actions = super().propose(task, state, phase, target, attempt)["actions"]
                return {"actions": actions + [{"op": "write", "path": "input/data.json", "value": []}]}
        def false_pass(task, state, visible):
            rows = analyze_execution(task, state, visible)
            rows[0]["status"] = "satisfied"
            return rows
        for policy in ("fixed-k", "dynamic-k"):
            with self.subTest(policy=policy):
                row = run_task(self.task, UnsafeActor(), policy, analyzer=false_pass,
                    evaluator=lambda task, state: evaluate_execution(task, state, self.references[task["id"]]),
                    intensity_config=self.config)
                self.assertEqual(row["cost"]["hard_rejections"], 3)
                self.assertEqual(row["repair_introduced_hard_violations"], [])
                self.assertFalse(row["metrics"]["compliant_success"])
