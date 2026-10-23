"""Loss/gradient equivalence for causal masking and selective output heads."""
import importlib.util
from types import SimpleNamespace
import unittest


@unittest.skipUnless(importlib.util.find_spec('torch') and importlib.util.find_spec('transformers'), 'Optional ML dependencies')
class SupervisedLogitsTests(unittest.TestCase):
    def compare(self, selective):
        import torch
        from intentlab.neural import token_loss
        torch.manual_seed(17)

        class Base(torch.nn.Module):
            def __init__(self):
                super().__init__()
                self.embed = torch.nn.Embedding(19, 7)
                self.head = torch.nn.Linear(7, 19)
                self.seen = None

            def compute(self, input_ids, positions):
                hidden = self.embed(input_ids).cumsum(dim=1)
                self.seen = positions
                if positions is not None:
                    hidden = hidden[:, positions]
                return SimpleNamespace(logits=self.head(hidden))

        class Selective(Base):
            def forward(self, input_ids, attention_mask, use_cache, logits_to_keep=None):
                return self.compute(input_ids, logits_to_keep)

        class Fallback(Base):
            def forward(self, input_ids, attention_mask, use_cache):
                return self.compute(input_ids, None)

        base = (Selective if selective else Fallback)()
        # Exercise the PEFT-style wrapper signature, not just a naked base.
        class Wrapper(torch.nn.Module):
            def __init__(self, model):
                super().__init__()
                self.model = model
            def get_base_model(self):
                return self.model
            def forward(self, **kwargs):
                return self.model(**kwargs)

        model = Wrapper(base)
        batch = {'input_ids': torch.tensor([[1, 2, 3, 4, 5, 6], [7, 8, 9, 10, 0, 0]]),
                 'attention_mask': torch.tensor([[1, 1, 1, 1, 1, 1], [1, 1, 1, 1, 0, 0]]),
                 'labels': torch.tensor([[-100, -100, -100, 4, -100, 6], [-100, -100, 9, 10, -100, -100]])}
        output = model(input_ids=batch['input_ids'], attention_mask=batch['attention_mask'], use_cache=False)
        expected = torch.nn.functional.cross_entropy(output.logits[:, :-1].float().reshape(-1, 19), batch['labels'][:, 1:].reshape(-1), ignore_index=-100, reduction='sum')
        expected.backward()
        gradients = [p.grad.clone() for p in model.parameters()]
        model.zero_grad(set_to_none=True)
        actual, count = token_loss(model, batch)
        actual.backward()
        self.assertEqual(count, 4)
        torch.testing.assert_close(actual, expected, rtol=1e-6, atol=1e-6)
        for param, reference in zip(model.parameters(), gradients):
            torch.testing.assert_close(param.grad, reference, rtol=1e-5, atol=1e-6)
        if selective:
            self.assertEqual(base.seen.tolist(), [1, 2, 4])
        else:
            self.assertIsNone(base.seen)
        batch['labels'].fill_(-100)
        with self.assertRaisesRegex(ValueError, 'no supervised'):
            token_loss(model, batch)

    def test_selective_head_matches_dense_loss_and_all_parameter_gradients(self):
        self.compare(True)

    def test_fallback_matches_dense_loss_and_all_parameter_gradients(self):
        self.compare(False)

    def test_qwen_peft_loss_and_adapter_gradients_match_dense_head(self):
        import torch
        import transformers
        if not importlib.util.find_spec('peft') or not hasattr(transformers, 'Qwen3_5ForCausalLM'):
            self.skipTest('Qwen3.5 and PEFT required')
        from peft import LoraConfig, get_peft_model
        from intentlab.neural import token_loss
        torch.manual_seed(23)
        config = transformers.Qwen3_5TextConfig(vocab_size=32, hidden_size=32,
            intermediate_size=64, num_hidden_layers=1, num_attention_heads=2,
            num_key_value_heads=1, head_dim=16, layer_types=['full_attention'],
            max_position_embeddings=64, attention_dropout=0.0)
        model = get_peft_model(transformers.Qwen3_5ForCausalLM(config),
            LoraConfig(r=2, lora_alpha=4, lora_dropout=0.0,
                       target_modules=['q_proj', 'v_proj'], task_type='CAUSAL_LM'))
        # Nonzero B also checks gradients flowing through both adapter factors.
        for name, param in model.named_parameters():
            if 'lora_B' in name:
                torch.nn.init.normal_(param, std=0.02)
        model.eval()
        batch = {'input_ids': torch.tensor([[1, 2, 3, 4, 5], [6, 7, 8, 0, 0]]),
                 'attention_mask': torch.tensor([[1, 1, 1, 1, 1], [1, 1, 1, 0, 0]]),
                 'labels': torch.tensor([[-100, -100, 3, 4, 5], [-100, -100, 8, -100, -100]])}
        logits = model(input_ids=batch['input_ids'], attention_mask=batch['attention_mask'], use_cache=False).logits
        reference = torch.nn.functional.cross_entropy(logits[:, :-1].float().reshape(-1, 32), batch['labels'][:, 1:].reshape(-1), ignore_index=-100, reduction='sum')
        reference.backward()
        gradients = {name: p.grad.clone() for name, p in model.named_parameters() if p.requires_grad}
        model.zero_grad(set_to_none=True)
        actual, count = token_loss(model, batch)
        actual.backward()
        self.assertEqual(count, 4)
        torch.testing.assert_close(actual, reference, rtol=1e-5, atol=1e-6)
        for name, param in model.named_parameters():
            if param.requires_grad:
                torch.testing.assert_close(param.grad, gradients[name], rtol=1e-4, atol=1e-6)
