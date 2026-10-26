"""Byte-copy allowlist tests; fixtures are not trained adapters."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from prepare_adapter_release import ASSETS, JOBS, prepare, sha


class AdapterReleasePreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = {'files': [], 'official_revision': 'synthetic-fixture-only'}
        self.receipt = {'kind': 'completed_formal_training_matrix_receipt', 'completed_jobs': 6,
                        'off_host_verified_backups': 6, 'protocol_hash': 'p' * 64,
                        'binding_hash': 'b' * 64, 'selections': {}}
        for job in JOBS:
            for name in sorted(ASSETS):
                path = self.root / 'source' / job / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((job + '/' + name).encode())
                self.plan['files'].append({'path': f'endpoints/{job}/model/{name}', 'source': str(path),
                                           'bytes': path.stat().st_size, 'sha256': sha(path)})
            self.receipt['selections'][job] = {'step': 7, 'export_files_sha256': {
                'adapter_model.safetensors': sha(self.root / 'source' / job / 'adapter_model.safetensors')}}
        # A full source plan can include other assets, but never copy them.
        self.plan['files'].append({'path': 'endpoints/cosine-seed-0/latest.pt', 'source': 'must-not-read'})
        self.plan_path, self.receipt_path = self.root / 'plan.json', self.root / 'receipt.json'
        self.save()

    def save(self):
        self.plan_path.write_text(json.dumps(self.plan))
        self.receipt_path.write_text(json.dumps(self.receipt))

    def run_prepare(self, name='out'):
        return prepare(self.plan_path, sha(self.plan_path), self.receipt_path, sha(self.receipt_path), self.root / name)

    def test_exact_allowlist_hashes_and_fresh_replay(self):
        first, second = self.run_prepare(), self.run_prepare('replay')
        self.assertEqual(first, second)
        self.assertEqual(first['file_count'], 36)
        actual = {p.relative_to(self.root / 'out').as_posix() for p in (self.root / 'out').rglob('*') if p.is_file()}
        self.assertEqual(actual, set(first['files']) | {'manifest.json', '.gitattributes', 'README.md'})
        for name in actual:
            self.assertEqual((self.root / 'out' / name).read_bytes(), (self.root / 'replay' / name).read_bytes())
        self.assertFalse(first['public_upload_performed'])
        self.assertFalse(first['model_forward_verified_by_preparation'])
        with self.assertRaises(ValueError):
            self.run_prepare()

    def test_changed_source_or_wrong_checkpoint_rejected_before_copy(self):
        source = Path(self.plan['files'][0]['source'])
        source.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.run_prepare()
        self.plan['files'][0]['sha256'] = sha(source)
        self.plan['files'][0]['bytes'] = source.stat().st_size
        self.receipt['selections']['cosine-seed-0']['export_files_sha256']['adapter_model.safetensors'] = '0' * 64
        self.save()
        with self.assertRaises(ValueError):
            self.run_prepare()
        self.assertFalse((self.root / 'out').exists())

    def test_missing_duplicate_or_unbound_inputs_rejected(self):
        with self.assertRaises(ValueError):
            prepare(self.plan_path, '0' * 64, self.receipt_path, sha(self.receipt_path), self.root / 'out')
        item = self.plan['files'].pop(0)
        self.save()
        with self.assertRaises(ValueError):
            self.run_prepare()
        self.plan['files'].extend([item, item])
        self.save()
        with self.assertRaises(ValueError):
            self.run_prepare()


if __name__ == '__main__':
    unittest.main()
