import hashlib
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from run_limited_30h_pipeline import archive_data,archive_unbacked_states


class LimitedArchiveTests(unittest.TestCase):
    def test_data_archive_keeps_private_raw_data_without_duplicating_checkpoint_weights(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            for name in ('training/train.jsonl','sealed/gold.jsonl','jobs/D-seed-0/result.json','jobs/D-seed-0/latest.pt','jobs/D-seed-0/model/adapter.safetensors'):
                p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(b'fixture')
            r=archive_data(root)
            with tarfile.open(r['path']) as a:
                names=set(a.getnames());index=json.load(a.extractfile('backup-index.json'))
                self.assertIn('sealed/gold.jsonl',names)
                self.assertNotIn('jobs/D-seed-0/latest.pt',names)
                self.assertNotIn('jobs/D-seed-0/model/adapter.safetensors',names)
                self.assertEqual(names,set(index['files'])|{'backup-index.json'})
                for name,row in index['files'].items():self.assertEqual(hashlib.sha256(a.extractfile(name).read()).hexdigest(),row['sha256'])

    def test_unfinished_weights_are_preserved_under_an_explicit_unvalidated_label(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'jobs/D-seed-0/latest.pt';p.parent.mkdir(parents=True);p.write_bytes(b'not a trusted pickle')
            (root/'backups').mkdir();r=archive_unbacked_states(root)
            self.assertEqual(r['scope'],'unvalidated_partial_state')
            with tarfile.open(r['path']) as a:
                index=json.load(a.extractfile('backup-index.json'))
                self.assertEqual(index['kind'],'unvalidated_partial_state')
                self.assertEqual(a.extractfile('jobs/D-seed-0/latest.pt').read(),b'not a trusted pickle')


if __name__=='__main__':unittest.main()
