from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from intentlab.formal_data import read_jsonl
from intentlab.history_candidate_data import build
from intentlab.procedural_data import build as build_base


class HistoryCandidateTests(unittest.TestCase):
    def fixture(self, root):
        plan=json.loads(Path('configs/procedural-data-plan.json').read_text())
        plan['counts']={'train':8,'validation':8,'test':8,'ood':2}
        (root/'plan.json').write_text(json.dumps(plan))
        (root/'seeds.json').write_text(json.dumps({s:format(i+1,'064x') for i,s in enumerate(plan['counts'])}))
        with redirect_stdout(io.StringIO()): build_base(root/'plan.json',root/'seeds.json',root/'base')

    def test_append_preserves_original_gold_exports_and_source_units(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.fixture(root)
            result=build(root/'base',root/'history')
            self.assertEqual(result['views_by_split'],{'train':48,'validation':48,'test':48,'ood':12})
            self.assertEqual(result['source_groups_by_split'],{'train':8,'validation':8,'test':8,'ood':2})
            self.assertEqual(result['new_independent_sources'],0)
            old=read_jsonl(root/'base/cases.jsonl');new=read_jsonl(root/'history/cases.jsonl')
            self.assertEqual(new[:len(old)],old)
            for relative in ['train.jsonl','validation.jsonl','programmatic-labels.jsonl',
                'heldout/test/cases.jsonl','heldout/test/gold.jsonl','heldout/ood/cases.jsonl','heldout/ood/gold.jsonl']:
                self.assertTrue((root/'history/export'/relative).read_bytes().startswith((root/'base/export'/relative).read_bytes()))
            self.assertFalse(result['formal_protocol_frozen'])
            with self.assertRaises(FileExistsError): build(root/'base',root/'history')

    def test_reject_changed_base_before_writing_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.fixture(root)
            p=root/'base/summary.json';summary=json.loads(p.read_text());summary['cases_hash']='forged';p.write_text(json.dumps(summary))
            with self.assertRaisesRegex(ValueError,'identity changed'):build(root/'base',root/'history')
            self.assertFalse((root/'history').exists())
