import json
from pathlib import Path
import tempfile
import unittest

from intentlab.budget import TokenLedger
from intentlab.core import initial_state, public_task
from intentlab.fixtures import build_tasks
from intentlab.formal_inference import diagnostic_prompt, reviewed_examples, run_diagnostics
from intentlab.model_backend import SchemaLanguageModelAnalyzer
from test_formal_data import case, review


class ControlledBackend:
    def __init__(self, fail=False):
        self.ledger, self.fail = TokenLedger(100), fail
        self.prompts = []

    def reset(self):
        self.ledger.reset()

    def complete(self, prompt, role="analyzer"):
        self.prompts.append(prompt)
        ticket, _ = self.ledger.begin(role, 10, 10, 100, "controlled")
        if self.fail:
            self.ledger.fail(ticket, "controlled_failure")
            raise RuntimeError("controlled failure")
        self.ledger.finish(ticket, 5)
        return {"text": '{"findings":[]}', "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


class FormalInferenceTests(unittest.TestCase):
    def test_no_labels_enter_query_and_failed_cases_are_saved(self):
        for fail in (False, True):
            with tempfile.TemporaryDirectory() as name:
                backend = ControlledBackend(fail)
                out = Path(name) / "result"
                manifest = run_diagnostics([case()], backend, out)
                self.assertFalse(manifest["gold_loaded"])
                self.assertEqual(manifest["errors"], int(fail))
                prediction = json.loads((out / "predictions.jsonl").read_text())
                self.assertEqual(prediction["case_id"], "view-1")
                self.assertNotIn("completion", backend.prompts[0])
                self.assertNotIn("reviewer", backend.prompts[0])
                self.assertEqual(prediction["text"], "" if fail else '{"findings":[]}')
                self.assertEqual(manifest["status"], "completed")

    def test_fewshot_requires_reviewed_development_and_blocks_overlap(self):
        exemplar = case("example", "validation", "example-source", "example-template")
        examples = reviewed_examples([exemplar], [review("example"), review("example", "bob")])
        with self.assertRaises(ValueError):
            diagnostic_prompt(case(), examples)  # Same normalized request.
        query = case()
        query["public"]["request"] += " Distinct query task."
        self.assertIn("Reviewed examples", diagnostic_prompt(query, examples))
        with self.assertRaises(ValueError):
            reviewed_examples([dict(exemplar, split="test")], [review("example"), review("example", "bob")])

    def test_schema_adapter_keeps_snapshot_violation_without_history(self):
        task = public_task(build_tasks()[0])
        class Backend:
            def complete(self, prompt):
                return {"text": json.dumps({"findings": [
                    {"id": rid, "status": "violated" if rid == "R_INPUT" else "unknown",
                     "evidence": ["input:" + next(iter(task["inputs"]))] if rid == "R_INPUT" else []}
                    for rid in ("R_INPUT", "R_ORDER", "R_RESULT", "R_REPORT")]})}
        analyzer = SchemaLanguageModelAnalyzer(Backend())
        findings = analyzer(task, initial_state(task), False)
        self.assertEqual(findings[0]["status"], "violated")
        self.assertEqual(analyzer.errors, [])
