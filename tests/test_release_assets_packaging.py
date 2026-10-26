"""Reconstruct six byte fixtures from Release assets; no real model claims."""
import hashlib
import json
from pathlib import Path
import sys
import tarfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from package_release_assets import JOBS, SHARED, package, sha
import test_adapter_release_preparation as preparation_fixture


class ReleaseAssetTests(unittest.TestCase):
    def setUp(self):
        self.fixture = preparation_fixture.AdapterReleasePreparationTests('test_exact_allowlist_hashes_and_fresh_replay')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        for row in self.fixture.plan['files']:
            if row['path'].split('/')[-1] in SHARED:
                path = Path(row['source'])
                path.write_bytes(('shared/' + path.name).encode())
                row.update(bytes=path.stat().st_size, sha256=sha(path))
        self.fixture.save()
        self.prepared = self.fixture.run_prepare()
        self.root = self.fixture.root
        self.source = self.root / 'out'

    def run_package(self, name='release'):
        return package(self.source, sha(self.source / 'manifest.json'), self.root / name)

    def test_all_assets_reproducible_and_reconstruct_exact_six_exports(self):
        first = self.run_package()
        self.assertEqual(first['assets'], 10)
        self.assertEqual(first, self.run_package('replay'))
        for path in (self.root / 'release').iterdir():
            self.assertEqual(path.read_bytes(), (self.root / 'replay' / path.name).read_bytes())
        reconstructed, shared = {}, {}
        for path in (self.root / 'release').glob('*.tar.gz'):
            with tarfile.open(path, 'r:gz') as tar:
                for member in tar.getmembers():
                    self.assertEqual(member.mtime, 0)
                    raw = tar.extractfile(member).read()
                    if member.name.startswith('tokenizer/'):
                        shared[member.name.split('/')[-1]] = raw
                    else:
                        reconstructed[member.name] = raw
        for job in JOBS:
            for name, raw in shared.items():
                reconstructed[job + '/' + name] = raw
        self.assertEqual(set(reconstructed), set(self.prepared['files']))
        for name, raw in reconstructed.items():
            self.assertEqual(hashlib.sha256(raw).hexdigest(), self.prepared['files'][name]['sha256'])
        for line in (self.root / 'release/SHA256SUMS.txt').read_text().splitlines():
            checksum, name = line.split('  ')
            self.assertEqual(sha(self.root / 'release' / name), checksum)
        self.assertNotIn('.gitattributes', {p.name for p in (self.root / 'release').iterdir()})
        with self.assertRaises(ValueError):
            self.run_package()

    def test_changed_or_unbound_source_fails_before_output(self):
        with self.assertRaises(ValueError):
            package(self.source, '0' * 64, self.root / 'release')
        path = self.source / JOBS[0] / 'adapter_model.safetensors'
        path.write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.run_package()
        self.assertFalse((self.root / 'release').exists())

    def test_shared_tokenizer_requires_identical_hashes_even_with_rebound_manifest(self):
        path = self.source / JOBS[0] / 'tokenizer.json'
        path.write_bytes(b'different-but-bound')
        manifest_path = self.source / 'manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['files'][JOBS[0] + '/tokenizer.json'] = {'sha256': sha(path), 'bytes': path.stat().st_size}
        manifest_path.write_text(json.dumps(manifest))
        with self.assertRaises(ValueError):
            self.run_package()
        self.assertFalse((self.root / 'release').exists())


if __name__ == '__main__':
    unittest.main()
