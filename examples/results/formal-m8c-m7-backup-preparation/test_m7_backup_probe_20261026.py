"""Probe identity tests on temporary engineering journals, without SSH or GPUs."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import prepare_m7_backup_20261026 as probe

tempfile.tempdir = str(Path(__file__).resolve().parent)


def journals(root, changed_claim=False):
    status = {'kind': 'frozen_m7_ablation_supervisor', 'pid': 123, 'start_ticks': 'engineering-parent',
              'driver_sha256': 'd97fff09401b8579c52b25f68883b1e37adf4b57174cfe8a877650b26cdd06b7',
              'started_unix': 1, 'runtime_commit': probe.COMMIT, 'protocol_hash': probe.LOCK,
              'binding_hash': probe.BINDING, 'status': 'running', 'active_action': 'interact',
              'stages': [{'action': 'interact', 'child_pid': 456, 'child_start_ticks': 'engineering-worker'}]}
    claim = dict(status)
    if changed_claim:
        claim['start_ticks'] = 'changed'
    (root / 'supervisor-status.json').write_text(json.dumps(status))
    (root / 'supervisor.claim.json').write_text(json.dumps(claim))


class ProbeTests(unittest.TestCase):
    def test_live_handles_are_reported_without_backup_creation(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            journals(root)
            output = io.StringIO()
            handles = {123: {'start_ticks': 'engineering-parent', 'state': 'S'},
                       456: {'start_ticks': 'engineering-worker', 'state': 'R'}}
            with patch.object(probe, 'ROOT', root), patch.object(probe, 'identity', side_effect=handles.get), patch.object(sys, 'argv', ['probe', '--probe']), redirect_stdout(output):
                probe.main()
            observed = json.loads(output.getvalue())
            self.assertFalse(observed['ready'])
            self.assertEqual(observed['parent']['start_ticks'], 'engineering-parent')
            self.assertEqual(len(observed['active_children']), 1)
            self.assertEqual(len(list(root.iterdir())), 2)

    def test_changed_claim_identity_is_rejected(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            journals(root, changed_claim=True)
            with patch.object(probe, 'ROOT', root), patch.object(sys, 'argv', ['probe', '--probe']):
                with self.assertRaises(AssertionError):
                    probe.main()
            self.assertFalse((root / 'sealed-ablation.tar').exists())

    def test_reused_process_id_cannot_be_treated_as_original(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            journals(root)
            with patch.object(probe, 'ROOT', root), patch.object(probe, 'identity', return_value={'start_ticks': 'other-process', 'state': 'R'}), patch.object(sys, 'argv', ['probe', '--probe']):
                with self.assertRaises(AssertionError):
                    probe.main()
            self.assertFalse((root / 'sealed-ablation.tar').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
