"""Engineering byte fixtures and mocks only; no gold, model, SSH or claim execution."""
import ast
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shlex
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
import backup_completed_m5_scoring_20261026 as bridge
tempfile.tempdir = str(bridge.WORKSPACE / 'tmp')


def fixture(root, short=False):
    files = {name: b'{"engineering_byte_fixture":true}\n' * (1239 if short and index == 0 else 1240)
             for index, name in enumerate(bridge.LOSS_NAMES)}
    manifest = {'kind': 'frozen_diagnostic_reveal', 'status': 'completed', 'scope': 'formal',
                'protocol_hash': bridge.LOCK, 'model_binding_hash': bridge.BINDING,
                'test_loss_injected': False, 'gold_opened_after_claim': True,
                'files_sha256': {name: hashlib.sha256(value).hexdigest() for name, value in files.items()}}
    manifest['receipt_hash'] = bridge.digest(manifest)
    files['manifest.json'] = json.dumps(manifest).encode()
    archive = root / 'fixture.tar'
    with tarfile.open(archive, 'w:') as handle:
        for name, value in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(value)
            handle.addfile(member, io.BytesIO(value))
    expected = {'protocol_hash': bridge.LOCK, 'binding_hash': bridge.BINDING, 'm5_supervisor_completed': True,
                'archive_bytes': archive.stat().st_size, 'archive_sha256': bridge.sha(archive),
                'diagnostic_receipt_hash': manifest['receipt_hash'],
                'files': {name: {'bytes': len(value), 'sha256': hashlib.sha256(value).hexdigest()} for name, value in files.items()}}
    return archive, expected


class M5M6TransferTests(unittest.TestCase):
    def test_wait_advances_only_after_ready_without_dispatching(self):
        with tempfile.TemporaryDirectory() as name:
            watch = Path(name) / 'watch'
            replies = ['{"ready":false,"supervisor_status":"running","parent":{"engineering_fixture":true}}',
                       '{"ready":true,"supervisor_status":"completed","parent":null}']
            with patch.object(bridge, 'WATCH', watch), patch.object(bridge, 'run_remote', side_effect=replies), patch.object(bridge.time, 'sleep') as sleep:
                result = bridge.await_m5()
            self.assertTrue(result['ready'])
            sleep.assert_called_once_with(60)
            state = json.loads((watch / 'status.json').read_text())
            self.assertTrue(state['wait_phase_completed'])
            self.assertFalse(state['m6_dispatched_by_wait_phase'])

    def test_six_complete_populations_and_members_are_reverified(self):
        with tempfile.TemporaryDirectory() as name:
            archive, expected = fixture(Path(name))
            result = bridge.verify_archive(archive, expected)
            self.assertTrue(result['all_archive_members_reverified'])
            self.assertFalse(result['gold_or_references_reopened_for_backup'])

    def test_corrupt_archive_cannot_admit_m6(self):
        with tempfile.TemporaryDirectory() as name:
            archive, expected = fixture(Path(name))
            with archive.open('ab') as handle:
                handle.write(b'CORRUPTION')
            with self.assertRaises(AssertionError):
                bridge.verify_archive(archive, expected)

    def test_correct_hashes_do_not_hide_missing_loss_rows(self):
        with tempfile.TemporaryDirectory() as name:
            archive, expected = fixture(Path(name), short=True)
            with self.assertRaises(AssertionError):
                bridge.verify_archive(archive, expected)

    def test_unfinished_m5_creates_no_backup_or_execution_claim(self):
        with tempfile.TemporaryDirectory() as name:
            out = Path(name) / 'must-not-exist'
            with patch.object(bridge, 'LOCAL', out), patch.object(bridge, 'run_remote', return_value='{"ready":false}'), patch.object(sys, 'argv', ['backup']):
                with self.assertRaises(AssertionError):
                    bridge.main()
            self.assertFalse(out.exists())

    def test_dispatch_syntax_is_checked_without_remote_execution(self):
        with patch.object(bridge, 'run_remote', return_value='{"engineering_mock":true}') as remote:
            self.assertEqual(bridge.dispatch_m6({'engineering_fixture': True}), {'engineering_mock': True})
        command = remote.call_args.args[1]
        code = shlex.split(command)[2]
        ast.parse(code)
        self.assertIn('start_new_session=True', code)
        self.assertIn(".open('x')", code)

    def test_all_four_commands_match_frozen_plan(self):
        source = (bridge.WORKSPACE / 'tmp/run_formal_execution_20261026.py').read_text()
        main = next(node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == 'main')
        assignments = [node for node in main.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id in {'common', 'stages'} for target in node.targets)]
        scope = {'str': str, 'PROTOCOL': PurePosixPath('/root/autodl-tmp/history-shared-freeze-preparation-20261023/formal-protocol.lock.json'),
                 'BINDING': PurePosixPath('/root/autodl-tmp/formal-model-binding-20261025.json'),
                 'M5': PurePosixPath(bridge.REMOTE), 'ROOT': PurePosixPath('/root/autodl-tmp/formal-execution-run-20261025')}
        exec(compile(ast.Module(body=assignments, type_ignores=[]), '<registered-command-shape-only>', 'exec'), scope)
        actual = [[bridge.PYTHON, '-m', 'intentlab.frozen_execution', action, *scope['common'], *extra]
                  for action, extra in scope['stages']]
        plan = json.loads((bridge.WORKSPACE / 'runs/frozen-next-stage-command-plan-20261025.json').read_text())
        self.assertEqual(actual, [stage['argv'] for stage in plan['stage_commands'][3:7]])


if __name__ == '__main__':
    unittest.main(verbosity=2)
