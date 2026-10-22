import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from intentlab.checkpoint_selection import best_validation, verify_selected_checkpoint, tensor_hash


class SelectionTests(unittest.TestCase):
    def test_selection_uses_validation_and_first_tie(self):
        history = [{"step": i, "validation": {"loss": loss, "target_tokens": 10}}
                   for i, loss in ((2, 1.1), (4, 0.7), (6, 0.7), (8, 0.9))]
        self.assertEqual(best_validation(history)["step"], 4)

    def test_invalid_or_incomparable_validation_history_is_refused(self):
        for history in ([], [{"step": 1, "validation": {"loss": float("nan"), "target_tokens": 10}}],
                        [{"step": True, "validation": {"loss": 1, "target_tokens": 10}}],
                        [{"step": 1, "validation": {"loss": -1, "target_tokens": 10}}],
                        [{"step": 1, "validation": {"loss": 1, "target_tokens": 10}},
                         {"step": 2, "validation": {"loss": 0.5, "target_tokens": 5}}]):
            with self.subTest(history=history), self.assertRaises(ValueError):
                best_validation(history)


AVAILABLE = all(importlib.util.find_spec(name) for name in ("torch", "transformers", "peft", "safetensors"))


@unittest.skipUnless(AVAILABLE, "Install optional ML dependencies for selected-tensor verification")
class SelectedTensorIntegrationTests(unittest.TestCase):
    def test_tensor_fingerprint_preserves_bfloat16_scalar_dtype_and_shape(self):
        import torch
        scalar = tensor_hash({"x": torch.tensor(1.25, dtype=torch.bfloat16)})
        self.assertNotEqual(scalar, tensor_hash({"x": torch.tensor([1.25], dtype=torch.bfloat16)}))
        self.assertNotEqual(scalar, tensor_hash({"x": torch.tensor(1.25, dtype=torch.float32)}))

    def test_full_and_lora_exports_contain_best_not_last_tensors_and_tampering_is_refused(self):
        import torch
        from safetensors.torch import load_file, save_file
        from intentlab.fixtures import build_tasks
        from intentlab.neural import train_neural
        from intentlab.sft_data import export_sft
        from test_neural import configuration
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            export_sft(build_tasks(), root / "data")
            for mode in ("full", "lora"):
                out = root / mode
                config = dict(configuration(root / "data", mode=mode), steps=3, eval_every=1, defer_test=True)
                # Constant validation forces the earliest tie. Real gradients
                # continue changing parameters; this is wiring, not efficacy.
                with patch("intentlab.neural.evaluate_loss", return_value={"loss": 1.0, "target_tokens": 10}):
                    result = train_neural(config, out)
                proof = verify_selected_checkpoint(out, result)
                self.assertEqual(proof["step"], 1)
                saved = torch.load(out / "latest.pt", weights_only=True)
                self.assertNotEqual(tensor_hash(saved["weights"]), tensor_hash(saved["best_weights"]))
                self.assertNotIn("test", result)
                path = next((out / "model").glob("*.safetensors"))
                tensors = load_file(path)
                key = next(iter(tensors))
                tensors[key] = tensors[key] + 1
                save_file(tensors, path)
                with self.assertRaises(ValueError):
                    verify_selected_checkpoint(out, result)
