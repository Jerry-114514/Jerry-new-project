from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from intentlab.core import digest
from intentlab.formal_data import read_jsonl
from intentlab.protocol import freeze
from intentlab.test_material_seal import create_test_seal,validate_test_seal,validate_test_seal_binding
from test_programmatic_protocol import programmatic_fixture


class TestMaterialSealTests(unittest.TestCase):
    def fixture(self,root):
        spec=programmatic_fixture(root)
        seal=Path(spec['evidence']['test_sealing']);seal.unlink()
        return spec,seal

    def test_complete_material_seals_exclusively_and_changed_config_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            spec,path=self.fixture(Path(d));binding=create_test_seal(spec,path)
            self.assertEqual(binding['heldout_case_counts'],{'test':1,'ood':1})
            self.assertEqual(len(binding['files']),10)
            with self.assertRaises(FileExistsError):create_test_seal(spec,path)
            changed=deepcopy(spec);changed['budgets']['max_new_tokens']+=1
            with self.assertRaisesRegex(ValueError,'candidate'):
                validate_test_seal(changed,read_jsonl(spec['dataset']['cases']))

    def test_changed_gold_and_plain_text_certificates_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            spec,path=self.fixture(Path(d));create_test_seal(spec,path)
            gold=Path(spec['dataset']['export'])/'heldout/test/gold.jsonl'
            gold.write_text(gold.read_text()+'\n')
            with self.assertRaisesRegex(ValueError,'content changed'):
                validate_test_seal(spec,read_jsonl(spec['dataset']['cases']))
            path.write_text('sealed, all checked')
            with self.assertRaises(ValueError):validate_test_seal(spec,read_jsonl(spec['dataset']['cases']))

    def test_missing_gold_coverage_and_existing_attempt_refuse_creation(self):
        for attempt in [False,True]:
            with self.subTest(attempt=attempt),tempfile.TemporaryDirectory() as d:
                spec,path=self.fixture(Path(d));export=Path(spec['dataset']['export'])
                if attempt:(export.parent/'diagnostic-old-generate.claim.json').write_text('{}')
                else:(export/'heldout/test/gold.jsonl').write_text('{}\n')
                with self.assertRaises(ValueError):create_test_seal(spec,path)
                self.assertFalse(path.exists())

    def test_training_metadata_binding_survives_removed_gold_and_detects_forgery(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);spec,path=self.fixture(root/'fixture');binding=create_test_seal(spec,path)
            lock=freeze(spec,root/'engineering.lock.json')
            lock['test_seal_binding']=binding
            lock['lock_hash']=digest({k:v for k,v in lock.items() if k!='lock_hash'})
            # Unit engineering lock: call the same formal metadata validator
            # explicitly, without claiming an actual formal protocol or dataset.
            for record in binding['files'].values():Path(record['path']).unlink(missing_ok=True)
            path.unlink()
            with patch('intentlab.protocol.file_hash',side_effect=AssertionError('No seal/gold I/O allowed')):
                self.assertTrue(validate_test_seal_binding(lock))
            changed=deepcopy(lock);changed['test_seal_binding']['files']['dataset/heldout/test/gold.jsonl']['sha256']='0'*64
            with self.assertRaisesRegex(ValueError,'inputs'):
                validate_test_seal_binding(changed)

    def test_self_consistent_new_seal_cannot_hide_changed_candidate_spec(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);spec,path=self.fixture(root/'fixture');binding=create_test_seal(spec,path)
            lock=freeze(spec,root/'engineering.lock.json');lock['test_seal_binding']=binding
            changed=deepcopy(lock);changed['spec']['training']['lr']*=2
            with self.assertRaisesRegex(ValueError,'binding'):
                validate_test_seal_binding(changed)
