import ast
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
import watch_formal_reveal_handoff_20261026 as gate

tempfile.tempdir = str(gate.WORKSPACE / 'tmp')


def write(path, value):
    path.write_text(json.dumps(value))


def completed_fixture(root):
    files = {}
    for condition in gate.CONDITIONS:
        files[condition + '/predictions.jsonl'] = b'BYTE FIXTURE ONLY, NOT A MODEL OUTPUT\n'
        files[condition + '/manifest.json'] = b'{"status":"completed"}'
    sums = {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}
    manifest = {'kind': 'frozen_diagnostic_predictions', 'status': 'sealed', 'scope': 'formal',
                'gold_loaded': False, 'protocol_hash': gate.LOCK, 'model_binding_hash': gate.BINDING,
                'conditions': gate.CONDITIONS, 'test_backend_injected': False, 'files_sha256': sums}
    manifest['seal_hash'] = gate.digest(manifest)
    files['manifest.json'] = json.dumps(manifest).encode()
    archive = root / 'sealed-predictions.tar'
    with tarfile.open(archive, 'w:') as handle:
        for name, value in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(value)
            handle.addfile(member, io.BytesIO(value))
    inventory = {'archive_sha256': gate.sha(archive), 'archive_bytes': archive.stat().st_size,
                 'prediction_seal_hash': manifest['seal_hash'],
                 'files': {name: {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()} for name, value in files.items()}}
    write(root / 'source-inventory.json', inventory)
    backup = {key: inventory[key] for key in ('archive_sha256', 'archive_bytes', 'prediction_seal_hash')}
    backup['verified_members'] = len(files)
    write(root / 'watcher-status.json', {'status': 'completed', 'backup': backup})


class HandoffGateTests(unittest.TestCase):
    def test_launch_request_is_syntax_valid_without_remote_execution(self):
        with patch.object(gate, 'remote_code', return_value={'test_only': True}) as remote:
            self.assertEqual(gate.launch({'test_fixture': True}), {'test_only': True})
        script = remote.call_args.args[0]
        ast.parse(script)
        self.assertIn('start_new_session=True', script)
        self.assertIn(".open('x')", script)

    def test_incomplete_failed_and_stale_backups_do_not_admit_scoring(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            write(root / 'watcher-status.json', {'status': 'watching', 'observed_utc': datetime.now(timezone.utc).isoformat()})
            self.assertIsNone(gate.backup_gate(root))
            write(root / 'watcher-status.json', {'status': 'failed'})
            with self.assertRaises(RuntimeError):
                gate.backup_gate(root)
            write(root / 'watcher-status.json', {'status': 'watching', 'observed_utc': (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()})
            with self.assertRaises(RuntimeError):
                gate.backup_gate(root)

    def test_completed_archive_is_reverified_and_corrupt_bytes_are_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            completed_fixture(root)
            receipt = gate.backup_gate(root)
            self.assertTrue(receipt['all_archive_members_reverified'])
            self.assertFalse(receipt['gold_read'])
            with (root / 'sealed-predictions.tar').open('ab') as handle:
                handle.write(b'CORRUPTION')
            with self.assertRaises(AssertionError):
                gate.backup_gate(root)

    def test_remote_commands_exactly_match_prepared_frozen_plan(self):
        source = (gate.WORKSPACE / 'tmp/run_formal_reveal_handoff_20261026.py').read_text()
        tree = ast.parse(source)
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        assignments = [node for node in main.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id in {'common', 'stages'} for target in node.targets)]
        scope = {'str': str, 'PROTOCOL': PurePosixPath('/root/autodl-tmp/history-shared-freeze-preparation-20261023/formal-protocol.lock.json'),
                 'BINDING': PurePosixPath('/root/autodl-tmp/formal-model-binding-20261025.json'),
                 'ROOT': PurePosixPath(gate.REMOTE)}
        exec(compile(ast.Module(body=assignments, type_ignores=[]), '<frozen-command-shape-only>', 'exec'), scope)
        actual = [[gate.PYTHON, '-m', 'intentlab.diagnostic_protocol', action, *scope['common'], *extra]
                  for action, extra in scope['stages']]
        plan = json.loads((gate.WORKSPACE / 'runs/frozen-next-stage-command-plan-20261025.json').read_text())
        self.assertEqual(actual, [row['argv'] for row in plan['stage_commands'][:3]])


if __name__ == '__main__':
    unittest.main(verbosity=2)
