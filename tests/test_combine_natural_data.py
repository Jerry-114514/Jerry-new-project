from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest

from intentlab.combine_natural_data import build
from intentlab.core import digest, initial_state
from intentlab.execution_data import load_execution_tasks, load_references
from intentlab.execution_oracle import evaluate_execution
from intentlab.formal_data import read_jsonl, write_jsonl
from intentlab.procedural_data import build as build_base


class CombinedNaturalDataTests(unittest.TestCase):
    def fixture(self,root):
        plan=json.loads(Path('configs/procedural-data-plan.json').read_text())
        plan['counts']={'train':8,'validation':8,'test':8,'ood':2}
        (root/'plan.json').write_text(json.dumps(plan))
        (root/'seeds.json').write_text(json.dumps({s:format(i+1,'064x') for i,s in enumerate(plan['counts'])}))
        with redirect_stdout(io.StringIO()): build_base(root/'plan.json',root/'seeds.json',root/'base')
        tasks=load_execution_tasks(root/'base/tasks.jsonl')
        selected=[next(t for t in tasks if t['split']==s) for s in ['train','validation']]
        refs=load_references(root/'base/references.jsonl',tasks)
        subset={t['id']:refs[t['id']] for t in selected}
        selection=root/'selection';selection.mkdir()
        execution=root/'execution';execution.mkdir()
        write_jsonl(selection/'tasks.jsonl',selected)
        write_jsonl(selection/'references.jsonl',list(subset.values()))
        # Explicitly synthetic provenance: no real model call or human label.
        models={'actor':'/synthetic-unit-model-not-real'}
        records=[]
        for t in selected:
            state=initial_state(t)
            records.append({'task_id':t['id'],'source_task_id':t['source_task_id'],'split':t['split'],
                'policy':'none','actor':'LanguageModelActor','status':'error',
                'final_state':{'files':deepcopy(state.files),'events':[]},
                'metrics':evaluate_execution(t,state,refs[t['id']]),
                'model_pool':{'models':models,'generations':[{'role':'actor','model_path':models['actor'],
                    'text':'SYNTHETIC UNIT FAILURE, NOT REAL INFERENCE','prompt_hash':'fixture-only'}]}})
        write_jsonl(execution/'runs.jsonl',records)
        manifest={'kind':'public_contract_development_execution','scope':'development','status':'completed',
            'actor':'local_model','executor_is_language_model':True,'task_hash':digest(selected),
            'offline_reference_hash':digest(subset),'policies':['none'],'model_paths':models}
        (execution/'manifest.json').write_text(json.dumps(manifest))
        return selected,records

    def test_failures_append_views_without_new_sources_or_heldout_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.fixture(root)
            result=build(root/'base',root/'selection',root/'execution',root/'combined')
            self.assertEqual(result['views_by_split'],{'train':34,'validation':34,'test':32,'ood':8})
            self.assertEqual(result['source_groups_by_split'],{'train':8,'validation':8,'test':8,'ood':2})
            self.assertEqual(result['natural_execution_status_counts'],{'error':2})
            self.assertEqual(result['new_independent_source_tasks'],0)
            for split in ('test','ood'):
                for name in ('cases.jsonl','gold.jsonl'):
                    relative=Path('export/heldout')/split/name
                    self.assertEqual((root/'base'/relative).read_bytes(),(root/'combined'/relative).read_bytes())
            self.assertFalse(result['formal_protocol_frozen'])
            with self.assertRaises(FileExistsError): build(root/'base',root/'selection',root/'execution',root/'combined')

    def test_heldout_selection_rejected_before_invalid_raw_access(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.fixture(root)
            task=next(t for t in read_jsonl(root/'base/tasks.jsonl') if t['split']=='test')
            write_jsonl(root/'selection/tasks.jsonl',[task])
            (root/'execution/runs.jsonl').write_text('INVALID RAW MUST NOT BE READ')
            with self.assertRaisesRegex(ValueError,'refuses test/OOD'):
                build(root/'base',root/'selection',root/'execution',root/'combined')
            self.assertFalse((root/'combined').exists())

    def test_snapshot_tampering_refused_without_combined_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);_,rows=self.fixture(root)
            rows[0]['final_state']['files']['forged.json']=[]
            write_jsonl(root/'execution/runs.jsonl',rows)
            with self.assertRaisesRegex(ValueError,'Replayed artifact'):
                build(root/'base',root/'selection',root/'execution',root/'combined')
            self.assertFalse((root/'combined').exists())
