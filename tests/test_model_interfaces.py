import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
import io

from intentlab.analysis import REQUIREMENTS
from intentlab.core import initial_state, public_task
from intentlab.fixtures import build_tasks, diagnostic_states
from intentlab.model_backend import LanguageModelActor, LanguageModelAnalyzer
from intentlab.requirements import extract_requirements
from intentlab.sft_data import export_sft, validate_splits
from intentlab.runner import run_task
from intentlab.actors import ScriptedActor


class FakeBackend:
    def __init__(self, value):
        self.value, self.prompts = value, []

    def complete(self, prompt):
        self.prompts.append(prompt)
        return {"text": json.dumps(self.value), "usage": {"prompt_tokens": 8, "completion_tokens": 4}}


class ModelInterfaceTests(unittest.TestCase):
    def test_training_json_configuration_and_explicit_overrides(self):
        from intentlab.neural import main
        with tempfile.TemporaryDirectory() as name:
            path = Path(name) / "config.json"
            path.write_text(json.dumps({"steps": 10, "mode": "lora", "lr": 0.001}))
            with patch("intentlab.neural.train_neural", return_value={"completed": False}) as call, redirect_stdout(io.StringIO()):
                main(["--config", str(path), "--steps", "3", "--out", str(Path(name) / "output")])
            config = call.call_args.args[0]
            self.assertEqual(config["steps"], 3)
            self.assertEqual(config["mode"], "lora")
            self.assertEqual(config["lr"], 0.001)

    def test_learned_risk_scores_do_not_override_hard_constraints(self):
        task = build_tasks()[1]
        result = run_task(task, ScriptedActor(), risk_weights=[0.0] * 10)
        self.assertTrue(all("risk_score" in f for f in result["history"][0]["findings"]))
        self.assertGreater(result["cost"]["rejected"], 0)
        self.assertTrue(result["metrics"]["compliant_success"])
    def test_actor_gets_no_reference_answer(self):
        task = public_task(build_tasks()[0])
        backend = FakeBackend({"actions": [{"op": "validate", "ok": True}]})
        reply = LanguageModelActor(backend).propose(task, initial_state(task), "initial")
        self.assertEqual(len(reply["actions"]), 1)
        self.assertNotIn('"oracle"', backend.prompts[0])

    def test_analyzer_abstains_on_invented_evidence(self):
        task = public_task(build_tasks()[0])
        backend = FakeBackend({"findings": [{"id": rid, "status": "satisfied", "evidence": [999]} for rid in REQUIREMENTS]})
        analyzer = LanguageModelAnalyzer(backend)
        findings = analyzer(task, initial_state(task))
        self.assertTrue(all(f["status"] == "unknown" for f in findings))
        self.assertEqual(len(analyzer.errors), 1)

    def test_analyzer_preserves_snapshot_judgment_when_history_is_hidden(self):
        task = public_task(build_tasks()[0])
        backend = FakeBackend({"findings": [{"id": rid, "status": "violated", "evidence": []} for rid in REQUIREMENTS]})
        findings = LanguageModelAnalyzer(backend)(task, initial_state(task), False)
        self.assertEqual([f["status"] for f in findings[:2]], ["violated", "violated"])

    def test_source_spans_and_unsupported_grammar(self):
        for task in build_tasks():
            for requirement in extract_requirements(task["request"]):
                self.assertEqual(task["request"][requirement["start"]:requirement["end"]], requirement["quote"])
        with self.assertRaises(ValueError):
            extract_requirements("Ambiguous unsupported task")

    def test_sft_export_and_group_isolation(self):
        with tempfile.TemporaryDirectory() as name:
            groups = export_sft(build_tasks(), Path(name))
            validate_splits(groups)
            self.assertEqual(sum(map(len, groups.values())), 320)
            self.assertNotIn('"oracle"', groups["train"][0]["prompt"])
            payload = json.loads(groups['train'][0]['prompt'].split('\n', 1)[1].rsplit('\nJSON:', 1)[0])
            self.assertEqual({r['id'] for r in payload['requirements']}, set(REQUIREMENTS))
            self.assertTrue(all('status' not in r for r in payload['requirements']))
            duplicate = dict(groups)
            duplicate["test"] = duplicate["test"] + [groups["train"][0]]
            with self.assertRaises(ValueError):
                validate_splits(duplicate)


if __name__ == "__main__":
    unittest.main()
