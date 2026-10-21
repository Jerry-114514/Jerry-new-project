import io
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from intentlab.actors import HTTPActor, ScriptedActor, solve
from intentlab.analysis import analyze, gate, score
from intentlab.core import initial_state, load_tasks, public_task, replay_events, valid_path
from intentlab.fixtures import build_tasks, diagnostic_states, export_diagnostics
from intentlab.learning import read_examples, train
from intentlab.oracle import evaluate
from intentlab.runner import run_task
from intentlab.schedules import Plateau, warmup_cosine


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.tasks = build_tasks()
        self.task = self.tasks[0]

    def test_all_goldens_have_legal_execution(self):
        for task in self.tasks:
            state = initial_state(task)
            state.apply(solve(public_task(task)))
            self.assertTrue(evaluate(task, state)["compliant_success"], task["id"])
            self.assertTrue(all(f["status"] == "satisfied" for f in analyze(public_task(task), state)))

    def test_bad_paths(self):
        for path in ("../secret", "a/../b", "/tmp/x", "C:/file", "a\\b", "a//b", ".", ""):
            with self.assertRaises(ValueError):
                valid_path(path)

    def test_invalid_proposal_is_atomic(self):
        state = initial_state(self.task)
        with self.assertRaises(ValueError):
            state.apply([{"op": "write", "path": "output/x", "value": 1}, {"op": "shell"}])
        self.assertNotIn("output/x", state.files)
        self.assertEqual(state.events, [])

    def test_claimed_validation_does_not_override_tool(self):
        task = self.tasks[4]  # Missing a required field.
        state = initial_state(task)
        state.apply([{"op": "validate", "ok": True}])
        self.assertFalse(state.events[0]["ok"])
        self.assertTrue(state.events[0]["claimed_ok"])

    def test_restore_does_not_erase_history(self):
        state = initial_state(self.task)
        state.apply(solve(public_task(self.task)))
        name = next(iter(self.task["inputs"]))
        state.apply([{"op": "write", "path": name, "value": []},
                     {"op": "write", "path": name, "value": self.task["inputs"][name]}])
        self.assertFalse(evaluate(self.task, state)["requirements"]["R_INPUT"])

    def test_order_checks_actual_history(self):
        state = initial_state(self.task)
        actions = solve(public_task(self.task))
        state.apply(actions[1:] + actions[:1])
        self.assertFalse(evaluate(self.task, state)["requirements"]["R_ORDER"])

    def test_blocked_report_must_follow_failed_check(self):
        task = self.tasks[4]
        state = initial_state(task)
        actions = solve(public_task(task))
        state.apply(actions[1:] + actions[:1])
        self.assertFalse(evaluate(task, state)["requirements"]["R_ORDER"])

    def test_hidden_oracle_and_input_isolation(self):
        visible = public_task(self.task)
        self.assertNotIn("oracle", visible)
        visible["inputs"].clear()
        self.assertTrue(self.task["inputs"])

    def test_unknown_evidence_is_not_satisfied(self):
        state = diagnostic_states(self.task)["valid"]
        findings = analyze(public_task(self.task), state, False)
        self.assertEqual(score(findings)["unknown"], 2)
        self.assertEqual(score(findings)["evidence_coverage"], 0.5)

    def test_gate_rejects_regression_and_leaves_live_state(self):
        states = diagnostic_states(self.task)
        before = states["violation"]
        initial_events = len(before.events)
        allowed, _ = gate(analyze(public_task(self.task), before), analyze(public_task(self.task), states["repair_regression"]))
        self.assertFalse(allowed)
        self.assertEqual(len(before.events), initial_events)

    def test_gate_accepts_verified_repair(self):
        states = diagnostic_states(self.task)
        allowed, _ = gate(analyze(public_task(self.task), states["violation"]), analyze(public_task(self.task), states["repair_ok"]))
        self.assertTrue(allowed)

    def test_gate_does_not_accept_unknown_hard_constraints(self):
        states = diagnostic_states(self.task)
        allowed, reason = gate(analyze(public_task(self.task), states["violation"], False),
                               analyze(public_task(self.task), states["repair_ok"], False))
        self.assertFalse(allowed)
        self.assertIn("unverified", reason)

    def test_static_oracle_not_generated_by_actor(self):
        state = diagnostic_states(self.task)["valid"]
        modified = public_task(self.task)
        modified["oracle"] = {"files": {}, "blocked": False}
        self.assertFalse(evaluate(modified, state)["compliant_success"])

    def test_replay_checks_tools_and_rejects_tampered_evidence(self):
        state = diagnostic_states(self.task)["repair_regression"]
        restored = replay_events(self.task, state.events)
        self.assertEqual(restored.files, state.files)
        altered = json.loads(json.dumps(state.events))
        altered[-1]["after"] = "forged"
        with self.assertRaises(ValueError):
            replay_events(self.task, altered)


