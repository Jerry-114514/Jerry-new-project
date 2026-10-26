"""Byte fixtures and mocked transport only, without formal data or remote jobs."""
import ast
import hashlib
import io
import json
from pathlib import Path
import shlex
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import backup_completed_m6_20261026 as bridge

tempfile.tempdir = str(bridge.WORKSPACE / 'tmp')


def fixture(root, short=False):
    files = {'interactions/interactions.jsonl': b'{"engineering_fixture":true}\n' * (1199 if short else 1200),
             'reveal/runs.jsonl': b'{"engineering_fixture":true}\n' * 1200}
    manifests = {}
    for directory, kind, status, seal in [('interactions', 'frozen_execution_interactions', 'sealed', 'seal_hash'),
                                         ('reveal', 'frozen_execution_reveal', 'completed', 'receipt_hash')]:
        manifest = {'kind': kind, 'status': status, 'scope': 'formal', 'protocol_hash': bridge.LOCK,
                    'model_binding_hash': bridge.BINDING,
                    'files_sha256': {n.split('/', 1)[1]: hashlib.sha256(raw).hexdigest()
                                     for n, raw in files.items() if n.startswith(directory + '/')}}
        if directory == 'interactions':
            manifest.update(offline_references_opened=False, injected_pool=False)
        else:
            manifest['interaction_seal_hash'] = manifests['interactions']['seal_hash']
        manifest[seal] = bridge.digest(manifest)
        manifests[directory] = manifest
    for directory, manifest in manifests.items():
        files[directory + '/manifest.json'] = json.dumps(manifest).encode()
    files['supervisor-status.json'] = json.dumps({'status': 'completed', 'm6_complete': True,
        'execution_receipt_hash': manifests['reveal']['receipt_hash'],
        'stages': [{'action': a, 'status': 'completed', 'exit_code': 0}
                   for a in ('interact', 'verify', 'reveal', 'verify-reveal')]}).encode()
    archive = root / 'fixture.tar'
    with tarfile.open(archive, 'w:') as handle:
        for name, raw in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(raw)
            handle.addfile(member, io.BytesIO(raw))
    expected = {'protocol_hash': bridge.LOCK, 'binding_hash': bridge.BINDING, 'm6_supervisor_completed': True,
                'archive_bytes': archive.stat().st_size, 'archive_sha256': bridge.sha(archive),
                'execution_receipt_hash': manifests['reveal']['receipt_hash'],
                'interaction_seal_hash': manifests['interactions']['seal_hash'],
                'interaction_records': 1200, 'scored_records': 1200,
                'files': {n: {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()} for n, raw in files.items()}}
    return archive, expected


class TransferTests(unittest.TestCase):
    def test_complete_archive_is_reverified(self):
        with tempfile.TemporaryDirectory() as name:
            archive, expected = fixture(Path(name))
            result = bridge.verify_archive(archive, expected)
            self.assertTrue(result['all_archive_members_reverified'])
            self.assertEqual(result['interaction_records'], 1200)
            self.assertFalse(result['references_reopened_for_backup'])

    def test_corrupt_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            archive, expected = fixture(Path(name))
            with archive.open('ab') as handle:
                handle.write(b'corruption')
            with self.assertRaises(AssertionError):
                bridge.verify_archive(archive, expected)

    def test_missing_record_is_rejected_even_with_correct_member_hashes(self):
        with tempfile.TemporaryDirectory() as name:
            archive, expected = fixture(Path(name), short=True)
            with self.assertRaises(AssertionError):
                bridge.verify_archive(archive, expected)

    def test_wait_handles_completed_status_before_parent_exits(self):
        with tempfile.TemporaryDirectory() as name:
            watch = Path(name) / 'watch'
            replies = [json.dumps({'ready': False, 'supervisor_status': 'completed', 'parent': {'fixture': True}}),
                       json.dumps({'ready': True, 'supervisor_status': 'completed', 'parent': None})]
            with patch.object(bridge, 'WATCH', watch), patch.object(bridge, 'run_remote', side_effect=replies), patch.object(bridge.time, 'sleep'):
                self.assertTrue(bridge.await_m6()['ready'])
            self.assertFalse(json.loads((watch / 'status.json').read_text())['m7_dispatched_by_wait_phase'])

    def test_missing_original_handle_does_not_start_any_job(self):
        with tempfile.TemporaryDirectory() as name:
            watch = Path(name) / 'watch'
            reply = json.dumps({'ready': False, 'supervisor_status': 'running', 'parent': None, 'active_children': []})
            with patch.object(bridge, 'WATCH', watch), patch.object(bridge, 'run_remote', return_value=reply):
                with self.assertRaises(AssertionError):
                    bridge.await_m6()
            self.assertEqual(json.loads((watch / 'status.json').read_text())['status'], 'observation_or_admission_failed')

    def test_live_m6_does_not_create_backup_directory(self):
        with tempfile.TemporaryDirectory() as name:
            out = Path(name) / 'not-created'
            with patch.object(bridge, 'LOCAL', out), patch.object(bridge, 'run_remote', return_value='{"ready":false}'), patch.object(sys, 'argv', ['bridge']):
                with self.assertRaises(AssertionError):
                    bridge.main()
            self.assertFalse(out.exists())

    def test_dispatch_code_is_exclusive_and_parses_without_execution(self):
        with patch.object(bridge, 'run_remote', return_value='{"engineering_mock":true}') as remote:
            self.assertTrue(bridge.dispatch_m7({'engineering_fixture': True})['engineering_mock'])
        code = shlex.split(remote.call_args.args[1])[2]
        ast.parse(code)
        self.assertIn('start_new_session=True', code)
        self.assertIn(".open('x')", code)
        self.assertIn('run_formal_ablation_20261026.py', code)


if __name__ == '__main__':
    unittest.main(verbosity=2)
