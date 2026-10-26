"""Engineering fixtures only: no models, gold, SSH, claims or formal execution."""
import ast
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.core import digest
import run_formal_ablation_20261026 as driver


def fixture():
    execution = {'kind': 'frozen_execution_reveal', 'status': 'completed', 'scope': 'formal',
                 'protocol_hash': driver.LOCK, 'model_binding_hash': driver.BINDING_HASH,
                 'engineering_fixture': True}
    execution['receipt_hash'] = digest(execution)
    status = {'pid': 412780, 'start_ticks': '889586178', 'runtime_commit': driver.COMMIT,
              'protocol_hash': driver.LOCK, 'binding_hash': driver.BINDING_HASH,
              'status': 'completed', 'm6_complete': True, 'execution_receipt_hash': execution['receipt_hash'],
              'stages': [{'action': a, 'status': 'completed', 'exit_code': 0}
                         for a in ('interact', 'verify', 'reveal', 'verify-reveal')]}
    attestation = {'kind': 'observed_off_host_m6_backup_gate', 'protocol_hash': driver.LOCK,
                   'binding_hash': driver.BINDING_HASH, 'execution_receipt_hash': execution['receipt_hash'],
                   'all_archive_members_reverified': True, 'interaction_records': 1200, 'scored_records': 1200}
    return status, execution, attestation


class AdmissionTests(unittest.TestCase):
    def test_complete_receipts_pass_pure_gate(self):
        driver.validate_m6_gate(*fixture(), digest)

    def test_live_m6_cannot_admit_m7(self):
        status, execution, attestation = fixture()
        status.update(status='running', m6_complete=False)
        with self.assertRaises(AssertionError):
            driver.validate_m6_gate(status, execution, attestation, digest)

    def test_each_failed_or_missing_stage_is_rejected(self):
        for index in range(4):
            with self.subTest(index=index):
                status, execution, attestation = fixture()
                status['stages'][index].update(status='failed', exit_code=1)
                with self.assertRaises(AssertionError):
                    driver.validate_m6_gate(status, execution, attestation, digest)
                status, execution, attestation = fixture()
                status['stages'].pop(index)
                with self.assertRaises(AssertionError):
                    driver.validate_m6_gate(status, execution, attestation, digest)

    def test_unverified_or_incomplete_backup_is_rejected(self):
        for change in ({'all_archive_members_reverified': False}, {'interaction_records': 1199},
                       {'scored_records': 1199}, {'execution_receipt_hash': 'wrong'},
                       {'protocol_hash': 'wrong'}, {'binding_hash': 'wrong'}):
            with self.subTest(change=change):
                status, execution, attestation = fixture()
                attestation.update(change)
                with self.assertRaises(AssertionError):
                    driver.validate_m6_gate(status, execution, attestation, digest)

    def test_modified_receipt_rejected_even_if_receipt_string_unchanged(self):
        status, execution, attestation = fixture()
        execution['engineering_fixture'] = False
        with self.assertRaises(AssertionError):
            driver.validate_m6_gate(status, execution, attestation, digest)

    def test_four_commands_match_prepared_frozen_plan(self):
        source = Path(driver.__file__).read_text()
        main = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'main')
        assignments = [n for n in main.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id in {'common', 'stages'} for t in n.targets)]
        scope = {'str': str, 'PROTOCOL': PurePosixPath(str(driver.PROTOCOL).replace('\\', '/')),
                 'BINDING': PurePosixPath(str(driver.BINDING).replace('\\', '/')),
                 'M5': PurePosixPath(str(driver.M5).replace('\\', '/')),
                 'M6': PurePosixPath(str(driver.M6).replace('\\', '/')),
                 'ROOT': PurePosixPath(str(driver.ROOT).replace('\\', '/'))}
        exec(compile(ast.Module(body=assignments, type_ignores=[]), '<command-shapes-only>', 'exec'), scope)
        actual = [[driver.PYTHON, '-m', 'intentlab.frozen_ablation', a, *scope['common'], *extra]
                  for a, extra in scope['stages']]
        plan_path = Path('runs/frozen-next-stage-command-plan-20261025.json')
        if not plan_path.exists():
            plan_path = Path(__file__).with_name('frozen-commands.json')
        plan = json.loads(plan_path.read_text())
        self.assertEqual(actual, [s['argv'] for s in plan['stage_commands'] if s['module'] == 'frozen_ablation'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
