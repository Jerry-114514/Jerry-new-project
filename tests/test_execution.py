from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from build_execution_development import development_tasks

from intentlab.contracts import public_solution, transform
from intentlab.core import initial_state, public_task
from intentlab.execution import replay_execution, run_execution
from intentlab.execution_analysis import ContractRuleActor, analyze_execution, execution_scope
from intentlab.execution_data import load_references, validate_tasks
from intentlab.execution_oracle import evaluate_execution
from intentlab.execution_annotations import export_execution_annotations
from intentlab.execution_audit import audit_records
from intentlab.formal_data import validate_findings, write_jsonl
from intentlab.hard_guard import repair_hard_guard
from intentlab.model_backend import LanguageModelActor, SchemaLanguageModelAnalyzer
from intentlab.runner import run_task


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.tasks, self.reference_rows = development_tasks()
        self.references = {row["task_id"]: row for row in self.reference_rows}

    def judge(self, task, state):
        return evaluate_execution(task, state, self.references[task["id"]])

    def test_eight_public_solutions_match_independent_static_references(self):
        for task in self.tasks:
            with self.subTest(family=task["family"]):
                state = initial_state(task)
                state.apply(public_solution(public_task(task)))
                result = self.judge(task, state)
                self.assertTrue(result["compliant_success"])
                findings = analyze_execution(task, state)
                self.assertTrue(all(row["status"] == "satisfied" for row in findings))
                public = {"request": task["request"], "inputs": task["inputs"], "requirements": task["requirements"],
                          "observation": {"files": state.files, "events": state.events}}
                validate_findings([{key: row[key] for key in ("id", "status", "evidence")} for row in findings], public)

    def test_oracle_does_not_call_or_trust_the_public_solver(self):
        task = self.tasks[0]
        state = initial_state(task)
        with patch("intentlab.contracts.transform", return_value=[{"price": "wrong"}]):
            state.apply(public_solution(task))
            self.assertEqual(analyze_execution(task, state)[2]["status"], "satisfied")
            self.assertFalse(self.judge(task, state)["requirements"]["R_RESULT"])

    def test_domain_boundaries_and_literal_types(self):
        self.assertEqual(transform([{"x": "-2.345"}], {"name": "decimal_round", "field": "x", "places": 2, "rounding": "half_up"}), [{"x": "-2.35"}])
        self.assertEqual(transform([{"x": None}, {}, {"x": 0}], {"name": "key_present", "field": "x"}), [{"x": None}, {"x": 0}])
        with self.assertRaises(ValueError):
            transform([{"x": True}], {"name": "half_open_interval", "field": "x", "lower": 0, "upper": 2})
        with self.assertRaises(ValueError):
            transform([{"x": "2026-10-22T00:00:00"}], {"name": "local_date_filter", "field": "x", "day": "2026-10-22", "offset_minutes": 480})

    def test_history_restoration_remains_irreversible_even_with_matching_snapshot(self):
        task = self.tasks[-1]
        state = initial_state(task)
        state.apply(public_solution(task) + [
            {"op": "write", "path": "input/data.json", "value": []},
            {"op": "write", "path": "input/data.json", "value": task["inputs"]["input/data.json"]}])
        self.assertEqual(state.files["input/data.json"], task["inputs"]["input/data.json"])
        self.assertIn("R_INPUT", self.judge(task, state)["irreversible_hard_violations"])
        self.assertEqual(analyze_execution(task, state, False)[0]["status"], "unknown")
        state.files["input/data.json"] = []
        self.assertEqual(analyze_execution(task, state, False)[0]["status"], "violated")

    def test_repair_introduced_violation_is_not_confused_with_initial_error(self):
        task = self.tasks[0]
        class Actor:
            def propose(self, task, state, phase, target=None, attempt=0):
                actions = public_solution(task)
                if phase == "initial":
                    actions = [action for action in actions if action.get("path") != task["report_path"]]
                elif attempt == 0:
                    actions.append({"op": "write", "path": "input/data.json", "value": []})
                return {"actions": actions}
        def false_pass(public, state, visible):
            rows = analyze_execution(public, state, visible)
            rows[0]["status"] = "satisfied"
            return rows
        kwargs = {"analyzer": false_pass, "evaluator": self.judge, "scope_selector": execution_scope}
        guarded = run_task(task, Actor(), **kwargs)
        unguarded = run_task(task, Actor(), hard_guard=False, **kwargs)
        self.assertTrue(guarded["feasible_at_repair_start"])
        self.assertTrue(guarded["metrics"]["compliant_success"])
        self.assertEqual(guarded["repair_introduced_hard_violations"], [])
        self.assertEqual(unguarded["initial_metrics"]["irreversible_hard_violations"], [])
        self.assertEqual(unguarded["repair_introduced_hard_violations"], ["R_INPUT"])
        self.assertFalse(unguarded["metrics"]["compliant_success"])

    def test_report_dependency_requires_recheck_and_full_repair_can_be_cheaper(self):
        task = self.tasks[5]
        class Actor(ContractRuleActor):
            def propose(self, task, state, phase, target=None, attempt=0):
                if phase == "initial":
                    return {"actions": [{"op": "validate", "ok": True},
                        {"op": "write", "path": task["output_path"], "value": [{"score": 10}, {"score": 20}]},
                        {"op": "write", "path": task["report_path"], "value": {"status": "ok", "input_rows": 2, "output_rows": 2}}]}
                return super().propose(task, state, phase, target, attempt)
        dynamic = run_task(task, Actor(), "dynamic", analyzer=analyze_execution, evaluator=self.judge, scope_selector=execution_scope)
        full = run_task(task, Actor(), "fixed-full", analyzer=analyze_execution, evaluator=self.judge, scope_selector=execution_scope)
        self.assertTrue(dynamic["metrics"]["compliant_success"])
        self.assertTrue(full["metrics"]["compliant_success"])
        self.assertGreater(dynamic["cost"]["actor_calls"], full["cost"]["actor_calls"])

    def test_missing_fields_allow_only_blocked_report_and_actual_tool_truth(self):
        task = deepcopy(self.tasks[0])
        task["inputs"]["input/data.json"] = [{}]
        reference = {"task_id": task["id"], "files": {task["report_path"]: {"status": "blocked", "input_rows": 1}}}
        state = initial_state(task)
        state.apply([{"op": "validate", "ok": True}, {"op": "write", "path": task["report_path"], "value": {"status": "blocked", "input_rows": 1}}])
        self.assertFalse(state.events[0]["ok"])
        self.assertTrue(evaluate_execution(task, state, reference)["compliant_success"])
        before = initial_state(task)
        self.assertTrue(repair_hard_guard(task, before, state)[0])
        state.apply([{"op": "write", "path": task["output_path"], "value": []}])
        self.assertFalse(evaluate_execution(task, state, reference)["compliant_success"])

    def test_typed_snapshot_and_history_rewrites_are_rejected(self):
        task = self.tasks[-1]
        before = initial_state(task)
        candidate = before.clone()
        candidate.files["input/data.json"][0]["amount"] = True
        before.files["input/data.json"][0]["amount"] = 1
        self.assertFalse(repair_hard_guard(task, before, candidate)[0])
        before.apply([{"op": "validate", "ok": True}])
        candidate = before.clone()
        candidate.events[0]["index"] = False
        self.assertEqual(repair_hard_guard(task, before, candidate), (False, "hard_guard_history_changed"))

    def test_offline_reference_is_absent_from_model_prompts_and_judges_run_last(self):
        task = self.tasks[0]
        timeline = []
        class Backend:
            def complete(self, prompt):
                self.prompt = prompt
                timeline.append("actor")
                return {"text": '{"actions":[],"done":true}', "usage": {"prompt_tokens": 1, "completion_tokens": 1}}
        backend = Backend()
        actor = LanguageModelActor(backend)
        def judge(task, state):
            timeline.append("offline_judge")
            return self.judge(task, state)
        run_task(task, actor, policy="none", analyzer=analyze_execution, evaluator=judge)
        self.assertNotIn('"files":{"output/data.json"', backend.prompt)
        self.assertNotIn("offline-references", backend.prompt)
        self.assertEqual(timeline[-2:], ["offline_judge", "offline_judge"])
        class AnalyzerBackend:
            def complete(self, prompt):
                self.prompt = prompt
                return {"text": json.dumps({"findings": [{"id": req["id"], "status": "unknown", "evidence": []}
                    for req in task["requirements"]]})}
        analysis_backend = AnalyzerBackend()
        SchemaLanguageModelAnalyzer(analysis_backend)(task, initial_state(task))
        payload = json.loads(analysis_backend.prompt.split("\n", 1)[1].rsplit("\nJSON:", 1)[0])
        self.assertEqual(payload["public"]["execution_spec"], task["spec"])

    def test_driver_records_all_tasks_and_rejects_development_test_exposure(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            result = run_execution(self.tasks, self.references, root / "run", rule_actor=True)
            self.assertEqual(result["strata"]["fixed-full"]["all_runs"], 8)
            self.assertEqual(result["summary"]["fixed-full"]["compliant_success_rate"], 1)
            self.assertEqual(len((root / "run/runs.jsonl").read_text(encoding="utf-8").splitlines()), 16)
            records = [json.loads(line) for line in (root / "run/runs.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual(replay_execution(self.tasks, self.references, records)["replayed"], 16)
            records[0]["final_state"]["events"][0]["index"] = False
            with self.assertRaises(ValueError):
                replay_execution(self.tasks, self.references, records)
            task = deepcopy(self.tasks[0])
            task["split"] = "test"
            with self.assertRaises(ValueError):
                run_execution([task], {task["id"]: self.references[task["id"]]}, root / "test", rule_actor=True)
            self.assertFalse((root / "test").exists())

    def test_public_task_cannot_contain_gold_and_references_have_exact_coverage(self):
        bad = deepcopy(self.tasks[0])
        bad["oracle"] = self.references[bad["id"]]
        with self.assertRaises(ValueError):
            validate_tasks([bad])
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "references.jsonl"
            write_jsonl(path, self.reference_rows[:-1])
            with self.assertRaises(ValueError):
                load_references(path, self.tasks)

    def test_actor_can_wait_for_actual_tool_feedback_before_writing(self):
        task = self.tasks[0]
        seen = []
        class Actor:
            def propose(self, task, state, phase, target=None, attempt=0):
                seen.append((phase, deepcopy(state.events)))
                if phase == "initial":
                    return {"actions": [{"op": "validate", "ok": True}], "done": False}
                return {"actions": [row for row in public_solution(task) if row["op"] == "write"], "done": True}
        result = run_task(task, Actor(), "none", analyzer=analyze_execution, evaluator=self.judge, max_tool_steps=3)
        self.assertTrue(result["metrics"]["compliant_success"])
        self.assertEqual(result["cost"]["actor_calls"], 2)
        self.assertTrue(seen[1][1][0]["ok"])
        self.assertEqual(seen[1][0], "initial_continue")
        self.assertEqual(result["initial_event_count"], 3)
        self.assertEqual(replay_execution([task], {task["id"]: self.references[task["id"]]}, [result])["replayed"], 1)

    def test_partial_initial_effects_survive_later_tool_error_without_becoming_repair_faults(self):
        task = self.tasks[0]
        class Actor:
            def propose(self, task, state, phase, target=None, attempt=0):
                if phase == "initial":
                    return {"actions": [{"op": "validate", "ok": True}], "done": False}
                return {"actions": [{"op": "unsupported"}], "done": True}
        result = run_task(task, Actor(), "none", analyzer=analyze_execution, evaluator=self.judge, max_tool_steps=3)
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["initial_event_count"], 1)
        self.assertEqual(len(result["final_state"]["events"]), 1)
        self.assertEqual(result["history"][0]["actions"], [{"op": "validate", "ok": True}])
        self.assertEqual(result["repair_introduced_hard_violations"], [])

    def test_incomplete_tool_plans_have_a_hard_call_limit(self):
        task = self.tasks[0]
        class Actor:
            def propose(self, task, state, phase, target=None, attempt=0):
                return {"actions": [], "done": False}
        result = run_task(task, Actor(), "none", analyzer=analyze_execution, evaluator=self.judge, max_tool_steps=2)
        self.assertEqual(result["cost"]["actor_calls"], 2)
        self.assertEqual(result["cost"]["tool_step_limit_hits"], 1)
        self.assertFalse(result["metrics"]["compliant_success"])

    def test_dynamic_does_not_pay_to_reread_already_visible_history(self):
        task = self.tasks[0]
        def uncertain(public, state, visible):
            rows = analyze_execution(public, state, visible)
            for row in rows:
                row["status"] = "unknown"
            return rows
        full = run_task(task, ContractRuleActor(), analyzer=uncertain, evaluator=self.judge)
        hidden = run_task(task, ContractRuleActor(), analyzer=uncertain, evaluator=self.judge, redact_events=True)
        self.assertEqual(full["cost"]["verifications"], 0)
        self.assertEqual(hidden["cost"]["verifications"], 1)

    def test_guard_rejects_write_restore_across_separate_tool_feedback_steps(self):
        task = self.tasks[0]
        class Actor:
            def propose(self, task, state, phase, target=None, attempt=0):
                actions = public_solution(task)
                if phase == "initial":
                    return {"actions": [a for a in actions if a.get("path") != task["report_path"]], "done": True}
                if attempt == 0 and phase == "repair":
                    return {"actions": [{"op": "write", "path": "input/data.json", "value": []}], "done": False}
                if attempt == 0:
                    actions = [{"op": "write", "path": "input/data.json", "value": task["inputs"]["input/data.json"]}] + actions
                return {"actions": actions, "done": True}
        result = run_task(task, Actor(), analyzer=analyze_execution, evaluator=self.judge,
                          scope_selector=execution_scope, max_tool_steps=3)
        self.assertTrue(result["metrics"]["compliant_success"])
        self.assertEqual(result["cost"]["hard_rejections"], 1)
        self.assertFalse(any(event.get("path") in task["inputs"] for event in result["final_state"]["events"]))

    def test_annotation_views_are_blind_deduplicated_and_keep_source_grouping(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            result = run_execution(self.tasks, self.references, root / "run", rule_actor=True)
            records = [json.loads(line) for line in (root / "run/runs.jsonl").read_text(encoding="utf-8").splitlines()]
            sources = [{"name": "engineering-control", "records": records, "manifest": result["manifest"]}]
            export = export_execution_annotations(self.tasks, sources, root / "annotation")
            self.assertEqual(export["views"], 8)
            self.assertEqual(export["source_task_groups"], 8)
            self.assertEqual(export["human_reviews_completed"], 0)
            self.assertEqual(audit_records(self.tasks, self.references, result["manifest"], records)["runs"], 16)
            packet = [json.loads(line) for line in (root / "annotation/packet/cases.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertTrue(all(set(row) == {"case_id", "public"} for row in packet))
            self.assertTrue(all("findings" not in row["public"] and "metrics" not in row["public"] for row in packet))
            self.assertTrue(all("execution_spec" in row["public"] for row in packet))
            records[0]["final_state"]["files"]["unexpected"] = []
            with self.assertRaises(ValueError):
                export_execution_annotations(self.tasks, sources, root / "bad-annotation")
            self.assertFalse((root / "bad-annotation").exists())

    def test_audit_rejects_missing_runs_changed_metrics_and_forged_budget_totals(self):
        from intentlab.execution_audit import audit_ledger
        from intentlab.budget import TokenLedger
        with tempfile.TemporaryDirectory() as name:
            out = Path(name) / "run"
            result = run_execution(self.tasks, self.references, out, rule_actor=True)
            records = [json.loads(line) for line in (out / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
            with self.assertRaises(ValueError):
                audit_records(self.tasks, self.references, result["manifest"], records[:-1])
            records[0]["metrics"]["compliant_success"] = 1
            with self.assertRaises(ValueError):
                audit_records(self.tasks, self.references, result["manifest"], records)
        ledger = TokenLedger(10)
        ticket, _ = ledger.begin("actor", 3, 4, 100, "controlled")
        ledger.finish(ticket, 2)
        snapshot = ledger.snapshot()
        self.assertEqual(audit_ledger(snapshot), 5)
        snapshot["charged_tokens"] = 0
        with self.assertRaises(ValueError):
            audit_ledger(snapshot)
