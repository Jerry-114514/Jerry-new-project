"""Engineering gates and command checks only; no formal statistical results."""
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.core import digest
import run_formal_statistics_reproduction_20261026 as driver


def fixture():
    receipt = {'kind': 'frozen_ablation_reveal', 'status': 'completed', 'scope': 'formal',
               'protocol_hash': driver.LOCK, 'model_binding_hash': driver.BINDING_HASH,
               'upstream': {'execution_receipt_hash': 'engineering-fixture-only'}}
    receipt['receipt_hash'] = digest(receipt)
    status = {'kind': 'frozen_m7_ablation_supervisor', 'driver_sha256': driver.M7_DRIVER_HASH,
              'runtime_commit': driver.COMMIT, 'protocol_hash': driver.LOCK, 'binding_hash': driver.BINDING_HASH,
              'status': 'completed', 'm7_complete': True, 'pid': 123, 'start_ticks': 'fixture', 'started_unix': 1,
              'execution_receipt_hash': 'engineering-fixture-only', 'ablation_receipt_hash': receipt['receipt_hash'],
              'stages': [{'action': a, 'status': 'completed', 'exit_code': 0}
                         for a in ('interact', 'verify', 'reveal', 'verify-reveal')]}
    claim = deepcopy(status)
    backup = {'kind': 'observed_off_host_m7_backup_gate', 'protocol_hash': driver.LOCK,
              'binding_hash': driver.BINDING_HASH, 'ablation_receipt_hash': receipt['receipt_hash'],
              'all_archive_members_reverified': True, 'interaction_records': 1800, 'scored_records': 1800}
    return status, claim, receipt, backup


class StatisticsPreparationTests(unittest.TestCase):
    def test_complete_pure_gate(self):
        driver.validate_m7_gate(*fixture(), digest)

    def test_live_or_failed_m7_cannot_admit_statistics(self):
        for change in ({'status': 'running', 'm7_complete': False}, {'status': 'failed'},
                       {'driver_sha256': 'changed'}, {'runtime_commit': 'changed'}):
            with self.subTest(change=change):
                status, claim, receipt, backup = fixture()
                status.update(change)
                with self.assertRaises(AssertionError):
                    driver.validate_m7_gate(status, claim, receipt, backup, digest)

    def test_claim_identity_and_all_four_stages_required(self):
        status, claim, receipt, backup = fixture()
        claim['start_ticks'] = 'other'
        with self.assertRaises(AssertionError):
            driver.validate_m7_gate(status, claim, receipt, backup, digest)
        for index in range(4):
            status, claim, receipt, backup = fixture()
            status['stages'][index]['exit_code'] = 1
            with self.assertRaises(AssertionError):
                driver.validate_m7_gate(status, claim, receipt, backup, digest)

    def test_missing_or_mismatched_backup_rejected(self):
        for change in ({'all_archive_members_reverified': False}, {'interaction_records': 1799},
                       {'scored_records': 1799}, {'ablation_receipt_hash': 'wrong'}, {'binding_hash': 'wrong'}):
            with self.subTest(change=change):
                status, claim, receipt, backup = fixture()
                backup.update(change)
                with self.assertRaises(AssertionError):
                    driver.validate_m7_gate(status, claim, receipt, backup, digest)

    def test_changed_receipt_rejected_without_rehash(self):
        status, claim, receipt, backup = fixture()
        receipt['upstream']['execution_receipt_hash'] = 'changed'
        with self.assertRaises(AssertionError):
            driver.validate_m7_gate(status, claim, receipt, backup, digest)

    def test_original_commands_match_plan_and_replay_changes_only_destination(self):
        path_names = ('PROTOCOL', 'BINDING', 'M5', 'M6', 'M7', 'STATISTICS', 'REPLAY')
        with ExitStack() as stack:
            for name in path_names:
                stack.enter_context(patch.object(driver, name, PurePosixPath(str(getattr(driver, name)).replace('\\', '/'))))
            commands = driver.commands()
        plan_path = Path('runs/frozen-next-stage-command-plan-20261025.json')
        if not plan_path.exists():
            plan_path = Path(__file__).with_name('frozen-statistics-commands.json')
        plan = json.loads(plan_path.read_text())
        self.assertEqual([cmd for _, cmd in commands[:2]],
                         [s['argv'] for s in plan['stage_commands'] if s['module'] == 'frozen_statistics'])
        for first, replay in ((commands[0][1], commands[2][1]), (commands[1][1], commands[3][1])):
            self.assertEqual(first[:-1], replay[:-1])
            self.assertNotEqual(first[-1], replay[-1])
            self.assertNotIn('--engineering', first)


if __name__ == '__main__':
    unittest.main(verbosity=2)
