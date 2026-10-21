"""Optional real-transformer integration tests, skipped in the dependency-free job."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from intentlab.fixtures import build_tasks
from intentlab.sft_data import export_sft


AVAILABLE = all(importlib.util.find_spec(name) for name in ("torch", "transformers", "peft"))


def configuration(data, schedule="cosine", mode="full"):
    return {"data": str(data), "model": "tiny", "revision": None, "mode": mode, "device": "cpu",
            "schedule": schedule, "steps": 6, "eval_every": 2, "batch_size": 1, "accumulation": 2,
            "max_length": 2048, "lr": 0.001, "minimum_lr": 0.000005,
            "rank": 4, "alpha": 8, "seed": 3, "limit": 2, "threads": 1}


@unittest.skipUnless(AVAILABLE, "Install optional ML dependencies to run real-transformer tests")
class NeuralIntegrationTests(unittest.TestCase):
    def test_controlled_plateau_reduces_actual_optimizer_lr(self):
        """Injected validation fixture tests control wiring, not empirical loss behavior."""
        import torch
        from intentlab.neural import train_neural
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            export_sft(build_tasks(), root / "data")
            config = dict(configuration(root / "data", schedule="plateau"), eval_every=1)
            with patch("intentlab.neural.evaluate_loss", return_value={"loss": 1.0, "target_tokens": 10}):
                result = train_neural(config, root / "model")
            self.assertTrue(any(row["scheduler"]["reduced"] for row in result["history"]))
            self.assertLess(result["history"][-1]["lr_used"], config["lr"])
            checkpoint = torch.load(root / "model/latest.pt", weights_only=True)
            self.assertLess(checkpoint["optimizer"]["param_groups"][0]["lr"], config["lr"])

    def test_resumed_training_matches_uninterrupted_training(self):
        import torch
        from intentlab.neural import train_neural
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            export_sft(build_tasks(), root / "data")
            for schedule in ("cosine", "plateau"):
                config = configuration(root / "data", schedule)
                full = train_neural(config, root / (schedule + "-full"))
                interrupted = root / (schedule + "-resume")
                partial = train_neural(config, interrupted, stop_after=3)
                self.assertFalse(partial["completed"])
                resumed = train_neural(config, interrupted, resume=interrupted / "latest.pt")
                self.assertEqual(full["history"], resumed["history"])
                self.assertEqual(full["test"], resumed["test"])
                full_state = torch.load(root / (schedule + "-full") / "latest.pt", weights_only=True)
                resumed_state = torch.load(interrupted / "latest.pt", weights_only=True)
                self.assertTrue(all(torch.equal(t, resumed_state["weights"][k]) for k, t in full_state["weights"].items()))
                changed = dict(config, lr=0.002)
                with self.assertRaises(ValueError):
                    train_neural(changed, interrupted, resume=interrupted / "latest.pt")

    def test_lora_trains_and_saved_adapter_generates_with_budget(self):
        from intentlab.model_backend import BudgetExceeded, LocalBackend
        from intentlab.neural import train_neural
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            export_sft(build_tasks(), root / "data")
            config = configuration(root / "data", mode="lora")
            result = train_neural(config, root / "adapter")
            self.assertLess(result["trainable_parameters"], result["parameters"])
            self.assertTrue((root / "adapter/model/adapter_model.safetensors").exists())
            backend = LocalBackend(root / "adapter/model", max_new_tokens=4, token_budget=32)
            reply = backend.complete("JSON:")
            self.assertIsInstance(reply["text"], str)
            self.assertGreater(backend.usage["calls"], 0)
            self.assertLessEqual(sum(backend.usage[k] for k in ("prompt_tokens", "completion_tokens")), 32)
            backend.limit = 1
            with self.assertRaises(BudgetExceeded):
                backend.complete("JSON:")

    def test_masking_and_truncation_guards(self):
        from intentlab.neural import encode_pair, tokenizer_for_tiny
        rows = [{"task_id": "x", "prompt": "Input text\n", "completion": '{"status":"unknown"}'}]
        tokenizer = tokenizer_for_tiny(rows)
        encoded = encode_pair(tokenizer, rows[0], 128)
        self.assertEqual(encoded["labels"][0], -100)
        self.assertGreater(sum(i != -100 for i in encoded["labels"]), 0)
        with self.assertRaises(ValueError):
            encode_pair(tokenizer, rows[0], 2)


if __name__ == "__main__":
    unittest.main()
