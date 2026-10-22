"""Controlled candidate counterfactuals, not measured model efficacy."""

from copy import deepcopy
import unittest

from intentlab.candidate_audit import audit_candidates
from intentlab.contracts import public_solution
from intentlab.execution_analysis import analyze_execution, execution_scope
from intentlab.execution_auxiliary import candidate_summary, common_feasibility
from intentlab.frozen_execution import score_records
from intentlab.runner import run_task
from scripts.build_execution_development import development_tasks


class Actor:
    def __init__(self, mode="legitimate"):
        self.mode = mode

    def propose(self, task, state, phase, target=None, attempt=0):
        if phase == "initial":
            return {"actions": [{"op": "validate", "ok": True}], "done": True}
        if self.mode == "proposal_error":
            if phase == "repair_continue":
                raise ValueError("SYNTHETIC proposal failure after one valid tool step")
            return {"actions": [{"op": "write", "path": task["output_path"], "value": []}], "done": False}
        actions = public_solution(task)
        if self.mode == "unsafe":
            actions += [{"op": "write", "path": next(iter(task["inputs"])), "value": next(iter(task["inputs"].values()))}]
        elif self.mode == "partial_then_complete":
            wanted = task["output_path"] if attempt == 0 else task["report_path"]
            actions = [action for action in actions if action.get("path") == wanted]
        return {"actions": actions, "done": True}


def analyzer(mode):
    def inspect(task, state, visible):
        rows = analyze_execution(task, state, visible)
        for row in rows:
            if task["spec"]["requirement_rules"][row["id"]] == "preserve_inputs":
                if mode == "false_pass":
                    row["status"] = "satisfied"
                elif task["output_path"] in state.files and mode == "false_reject":
                    row["status"] = "violated"
        if mode == "decision_error" and task["output_path"] in state.files:
            raise RuntimeError("SYNTHETIC analysis failure after complete candidate submission")
        return rows
    return inspect


def run(actor="legitimate", analysis="truth", guard=True, repairs=1):
    tasks, references = development_tasks()
    task = tasks[0]
    reference = next(row for row in references if row["task_id"] == task["id"])
    raw = run_task(task, Actor(actor), "fixed-full", repairs, analyzer=analyzer(analysis), hard_guard=guard,
                   evaluator=lambda task, state: {}, scope_selector=execution_scope, max_tool_steps=2)
    raw["source_task_id"] = task["source_task_id"]
    scored = score_records([task], {task["id"]: reference}, [raw], candidate_metrics=True)[0]
    return task, reference, raw, scored


class CandidateAuditTests(unittest.TestCase):
    def test_legitimate_candidate_rejected_by_model_gate_counts_false_block(self):
        _, _, _, scored = run(analysis="false_reject")
        trial = scored["candidate_audit"]["candidates"][0]
        self.assertTrue(trial["offline_compliant"])
        self.assertTrue(trial["false_block"])
        self.assertFalse(trial["independent_guard_false_block"])
        self.assertTrue(trial["hard_guard_passed"])
        summary = candidate_summary([scored])
        self.assertEqual(summary["pooled_candidate_false_block_rate"], 1)
        self.assertEqual(summary["counts"]["complete_compliant_candidates"], 1)

    def test_history_input_write_is_noncompliant_even_when_restored(self):
        for guard in (True, False):
            with self.subTest(guard=guard):
                _, _, _, scored = run(actor="unsafe", analysis="false_pass", guard=guard)
                trial = scored["candidate_audit"]["candidates"][0]
                self.assertFalse(trial["offline_compliant"])
                self.assertFalse(trial["false_block"])
                self.assertEqual(trial["accepted"], not guard)
                self.assertTrue(trial["candidate_new_hard_violations"])
                self.assertIsNone(candidate_summary([scored])["pooled_candidate_false_block_rate"])

    def test_incomplete_proposal_stays_in_attempt_count_with_null_truth(self):
        _, _, _, scored = run(actor="proposal_error")
        trial = scored["candidate_audit"]["candidates"][0]
        self.assertFalse(trial["complete_proposal"])
        self.assertIsNone(trial["offline_compliant"])
        summary = candidate_summary([scored])
        self.assertEqual(summary["counts"]["attempts"], 1)
        self.assertEqual(summary["counts"]["incomplete_proposals"], 1)
        self.assertIsNone(summary["pooled_candidate_false_block_rate"])

    def test_decision_error_does_not_remove_complete_compliant_candidate(self):
        _, _, _, scored = run(analysis="decision_error")
        trial = scored["candidate_audit"]["candidates"][0]
        self.assertEqual(scored["status"], "error")
        self.assertTrue(trial["complete_proposal"])
        self.assertEqual(trial["trial_status"], "decision_error")
        self.assertTrue(trial["false_block"])
        self.assertEqual(candidate_summary([scored])["counts"]["decision_error_false_blocks"], 1)

    def test_accepted_partial_progress_is_not_a_false_block_and_replays_commit_order(self):
        _, _, _, scored = run(actor="partial_then_complete", repairs=2)
        candidates = scored["candidate_audit"]["candidates"]
        self.assertEqual(len(candidates), 2)
        self.assertFalse(candidates[0]["offline_compliant"])
        self.assertTrue(candidates[0]["accepted"])
        self.assertTrue(candidates[1]["offline_compliant"])
        self.assertTrue(scored["metrics"]["compliant_success"])
        self.assertEqual(candidate_summary([scored])["pooled_candidate_false_block_rate"], 0)

    def test_missing_markers_or_inconsistent_commits_are_rejected(self):
        task, reference, raw, scored = run()
        changed = deepcopy(raw)
        changed["history"][1]["accepted"] = False
        with self.assertRaises(ValueError):
            audit_candidates(task, reference, changed)
        changed = deepcopy(raw)
        del changed["history"][1]["proposal_complete"]
        with self.assertRaises(ValueError):
            audit_candidates(task, reference, changed)
        del scored["candidate_audit"]
        with self.assertRaises(ValueError):
            candidate_summary([scored])

    def test_common_feasibility_intersection_cannot_compare_separate_denominators(self):
        rows = [{"condition": condition, "split": "test", "task_id": source, "source_task_id": source,
                 "feasible_at_repair_start": (condition, source) in {("P3", "a"), ("P4", "b")},
                 "metrics": {"compliant_success": True}, "repair_introduced_hard_violations": []}
                for condition in ("P3", "P4") for source in ("a", "b")]
        report = common_feasibility(rows, "P3", "P4", "test")
        self.assertEqual(report["counts"]["paired_variants"], 2)
        self.assertEqual(report["counts"]["common_feasible_variants"], 0)
        self.assertEqual(report["counts"]["left_only_feasible_variants"], 1)
        self.assertEqual(report["counts"]["right_only_feasible_variants"], 1)
        self.assertIsNone(report["right_minus_left"])

    def test_common_feasibility_uses_equal_source_weight_for_unequal_variants(self):
        rows = [{"condition": condition, "split": "test", "task_id": source + str(index), "source_task_id": source,
                 "feasible_at_repair_start": True, "metrics": {"compliant_success": (condition, source) in {("P3", "a"), ("P4", "b")}},
                 "repair_introduced_hard_violations": []}
                for condition in ("P3", "P4") for source, count in (("a", 9), ("b", 1)) for index in range(count)]
        report = common_feasibility(rows, "P3", "P4", "test")
        self.assertEqual(report["right_minus_left"], 0)
        self.assertEqual(report["eligible_source_task_groups"], 2)
        self.assertEqual(report["counts"]["common_feasible_variants"], 10)
