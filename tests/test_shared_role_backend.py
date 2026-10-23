"""Residency correctness tests; random tiny weights are not efficacy evidence."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from intentlab.budget import BudgetExceeded, TokenLedger
from intentlab.shared_role_backend import compatible_base_adapter


class CompatibilityTests(unittest.TestCase):
    def test_only_matching_non_mutating_local_lora_is_eligible(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); actor = root / "base"; adapter = root / "adapter"
            actor.mkdir(); adapter.mkdir()
            paths = {"actor": actor, "analyzer": adapter}
            config = {"base_model_name_or_path": str(actor.resolve()), "peft_type": "LORA", "bias": "none"}
            target = adapter / "adapter_config.json"
            target.write_text(json.dumps(config), encoding="utf-8")
            self.assertTrue(compatible_base_adapter(paths))
            for change in ({"bias": "all"}, {"lora_bias": True}, {"modules_to_save": ["lm_head"]},
                           {"trainable_token_indices": [1]}, {"layer_replication": [[0, 1]]},
                           {"init_lora_weights": "pissa"}, {"base_model_name_or_path": "hub/model"},
                           {"base_model_name_or_path": str(root / "other")}, {"peft_type": "IA3"}):
                target.write_text(json.dumps(dict(config, **change)), encoding="utf-8")
                self.assertFalse(compatible_base_adapter(paths), change)
            target.write_text(json.dumps(config), encoding="utf-8")
            (adapter / "tiny_base_recipe.json").write_text("{}")
            self.assertFalse(compatible_base_adapter(paths))
            (adapter / "tiny_base_recipe.json").unlink()
            (actor / "adapter_config.json").write_text("{}")
            self.assertFalse(compatible_base_adapter(paths))
            target.write_text("bad-json", encoding="utf-8")
            self.assertFalse(compatible_base_adapter(paths))


AVAILABLE = all(importlib.util.find_spec(name) for name in ("torch", "transformers", "peft"))


@unittest.skipUnless(AVAILABLE, "Install optional ML dependencies for real residency tests")
class SharedRoleIntegrationTests(unittest.TestCase):
    def test_real_adapter_alternation_matches_reload_and_restores_after_failure(self):
        import torch
        from peft import LoraConfig, get_peft_model
        from transformers import GPT2Config, GPT2LMHeadModel
        from intentlab.model_backend import LocalBackend
        from intentlab.model_pool import LocalModelPool
        from intentlab.checkpoint_selection import tensor_hash
        from intentlab.neural import tokenizer_for_tiny

        torch.set_num_threads(1)
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); base = root / "base"; adapter = root / "adapter"
            tok = tokenizer_for_tiny([{"prompt": "JSON: inspect evidence now", "completion": "satisfied violated unknown"}])
            torch.manual_seed(17)
            model = GPT2LMHeadModel(GPT2Config(vocab_size=len(tok), n_positions=16384, n_embd=24, n_layer=1,
                                             n_head=2, eos_token_id=tok.eos_token_id, bos_token_id=tok.bos_token_id))
            model.save_pretrained(base); tok.save_pretrained(base)
            model = GPT2LMHeadModel.from_pretrained(base, local_files_only=True)
            adapted = get_peft_model(model, LoraConfig(r=4, lora_alpha=8, target_modules=["c_attn"],
                                                      task_type="CAUSAL_LM", bias="none"))
            with torch.no_grad():
                for key, parameter in adapted.named_parameters():
                    if "lora_B" in key:
                        parameter.normal_(std=0.5)
            adapted.save_pretrained(adapter)
            # Deliberately different special-token policies without changing vocab.
            tok.eos_token = "[BOS]"; tok.pad_token = "[UNK]"; tok.save_pretrained(adapter)
            paths = {"actor": base, "analyzer": adapter}
            self.assertTrue(compatible_base_adapter(paths))
            prompts = [("actor", "JSON:"), ("analyzer", "inspect evidence"), ("actor", "JSON:")]
            expected, expected_ids = [], []
            ledger = TokenLedger(100)

            def capture(backend, output_ids):
                original = backend.model.generate
                def generate(*args, **kwargs):
                    output = original(*args, **kwargs)
                    output_ids.append(output.tolist())
                    return output
                return patch.object(backend.model, "generate", side_effect=generate)

            for role, prompt in prompts:
                backend = LocalBackend(paths[role], max_new_tokens=3, token_budget=100, ledger=ledger, context_limit=128)
                try:
                    with capture(backend, expected_ids):
                        expected.append(backend.complete(prompt, role=role))
                finally:
                    backend.close()
            pool = LocalModelPool(paths, max_new_tokens=3, token_budget=100, context_limit=128, share_base_adapter=True)
            actual, actual_ids = [], []
            try:
                # First call initializes the one resident base+adapter.
                actual.append(pool.complete(*prompts[0]))
                current = pool.current
                initial = tensor_hash(dict(current.model.named_parameters()))
                with capture(current, actual_ids):
                    for role, prompt in prompts[1:]:
                        actual.append(pool.complete(role, prompt))
                self.assertEqual(actual, expected)
                self.assertEqual(actual_ids, expected_ids[1:])
                def without_timing(value):
                    value["events"] = [{k: v for k, v in row.items() if k != "elapsed_seconds"}
                                       for row in value["events"]]
                    return value
                self.assertEqual(without_timing(pool.ledger.snapshot()), without_timing(ledger.snapshot()))
                self.assertEqual(len(pool.loads), 1)
                self.assertEqual(pool.snapshot()["residency_strategy"], "shared-base-adapter")
                self.assertNotEqual(current.role_tokenizers["actor"].eos_token_id,
                                    current.role_tokenizers["analyzer"].eos_token_id)
                ids = torch.tensor([[4, 5, 6]])
                with torch.no_grad():
                    on = current.model(ids).logits
                    with current.model.disable_adapter():
                        off = current.model(ids).logits
                self.assertFalse(torch.allclose(on, off))
                with patch.object(current.model, "generate", side_effect=RuntimeError("injected generation failure")):
                    with self.assertRaisesRegex(RuntimeError, "injected"):
                        pool.complete("actor", "JSON:")
                self.assertEqual(pool.ledger.events[-1]["status"], "error")
                self.assertTrue(torch.equal(on, current.model(ids).logits))
                with self.assertRaises(BudgetExceeded):
                    pool.complete("analyzer", "x " * 200)
                self.assertEqual(initial, tensor_hash(dict(current.model.named_parameters())))
                pool.reset()
                self.assertEqual(pool.ledger.snapshot()["charged_tokens"], 0)
                self.assertEqual(pool.generations, [])
                with capture(current, actual_ids):
                    self.assertEqual(pool.complete("actor", "JSON:"), expected[0])
                self.assertEqual(actual_ids[-1], expected_ids[0])
                self.assertIs(pool.current, current)
                self.assertEqual(pool.loads, [])
            finally:
                pool.close()
            self.assertIsNone(pool.current)
            from intentlab.formal_data import write_jsonl
            from intentlab.residency_probe import run_probe
            from test_residency_probe import development_tasks
            write_jsonl(root / "development.jsonl", development_tasks())
            with self.assertRaises(BudgetExceeded):
                run_probe(paths, root / "development.jsonl", root / "too-short-probe", device="cpu",
                          max_new_tokens=2, context_limit=128)
            failed = json.loads((root / "too-short-probe/status.json").read_text())
            self.assertEqual(failed["status"], "failed")
            self.assertTrue((root / "too-short-probe/failure-pool.json").exists())
            probe = run_probe(paths, root / "development.jsonl", root / "probe", device="cpu",
                              max_new_tokens=2, context_limit=16384)
            self.assertEqual(probe["status"], "completed")
            self.assertTrue(probe["exact_outputs_and_tokens_equal"])
            self.assertTrue(probe["accounting_equal_except_time"])
            self.assertTrue(probe["assets_unchanged"])
            self.assertEqual(probe["modes"]["cold-task-reload"]["load_count"], 6)
            self.assertEqual(probe["modes"]["shared-condition-resident"]["load_count"], 1)
            with self.assertRaises(FileExistsError):
                run_probe(paths, root / "development.jsonl", root / "probe", device="cpu",
                          max_new_tokens=2, context_limit=16384)
