from copy import deepcopy
import json
import importlib.util
from pathlib import Path
import tempfile
import unittest

from test_execution_protocol import fixture
from build_execution_development import development_tasks
from intentlab.core import digest
from intentlab.execution_data import load_execution_tasks, load_references
from intentlab.formal_data import read_jsonl, write_jsonl
from intentlab.programmatic_labels import export_programmatic
from intentlab.programmatic_protocol import SCOPE, source_record, validation_record
from intentlab.protocol import check_spec, freeze, verify
from intentlab.spec_reference import verify_references


def programmatic_fixture(root, model=None, source=None):
    spec = fixture(root, model, source)
    tasks, rows = development_tasks()
    tasks = tasks[:4]
    for task, split in zip(tasks, ('train', 'validation', 'test', 'ood')):
        task['split'] = split
    refs = {r['task_id']: r for r in rows if r['task_id'] in {t['id'] for t in tasks}}
    cases = read_jsonl(spec['dataset']['cases'])
    out = root/'programmatic'
    export_programmatic(cases, tasks, refs, out)
    write_jsonl(root/'all-tasks.jsonl', tasks)
    write_jsonl(root/'all-references.jsonl', list(refs.values()))
    spec['schema_version'] = 3
    spec['label_scope'] = SCOPE
    spec['dataset'] = {'cases': spec['dataset']['cases'], 'labels': str(out/'programmatic-labels.jsonl'),
        'tasks': str(root/'all-tasks.jsonl'), 'references': str(root/'all-references.jsonl'), 'export': str(out)}
    spec['evidence']['programmatic_validation'] = str(root/'programmatic-validation.json')
    Path(spec['evidence']['programmatic_validation']).write_text(json.dumps(validation_record(cases, tasks, refs)), encoding='utf-8')
    Path(spec['evidence']['semantic_dedup_review']).write_text(json.dumps(source_record(cases)), encoding='utf-8')
    heldout = load_execution_tasks(spec['execution']['tasks'])
    reference = load_references(spec['execution']['references'], heldout)
    Path(spec['evidence']['execution_and_oracle_audit']).write_text(json.dumps(verify_references(heldout, reference)), encoding='utf-8')
    (root/'reviews.jsonl').unlink()
    return spec


