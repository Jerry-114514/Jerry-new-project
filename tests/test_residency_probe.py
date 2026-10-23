from copy import deepcopy
import json
from pathlib import Path
import unittest

from intentlab.procedural_data import make_task
from intentlab.residency_probe import capture_tokens, development_prompts, without_timing


def development_tasks():
    plan = json.loads(Path("configs/procedural-data-plan.json").read_text())
    return [make_task("stable_sort", "validation", i, "01" * 32, plan)[0] for i in (0, 9)]


class ResidencyProbeTests(unittest.TestCase):
    def test_only_development_and_fixed_ordered_prompts(self):
        tasks = development_tasks()
        batches = development_prompts(tasks)
        self.assertEqual(batches, development_prompts(list(reversed(tasks))))
        for batch in batches:
            self.assertEqual([role for role, _ in batch["calls"]], ["actor", "analyzer", "actor"])
            self.assertEqual(batch["calls"][0], batch["calls"][2])
            self.assertIn("response_schema", batch["calls"][0][1])
            self.assertIn("execution_spec", batch["calls"][1][1])
        mixed = deepcopy(tasks); mixed[1]["split"] = "test"
        with self.assertRaisesRegex(ValueError, "no heldout"):
            development_prompts(mixed)
        with self.assertRaises(ValueError):
            development_prompts(tasks[:1])

    def test_compare_preserves_all_accounting_except_elapsed_seconds(self):
        snapshot = {"charged_tokens": 5, "events": [{"role": "actor", "elapsed_seconds": 2,
                    "completion_tokens": None, "status": "error", "charged_tokens": 5}]}
        result = without_timing(snapshot)
        self.assertIn("elapsed_seconds", snapshot["events"][0])
        self.assertEqual(result["events"][0], {k: v for k, v in snapshot["events"][0].items() if k != "elapsed_seconds"})

    def test_generation_observer_restores_existing_override_even_after_failure(self):
        class Model:
            def generate(self):
                raise RuntimeError("expected")
        class Backend:
            model = Model()
        backend = Backend()
        before = backend.model.generate
        with self.assertRaisesRegex(RuntimeError, "expected"):
            with capture_tokens(backend):
                backend.model.generate()
        self.assertNotIn("generate", vars(backend.model))
        backend.model.generate = before
        with capture_tokens(backend):
            pass
        self.assertIs(backend.model.generate, before)
