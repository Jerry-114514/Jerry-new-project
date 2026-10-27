import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from verify_30h_private_archive import verify


class PrivateArchiveTests(unittest.TestCase):
    def archive(self,root,content,index_content=None):
        path=Path(root)/'archive.tar'
        indexed=content if index_content is None else index_content
        index=json.dumps({'kind':'unvalidated_partial_state','files':{'state.pt':{'bytes':len(indexed),'sha256':hashlib.sha256(indexed).hexdigest()}}}).encode()
        with tarfile.open(path,'x:') as a:
            for name,raw in [('backup-index.json',index),('state.pt',content)]:
                header=tarfile.TarInfo(name);header.size=len(raw);a.addfile(header,io.BytesIO(raw))
        return path,hashlib.sha256(path.read_bytes()).hexdigest()

    def test_verification_does_not_deserialize_checkpoint_bytes(self):
        with tempfile.TemporaryDirectory() as d:
            path,sha=self.archive(d,b'not a loadable checkpoint')
            r=verify(path,sha);self.assertTrue(r['all_member_hashes_verified']);self.assertFalse(r['model_or_pickle_loaded'])

    def test_resealed_archive_cannot_hide_member_hash_mismatch(self):
        with tempfile.TemporaryDirectory() as d:
            path,sha=self.archive(d,b'changed',b'original')
            with self.assertRaises(ValueError):verify(path,sha)


if __name__=='__main__':unittest.main()