class ProgrammaticProtocolTests(unittest.TestCase):
    def test_v3_freezes_without_human_reviews_and_training_never_reads_gold(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec = programmatic_fixture(root/'fixture')
            self.assertTrue(check_spec(spec)['ready'], check_spec(spec))
            lock = freeze(spec, root/'lock.json')
            self.assertIn('programmatic_binding', lock)
            self.assertNotIn('reviews', lock['annotation_inputs'])
            for row in list(lock['annotation_inputs'].values()) + list(lock['evidence'].values()) + list(lock['execution_binding']['files'].values()):
                Path(row['path']).unlink(missing_ok=True)
            for path in Path(spec['dataset']['export']).rglob('*'):
                if path.is_file() and path.name not in ('train.jsonl', 'validation.jsonl'):
                    path.unlink()
            self.assertTrue(verify(lock, 'training')['verified'])
            with self.assertRaises(OSError):
                verify(lock, 'all')

    def test_changed_programmatic_labels_cannot_be_hidden_by_manifest_hashes(self):
        with tempfile.TemporaryDirectory() as temp:
            spec = programmatic_fixture(Path(temp))
            path = Path(spec['dataset']['labels'])
            labels = read_jsonl(path)
            labels[0]['findings'][0]['status'] = 'violated'
            write_jsonl(path, labels)
            manifest_path = Path(spec['dataset']['export'])/'manifest.json'
            manifest = json.loads(manifest_path.read_text())
            manifest['labels_hash'] = digest(labels)
            manifest_path.write_text(json.dumps(manifest))
            self.assertFalse(check_spec(spec)['ready'])

    def test_changed_reference_is_rejected_and_old_review_fields_are_not_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            spec = programmatic_fixture(Path(temp))
            changed = deepcopy(spec)
            changed['dataset']['reviews'] = 'not-an-allowed-v3-field'
            self.assertFalse(check_spec(changed)['ready'])
            path = Path(spec['dataset']['references'])
            refs = read_jsonl(path)
            task = read_jsonl(spec['dataset']['tasks'])[0]
            refs[0]['files'][task['output_path']] = []
            write_jsonl(path, refs)
            self.assertFalse(check_spec(spec)['ready'])

    def test_original_payload_reuse_is_rejected_even_if_ids_and_templates_change(self):
        with tempfile.TemporaryDirectory() as temp:
            spec = programmatic_fixture(Path(temp))
            cases = read_jsonl(spec['dataset']['cases'])
            cases[1]['public']['inputs'] = deepcopy(cases[0]['public']['inputs'])
            with self.assertRaisesRegex(ValueError, 'payload reused'):
                source_record(cases)

    def test_unchanged_v3_all_verification_and_missing_machine_binding(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec = programmatic_fixture(root/'fixture')
            lock = freeze(spec, root/'lock.json')
            self.assertTrue(verify(lock, 'all')['verified'])
            del lock['programmatic_binding']
            lock['lock_hash'] = digest({k:v for k,v in lock.items() if k!='lock_hash'})
            with self.assertRaisesRegex(ValueError, 'binding missing'):
                verify(lock, 'training')

    def test_programmatic_controller_keeps_development_selection_without_reviewers(self):
        from test_controller_plan import prepare_controller_plan
        from test_frozen_execution import FakePool
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            spec = programmatic_fixture(root/'fixture')
            selection = prepare_controller_plan(spec, root, FakePool)
            path = Path(spec['evidence']['controller_ablation_audit'])
            plan = json.loads(path.read_text())
            del plan['reviewers']
            plan.update(schema_version=2, label_scope=SCOPE)
            path.write_text(json.dumps(plan))
            lock = freeze(spec, root/'lock.json')
            self.assertEqual(lock['controller_binding']['selection'], selection['selection'])
            self.assertTrue(verify(lock, 'all')['verified'])


@unittest.skipUnless(all(importlib.util.find_spec(m) for m in ('torch', 'transformers', 'peft')), 'Optional ML dependencies')
class ProgrammaticMatrixTests(unittest.TestCase):
    def test_six_real_tiny_workers_resume_without_machine_labels_or_heldout_inputs(self):
        from intentlab.fixtures import build_tasks
        from intentlab.sft_data import export_sft
        from intentlab.neural import train_neural
        from intentlab.matrix import run_matrix
        from intentlab.execution_models import bind_execution_models, verify_execution_models
        from test_neural import configuration
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            export_sft(build_tasks(), root/'base-data')
            train_neural(dict(configuration(root/'base-data'), max_length=4096, steps=2, eval_every=1, defer_test=True), root/'base')
            spec = programmatic_fixture(root/'fixture', root/'base/model', Path(__file__).resolve().parents[1])
            spec['training']['max_length'] = 4096
            lock = freeze(spec, root/'lock.json')
            for record in list(lock['annotation_inputs'].values()) + list(lock['evidence'].values()) + list(lock['execution_binding']['files'].values()):
                Path(record['path']).unlink(missing_ok=True)
            for path in Path(spec['dataset']['export']).rglob('*'):
                if path.is_file() and path.name not in ('train.jsonl', 'validation.jsonl'):
                    path.unlink()
            partial = run_matrix(lock, root/'matrix', engineering=True, stop_after_updates=1)
            self.assertEqual(partial['status'], 'interrupted')
            complete = run_matrix(lock, root/'matrix', engineering=True, resume=True)
            if complete['status'] != 'completed':
                self.fail('\n'.join(p.read_text(encoding='utf-8') for p in (root/'matrix').glob('*.log')))
            self.assertEqual(len(complete['paired_audit']), 3)
            self.assertEqual(len(complete['jobs'][0]['attempts']), 2)
            binding = bind_execution_models(lock, root/'matrix', root/'models-lock.json', engineering=True)
            self.assertTrue(verify_execution_models(lock, binding, engineering=True)['verified'])
