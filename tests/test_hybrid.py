from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_execution_development import development_tasks
from intentlab.core import initial_state
from intentlab.execution_analysis import ContractRuleActor, HybridExecutionAnalyzer, analyze_execution
from intentlab.execution_oracle import evaluate_execution
from intentlab.runner import run_task


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.tasks, refs = development_tasks()
        self.task = self.tasks[0]
        self.refs = {row["task_id"]: row for row in refs}

    @staticmethod
    def false_pass(task, state, events_visible=True):
        return [{"id": row["id"], "hard": row["hard"], "status": "satisfied", "evidence": [], "reason": "injected_false_pass"}
                for row in task["requirements"]]

    def test_false_pass_missing_outputs_now_triggers_repair(self):
        class Actor(ContractRuleActor):
            def propose(self, task, state, phase, target=None, attempt=0):
                if phase == "initial":
                    return {"actions": [{"op": "validate", "ok": True}]}
                return super().propose(task, state, phase, target, attempt)
        def judge(task, state):
            return evaluate_execution(task, state, self.refs[task["id"]])
        pure = run_task(self.task, Actor(), "fixed-full", analyzer=self.false_pass, evaluator=judge)
        hybrid = HybridExecutionAnalyzer(self.false_pass)
        fixed = run_task(self.task, Actor(), "fixed-full", analyzer=hybrid, evaluator=judge)
        self.assertFalse(pure["metrics"]["compliant_success"])
        self.assertEqual(pure["cost"]["actor_calls"], 1)
        self.assertTrue(fixed["metrics"]["compliant_success"])
        self.assertEqual(fixed["cost"]["actor_calls"], 2)
        self.assertEqual({item["id"] for item in hybrid.decisions[0]["overrides"]}, {"R_RESULT", "R_REPORT"})
        self.assertTrue(all(row["status"] == "satisfied" for row in hybrid.decisions[0]["model_findings"]))

    def test_hidden_history_never_becomes_proved_by_model_confidence(self):
        analyzer = HybridExecutionAnalyzer(self.false_pass)
        rows = analyzer(self.task, initial_state(self.task), False)
        self.assertEqual([row["status"] for row in rows], ["unknown", "unknown", "violated", "violated"])
        self.assertEqual(analyzer.decisions[0]["model_findings"][0]["status"], "satisfied")

    def test_public_rule_gate_equality_is_explicit_and_no_private_answers(self):
        for task in self.tasks:
            state = initial_state(task)
            altered = deepcopy(task)
            altered["oracle"] = {"wrong": "must never be read"}
            merged = HybridExecutionAnalyzer(self.false_pass)(altered, state)
            rules = analyze_execution(task, state)
            self.assertEqual([(row["id"], row["status"], row["evidence"]) for row in merged],
                             [(row["id"], row["status"], row["evidence"]) for row in rules])

    def test_model_analysis_errors_are_retained_and_bad_coverage_rejected(self):
        class FailedSchema:
            errors = ["invented evidence"]
            def __call__(self, task, state, events_visible):
                return [dict(row, status="unknown", evidence=[]) for row in HybridTests.false_pass(task, state)]
        analyzer = HybridExecutionAnalyzer(FailedSchema())
        rows = analyzer(self.task, initial_state(self.task))
        self.assertEqual(analyzer.errors, ["invented evidence"])
        self.assertTrue(any(row["status"] == "violated" for row in rows))
        with self.assertRaises(ValueError):
            HybridExecutionAnalyzer(lambda *args: [])(self.task, initial_state(self.task))