class RunnerTests(unittest.TestCase):
    def test_rejected_candidate_does_not_touch_input(self):
        task = build_tasks()[1]
        record = run_task(task, ScriptedActor(), "dynamic")
        self.assertGreater(record["cost"]["rejected"], 0)
        self.assertTrue(record["metrics"]["compliant_success"])

    def test_budget_respected(self):
        task = build_tasks()[1]
        record = run_task(task, ScriptedActor(), "dynamic", max_repairs=0)
        self.assertEqual(record["cost"]["actor_calls"], 1)
        self.assertFalse(record["metrics"]["task_complete"])

    def test_dynamic_verification_is_counted(self):
        record = run_task(build_tasks()[1], ScriptedActor(), "dynamic", redact_events=True)
        self.assertEqual(record["cost"]["verifications"], 1)

    def test_failed_actor_is_reported(self):
        class Broken:
            def propose(self, *args, **kwargs):
                return {"actions": [{"op": "shell", "command": "no"}]}
        record = run_task(build_tasks()[0], Broken())
        self.assertEqual(record["status"], "error")
        self.assertFalse(record["metrics"]["compliant_success"])

    def test_http_payload_excludes_oracle(self):
        task = build_tasks()[0]
        payload = json.dumps({"actions": solve(public_task(task))}).encode()
        with patch("urllib.request.urlopen", return_value=io.BytesIO(payload)) as mock:
            record = run_task(task, HTTPActor("http://localhost/propose"))
            request = mock.call_args.args[0]
            self.assertNotIn("oracle", json.loads(request.data)["task"])
            self.assertTrue(record["metrics"]["compliant_success"])

    def test_http_response_limit(self):
        with patch("urllib.request.urlopen", return_value=io.BytesIO(b"x" * 1_000_001)):
            with self.assertRaises(ValueError):
                HTTPActor("http://localhost").propose({}, initial_state(build_tasks()[0]), "initial")


class SchedulerTests(unittest.TestCase):
    def test_plateau_patience_and_cooldown(self):
        scheduler = Plateau(0.1, min_lr=0.01)
        for loss in [1, 1, 1]:
            self.assertFalse(scheduler.step(loss)["reduced"])
        self.assertTrue(scheduler.step(1)["reduced"])
        self.assertEqual(scheduler.lr, 0.05)
        scheduler.step(1)
        self.assertEqual(scheduler.bad, 0)

    def test_lower_bound_and_serialized_resume(self):
        from dataclasses import asdict
        scheduler = Plateau(0.1, patience=0, cooldown=0, min_lr=0.02)
        for _ in range(8):
            scheduler.step(1)
        resumed = Plateau(**json.loads(json.dumps(asdict(scheduler))))
        self.assertEqual(scheduler.step(1), resumed.step(1))
        self.assertEqual(scheduler.lr, 0.02)

    def test_relative_improvement(self):
        scheduler = Plateau(0.1, threshold=0.01)
        scheduler.step(1)
        scheduler.step(0.995)
        self.assertEqual(scheduler.bad, 1)
        scheduler.step(0.98)
        self.assertEqual(scheduler.bad, 0)

    def test_cosine_endpoints_and_nan(self):
        self.assertAlmostEqual(warmup_cosine(2, 10, 0.1, 0.01, 2), 0.1)
        self.assertAlmostEqual(warmup_cosine(9, 10, 0.1, 0.01, 2), 0.01)
        with self.assertRaises(ValueError):
            Plateau(0.1).step(math.nan)


class DataLearningTests(unittest.TestCase):
    def test_generation_training_and_test_separation(self):
        with tempfile.TemporaryDirectory() as name:
            directory = Path(name)
            export_diagnostics(build_tasks(), directory)
            self.assertEqual(len((directory / "trajectories.jsonl").read_text(encoding="utf-8").splitlines()), 160)
            self.assertEqual(len((directory / "diagnostic_views.jsonl").read_text(encoding="utf-8").splitlines()), 320)
            examples = read_examples(directory / "diagnostic_views.jsonl")
            model = train(examples, epochs=6)
            self.assertTrue(math.isfinite(model["test"]["loss"]))
            self.assertEqual(model, train(examples, epochs=6))
            changed = dict(examples)
            changed["test"] = [(x, 1-y) for x, y in examples["test"]]
            second = train(changed, epochs=6)
            self.assertEqual(model["weights"], second["weights"])
            self.assertEqual(model["history"], second["history"])

    def test_task_loader_rejects_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "tasks.json"
            tasks = build_tasks()
            path.write_text(json.dumps([tasks[0], tasks[0]]), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_tasks(path)


if __name__ == "__main__":
    unittest.main()
