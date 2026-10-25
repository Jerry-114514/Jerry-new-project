"""Filesystem recovery checks with byte fixtures; no actual model loading."""
import io
import hashlib
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from intentlab.model_backup import create_model_backup, file_sha, inventory
from scripts.restore_model_backup import restore
from tests.test_model_backup import fixture


class ModelRestoreTests(unittest.TestCase):
    def test_fresh_restore_matches_source_and_refuses_overwrite_or_wrong_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root / 'job')
            create_model_backup(root / 'job', root / 'backup', engineering=True)
            archive = root / 'backup/model.tar'
            expected = file_sha(archive)
            with self.assertRaises(ValueError):
                restore(archive, '0' * 64, root / 'wrong')
            self.assertFalse((root / 'wrong').exists())
            result = restore(archive, expected, root / 'restored')
            self.assertEqual(result['restored_files'], inventory(root / 'job'))
            self.assertFalse(result['model_or_pickle_loaded'])
            self.assertFalse(result['training_resume_verified'])
            with self.assertRaises(FileExistsError):
                restore(archive, expected, root / 'restored')

    def test_copy_failure_preserves_failed_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root / 'job')
            create_model_backup(root / 'job', root / 'backup', engineering=True)
            archive = root / 'backup/model.tar'
            with patch('scripts.restore_model_backup.shutil.copyfileobj', side_effect=OSError('fixture disk failure')):
                with self.assertRaises(OSError):
                    restore(archive, file_sha(archive), root / 'restored')
            receipt = json.loads((root / 'restored/restore-receipt.json').read_text())
            self.assertEqual(receipt['status'], 'failed')
            self.assertEqual(receipt['error_type'], 'OSError')

    def test_unsafe_archive_is_rejected_before_output_creation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = root / 'unsafe.tar'
            with tarfile.open(archive, 'w:') as handle:
                member = tarfile.TarInfo('../outside')
                member.size = 1
                handle.addfile(member, io.BytesIO(b'x'))
            with self.assertRaises(ValueError):
                restore(archive, file_sha(archive), root / 'restored')
            self.assertFalse((root / 'restored').exists())
            self.assertFalse((root / 'outside').exists())

    def test_windows_aliases_and_file_directory_conflicts_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for number, names in enumerate((['CON'], ['nested/name.'], ['A', 'a'], ['file', 'file/child'])):
                with self.subTest(names=names):
                    archive = root / (str(number) + '.tar')
                    index = {'kind': 'model_checkpoint_bundle_index', 'schema_version': 1,
                             'files': {name: {'bytes': 1, 'sha256': hashlib.sha256(b'x').hexdigest()} for name in names}}
                    with tarfile.open(archive, 'w:') as handle:
                        for name, data in [('backup-index.json', json.dumps(index).encode()),
                                           *[(name, b'x') for name in names]]:
                            member = tarfile.TarInfo(name)
                            member.size = len(data)
                            handle.addfile(member, io.BytesIO(data))
                    out = root / ('out-' + str(number))
                    with self.assertRaises(ValueError):
                        restore(archive, file_sha(archive), out)
                    self.assertFalse(out.exists())


if __name__ == '__main__':
    unittest.main()
