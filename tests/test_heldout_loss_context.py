from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from intentlab.diagnostic_protocol import heldout_loss
from intentlab.formal_data import read_jsonl
from test_programmatic_protocol import programmatic_fixture


class CharacterTokenizer:
    chat_template=None
    bos_token_id=None
    eos_token_id=0
    def encode(self,text,add_special_tokens=False):return [ord(c)+1 for c in text]


class Scalar:
    def item(self):return 1.0


class HeldoutLossContextTests(unittest.TestCase):
    def fixture(self,root,context):
        spec=programmatic_fixture(root/'fixture')
        spec['training']['max_length']=128
        cases=read_jsonl(Path(spec['dataset']['export'])/'heldout/ood/cases.jsonl')
        labels=read_jsonl(Path(spec['dataset']['export'])/'heldout/ood/gold.jsonl')
        gold={r['case_id']:{f['id']:f for f in r['findings']} for r in labels}
        backend=SimpleNamespace(tokenizer=CharacterTokenizer(),context=context,device='cpu',
            torch=SimpleNamespace(no_grad=nullcontext),model=object(),close=lambda:None)
        return {'spec':spec},cases,gold,backend

    def test_complete_ood_loss_uses_evaluation_context_and_preserves_target_count(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);protocol,cases,gold,backend=self.fixture(root,40960)
            seen=[]
            def batch(examples,*args):seen.extend(examples);return examples[0]
            def loss(model,encoded):return Scalar(),sum(x!=-100 for x in encoded['labels'][1:])
            backend.tokenizer.pad_token_id=0
            with patch('intentlab.diagnostic_protocol.backend_for',return_value=backend), \
                    patch('intentlab.neural.batch_tensors',side_effect=batch),patch('intentlab.neural.token_loss',side_effect=loss):
                rows=heldout_loss(protocol,'fixture-only-not-real-model',cases,gold,root/'loss.jsonl')
            self.assertGreater(len(seen[0]['input_ids']),protocol['spec']['training']['max_length'])
            self.assertEqual(rows[0]['target_tokens'],sum(x!=-100 for x in seen[0]['labels'][1:]))
            self.assertEqual(len(rows),1)

    def test_true_evaluation_overflow_is_rejected_and_backend_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);protocol,cases,gold,backend=self.fixture(root,64)
            closed=[];backend.close=lambda:closed.append(True)
            with patch('intentlab.diagnostic_protocol.backend_for',return_value=backend),self.assertRaisesRegex(ValueError,'no silent truncation'):
                heldout_loss(protocol,'fixture-only-not-real-model',cases,gold,root/'loss.jsonl')
            self.assertEqual(closed,[True])
