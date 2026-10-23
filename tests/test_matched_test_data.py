from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from intentlab.formal_data import read_jsonl
from intentlab.matched_test_data import build
from intentlab.procedural_data import build as build_base


class MatchedTestDataTests(unittest.TestCase):
    def fixture(self,root):
        plan=json.loads(Path('configs/procedural-data-plan.json').read_text())
        plan['counts']={'train':8,'validation':8,'test':8,'ood':2}
        (root/'plan.json').write_text(json.dumps(plan))
        seeds={split:format(i+1,'064x') for i,split in enumerate(plan['counts'])}
        # Fixed public fixture seeds are not research split seeds.
        (root/'seeds.json').write_text(json.dumps(seeds))
        (root/'new-seed.json').write_text(json.dumps({'seed':format(9,'064x')}))
        with redirect_stdout(io.StringIO()):
            build_base(root/'plan.json',root/'seeds.json',root/'base')
        return plan,seeds

    def test_layout_and_development_bytes_preserved_with_real_wording_change(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.fixture(root)
            summary=build(root/'base',root/'plan.json',root/'new-seed.json',root/'matched',count=8)
            self.assertFalse(summary['strict_iid_claim'])
            self.assertFalse(summary['formal_protocol_frozen'])
            self.assertEqual(summary['matched_test_views'],32)
            for split in ('train','validation'):
                self.assertEqual((root/'base/export'/f'{split}.jsonl').read_bytes(),(root/'matched/export'/f'{split}.jsonl').read_bytes())
            old=read_jsonl(root/'base/tasks.jsonl')
            new=read_jsonl(root/'matched/tasks.jsonl')
            test=[t for t in new if t['split']=='test']
            train=[t for t in new if t['split']=='train']
            required_by_family={t['family']:t['spec']['required_fields'] for t in train}
            self.assertTrue(all(len(t['inputs'])==1 and t['spec']['required_fields']==required_by_family[t['family']] for t in test))
            self.assertFalse({t['id'] for t in test}&{t['id'] for t in old})
            self.assertFalse({t['template_id'] for t in test}&{t['template_id'] for t in train})
            for task in test:
                self.assertTrue(task['request'].startswith('Every input row must provide'))
                self.assertTrue(all(r['quote'] in task['request'] for r in task['requirements']))
            self.assertEqual([t for t in old if t['split']=='ood'],[t for t in new if t['split']=='ood'])

    def test_seed_reuse_and_overwrite_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            _,seeds=self.fixture(root)
            (root/'new-seed.json').write_text(json.dumps({'seed':seeds['train']}))
            with self.assertRaisesRegex(ValueError,'reuse'):
                build(root/'base',root/'plan.json',root/'new-seed.json',root/'matched',count=8)
            self.assertFalse((root/'matched').exists())
            with self.assertRaises(FileExistsError):
                build(root/'base',root/'plan.json',root/'new-seed.json',root/'base',count=8)

    def test_base_mutation_refused_before_candidate_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            self.fixture(root)
            path=root/'base/tasks.jsonl'
            text=path.read_text(encoding='utf-8').replace('Required fields','Modified required fields',1)
            path.write_text(text,encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'payload changed'):
                build(root/'base',root/'plan.json',root/'new-seed.json',root/'matched',count=8)
            self.assertFalse((root/'matched').exists())
