from copy import deepcopy
import json
from pathlib import Path
import unittest

from intentlab.contract_perturbations import perturbations, verify_expectations
from intentlab.procedural_data import generate
from intentlab.programmatic_labels import generate_labels
from intentlab.programmatic_protocol import source_record


class ProceduralDataTests(unittest.TestCase):
    def plan(self):
        plan=json.loads(Path('configs/procedural-data-plan.json').read_text())
        plan['counts']={'train':80,'validation':8,'test':8,'ood':2}
        return plan

    def seeds(self):
        # Public synthetic unit seeds, never used for research candidate batches.
        return {split:format(i+1,'064x') for i,split in enumerate(('train','validation','test','ood'))}

    def test_reproducible_structural_split_and_private_source_draws(self):
        plan,seeds=self.plan(),self.seeds()
        first=generate(plan,seeds)
        self.assertEqual(first,generate(plan,seeds))
        tasks,refs,cases,ledger=first
        self.assertEqual(len(tasks),98)
        self.assertEqual(len(cases),392)
        self.assertEqual(len({t['template_id'] for t in tasks}),26)
        self.assertEqual(sum(r['blocked'] for r in ledger),8)
        self.assertTrue(all(t['source']['origin']=='program_generated' for t in tasks))
        self.assertTrue(all(all(v not in json.dumps(t) for v in seeds.values()) for t in tasks))
        ood={t['family'] for t in tasks if t['split']=='ood'}
        seen={t['family'] for t in tasks if t['split']!='ood'}
        self.assertFalse(ood & seen)
        self.assertEqual(len(source_record(cases)['source_groups']),98)

    def test_blocked_fault_matrix_has_independent_expected_states(self):
        tasks,refs,cases,ledger=generate(self.plan(),self.seeds())
        ids={r['task_id'] for r in ledger if r['blocked']}
        selected=[t for t in tasks if t['id'] in ids]
        selected_refs={t['id']:refs[t['id']] for t in selected}
        faults,expected=perturbations(selected,selected_refs)
        verify_expectations(generate_labels(faults,selected,selected_refs),expected)
        self.assertEqual(len(faults),8*8)

    def test_split_seed_changes_do_not_rewrite_other_splits(self):
        plan=self.plan();plan['counts']={'train':8,'validation':8,'test':8,'ood':2}
        seeds=self.seeds()
        first=generate(plan,seeds)[0]
        seeds['test']='f'*64
        second=generate(plan,seeds)[0]
        self.assertEqual([t for t in first if t['split']!='test'],[t for t in second if t['split']!='test'])
        self.assertNotEqual([t['id'] for t in first if t['split']=='test'],[t['id'] for t in second if t['split']=='test'])

    def test_shared_split_seed_is_rejected(self):
        seeds=self.seeds();seeds['test']=seeds['train']
        with self.assertRaisesRegex(ValueError,'distinct private'):
            generate(self.plan(),seeds)
