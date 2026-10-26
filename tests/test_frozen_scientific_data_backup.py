import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('scientific_backup', ROOT / 'scripts/backup_frozen_scientific_data.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class ScientificBackupTests(unittest.TestCase):
    def setUp(self):
        (ROOT / 'tmp').mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / 'tmp', prefix='scientific-backup-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.data = self.root / 'dataset'
        self.data.mkdir()
        lock = {'spec': {'dataset': {}, 'execution': {}}, 'annotation_inputs': {},
                'execution_binding': {'files': {}}, 'dataset_export': {'files_sha256': {
                    name: '' for name in ['train.jsonl', 'validation.jsonl', 'manifest.json',
                                          'programmatic-labels.jsonl', 'heldout/test/cases.jsonl',
                                          'heldout/test/gold.jsonl', 'heldout/ood/cases.jsonl',
                                          'heldout/ood/gold.jsonl']}}}
        names = ['cases.jsonl', 'tasks.jsonl', 'references.jsonl', 'execution-tasks.jsonl',
                 'execution-references.jsonl'] + ['export/' + n for n in lock['dataset_export']['files_sha256']]
        for name in names:
            p = self.data / name
            p.parent.mkdir(parents=True, exist_ok=True)
            # Deliberately not JSON: a byte backup must not parse scientific data.
            p.write_bytes(b'opaque bytes, not labels to interpret: ' + name.encode())
        for key, name in [('cases', 'cases.jsonl'), ('tasks', 'tasks.jsonl'),
                          ('references', 'references.jsonl'), ('labels', 'export/programmatic-labels.jsonl')]:
            p = self.data / name
            lock['annotation_inputs'][key] = {'path': p.as_posix(), 'sha256': backup.sha_file(p)}
            lock['spec']['dataset'][key] = p.as_posix()
        lock['spec']['dataset']['export'] = (self.data / 'export').as_posix()
        lock['dataset_export']['root'] = (self.data / 'export').as_posix()
        for name in lock['dataset_export']['files_sha256']:
            lock['dataset_export']['files_sha256'][name] = backup.sha_file(self.data / 'export' / name)
        for key, name in [('tasks', 'execution-tasks.jsonl'), ('references', 'execution-references.jsonl')]:
            p = self.data / name
            lock['execution_binding']['files'][key] = {'path': p.as_posix(), 'sha256': backup.sha_file(p)}
            lock['spec']['execution'][key] = p.as_posix()
        self.lock = lock
        self.lock_path = self.root / 'lock.json'
        self.save_lock()

    def save_lock(self):
        body = {k: v for k, v in self.lock.items() if k != 'lock_hash'}
        self.identity = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                                   separators=(',', ':')).encode()).hexdigest()
        self.lock['lock_hash'] = self.identity
        self.lock_path.write_text(json.dumps(self.lock), encoding='utf-8')

    def make_backup(self):
        out = self.root / 'copy'
        receipt = backup.create(self.lock_path, self.identity, out)
        return out / 'frozen-scientific-data.tar.gz', receipt

    def test_round_trip_opaque_bytes_and_exclude_unbound_secrets(self):
        (self.data / 'private-seed.json').write_text('not included')
        archive, receipt = self.make_backup()
        self.assertEqual(14, receipt['member_count'])
        self.assertEqual(receipt, backup.verify(archive, self.lock_path, self.identity, receipt['archive_sha256']))
        self.assertFalse(receipt['labels_interpreted'])
        self.assertFalse(receipt['m8_complete'])
        self.assertNotIn('private-seed', json.dumps(receipt))
        with self.assertRaises(FileExistsError):
            backup.create(self.lock_path, self.identity, archive.parent)

    def test_changed_source_rejected_before_output(self):
        (self.data / 'cases.jsonl').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'source changed'):
            backup.create(self.lock_path, self.identity, self.root / 'copy')
        self.assertFalse((self.root / 'copy').exists())

    def test_lock_and_archive_trust_anchors(self):
        archive, receipt = self.make_backup()
        with self.assertRaisesRegex(ValueError, 'Archive SHA256'):
            backup.verify(archive, self.lock_path, self.identity, '0' * 64)
        self.lock['warning'] = 'modified'
        self.lock_path.write_text(json.dumps(self.lock), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'lock identity'):
            backup.verify(archive, self.lock_path, self.identity, receipt['archive_sha256'])

    def test_member_tampering_duplicate_missing_and_symlink_rejected(self):
        archive, _ = self.make_backup()
        with tarfile.open(archive) as tar:
            originals = [(m.name, tar.extractfile(m).read()) for m in tar]
        for mode in ['changed', 'missing', 'duplicate', 'symlink', 'extra']:
            target = self.root / (mode + '.tar.gz')
            entries = list(originals)
            if mode == 'changed':
                entries[0] = (entries[0][0], b'bad bytes')
            if mode == 'missing':
                entries.pop()
            if mode == 'duplicate':
                entries.append(entries[0])
            if mode == 'extra':
                entries.append(('../private-seed.json', b'no'))
            with tarfile.open(target, 'w:gz') as tar:
                for idx, (name, data) in enumerate(entries):
                    member = tarfile.TarInfo(name)
                    member.size = len(data)
                    if mode == 'symlink' and idx == 0:
                        member.type = tarfile.SYMTYPE
                        member.linkname = '/etc/passwd'
                        member.size = 0
                        tar.addfile(member)
                    else:
                        tar.addfile(member, io.BytesIO(data))
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                backup.verify(target, self.lock_path, self.identity, backup.sha_file(target))

    def test_unexpected_export_member_rejected(self):
        self.lock['dataset_export']['files_sha256']['../private-seed.json'] = '0' * 64
        self.save_lock()
        with self.assertRaisesRegex(ValueError, 'Unexpected export members'):
            backup.create(self.lock_path, self.identity, self.root / 'copy')
        self.assertFalse((self.root / 'copy').exists())


if __name__ == '__main__':
    unittest.main()
