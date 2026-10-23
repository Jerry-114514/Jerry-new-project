from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest

from intentlab.formal_data import read_jsonl, write_jsonl
from intentlab.procedural_data import make_task
from scripts.prepare_natural_development import prepare


class NaturalSelectionTests(unittest.TestCase):
    def tasks(self):
        plan=json.loads(Path('configs/procedural-data-plan.json').read_text())
        # Public fixture seeds are not used in research batches.
        return [make_task('stable_sort',split,ordinal,format(seed,'064x'),plan)[0]
                for split,seed in [('train',1),('validation',2)] for ordinal in (0,1,9,19)]

    def test_selection_preserves_groups_and_is_invariant_to_input_order(self):
        with tempfile.TemporaryDirectory() as directory,redirect_stdout(io.StringIO()):
            root=Path(directory)
            tasks=self.tasks()
            write_jsonl(root/'tasks.jsonl',tasks)
            first=prepare(root/'tasks.jsonl',root/'first')
            write_jsonl(root/'tasks.jsonl',list(reversed(tasks)))
            second=prepare(root/'tasks.jsonl',root/'second')
            self.assertEqual(first['selected_ids'],second['selected_ids'])
            self.assertEqual(first['tasks_hash'],second['tasks_hash'])
            self.assertEqual(first['selected_source_tasks'],4)
            self.assertEqual(first['expected_visibility_views'],8)
            self.assertFalse(first['collection_started'])
            selected=read_jsonl(root/'first/tasks.jsonl')
            self.assertEqual({t['split'] for t in selected},{'train','validation'})
            self.assertEqual(len(read_jsonl(root/'first/references.jsonl')),4)
            with self.assertRaises(FileExistsError):
                prepare(root/'tasks.jsonl',root/'first')

    def test_missing_blocked_stratum_refused_without_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            write_jsonl(root/'tasks.jsonl',self.tasks()[:2])
            with self.assertRaisesRegex(ValueError,'Both present-field and blocked'):
                prepare(root/'tasks.jsonl',root/'selection')
            self.assertFalse((root/'selection').exists())

    def test_heldout_source_never_enters_selection_or_reference_generation(self):
        with tempfile.TemporaryDirectory() as directory,redirect_stdout(io.StringIO()):
            root=Path(directory)
            tasks=self.tasks()
            plan=json.loads(Path('configs/procedural-data-plan.json').read_text())
            heldout=make_task('stable_sort','test',0,format(3,'064x'),plan)[0]
            heldout.update(id='heldout-only',source_task_id='heldout-only')
            write_jsonl(root/'tasks.jsonl',tasks+[heldout])
            result=prepare(root/'tasks.jsonl',root/'selection')
            self.assertNotIn('heldout-only',result['selected_ids'])
            self.assertNotIn('heldout-only',{r['task_id'] for r in read_jsonl(root/'selection/references.jsonl')})
