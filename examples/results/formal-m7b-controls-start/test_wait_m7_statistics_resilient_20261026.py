"""Read-only observation retry fixtures; no SSH, models, backup or dispatch."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import wait_m7_statistics_resilient_20261026 as recovery

tempfile.tempdir = str(Path(__file__).resolve().parent)
READY = json.dumps({'ready': True, 'supervisor_status': 'completed', 'parent': None})
LIVE = json.dumps({'ready': False, 'supervisor_status': 'running', 'parent': {'engineering_fixture': True, 'start_ticks': '893622222'}})


class RetryTests(unittest.TestCase):
    def run_fixture(self, replies, expected_error=None):
        with tempfile.TemporaryDirectory() as name:
            watch = Path(name) / 'watch'
            with patch.object(recovery.bridge, 'WATCH', watch), patch.object(recovery.bridge, 'run_remote', side_effect=replies) as remote, patch.object(recovery.time, 'sleep') as sleep:
                if expected_error:
                    with self.assertRaises(expected_error):
                        recovery.await_m7()
                else:
                    self.assertTrue(recovery.await_m7()['ready'])
            state = json.loads((watch / 'status.json').read_text())
            self.assertFalse(state['statistics_dispatched_by_wait_phase'])
            self.assertTrue(all(call.args[1].endswith(' --probe') for call in remote.call_args_list))
            return state, remote.call_count, [call.args[0] for call in sleep.call_args_list]

    def test_ssh_255_retries_only_read_only_probe(self):
        state, count, sleeps = self.run_fixture([subprocess.CalledProcessError(255, ['engineering-ssh']), READY])
        self.assertEqual(count, 2)
        self.assertEqual(sleeps, [10])
        self.assertEqual(len(state['probe_errors']), 1)
        self.assertEqual(state['status'], 'm7_ready_for_backup')

    def test_observation_timeout_does_not_restart_model(self):
        state, count, sleeps = self.run_fixture([subprocess.TimeoutExpired(['engineering-ssh'], 180), READY])
        self.assertEqual(count, 2)
        self.assertEqual(sleeps, [10])
        self.assertEqual(state['probe_errors'][0]['error_type'], 'TimeoutExpired')

    def test_three_consecutive_failures_stop(self):
        state, count, sleeps = self.run_fixture([subprocess.CalledProcessError(255, ['engineering-ssh']) for _ in range(3)], RuntimeError)
        self.assertEqual(count, 3)
        self.assertEqual(sleeps, [10, 30])
        self.assertEqual(state['status'], 'observation_or_admission_failed')
        self.assertEqual(len(state['probe_errors']), 3)

    def test_nontransport_remote_failure_is_not_retried(self):
        state, count, sleeps = self.run_fixture([subprocess.CalledProcessError(1, ['engineering-probe'])], subprocess.CalledProcessError)
        self.assertEqual(count, 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(state['probe_errors'], [])

    def test_missing_original_handles_stop_without_retry(self):
        missing = json.dumps({'ready': False, 'supervisor_status': 'running', 'parent': None, 'active_children': []})
        state, count, sleeps = self.run_fixture([missing], AssertionError)
        self.assertEqual(count, 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(state['status'], 'observation_or_admission_failed')

    def test_changed_m7_process_identity_stops_without_retry(self):
        changed = json.dumps({'ready': False, 'supervisor_status': 'running', 'parent': {'start_ticks': 'other'}})
        state, count, sleeps = self.run_fixture([changed], AssertionError)
        self.assertEqual(count, 1)
        self.assertEqual(sleeps, [])
        self.assertEqual(state['status'], 'observation_or_admission_failed')

    def test_successful_observation_resets_consecutive_error_count(self):
        error = lambda: subprocess.CalledProcessError(255, ['engineering-ssh'])
        state, count, sleeps = self.run_fixture([error(), error(), LIVE, error(), error(), READY])
        self.assertEqual(count, 6)
        self.assertEqual(sleeps, [10, 30, 60, 10, 30])
        self.assertEqual(len(state['probe_errors']), 4)
        self.assertEqual(state['consecutive_probe_errors'], 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
