import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.run_procedural_followup import dependency_state, main, process_identity


class DependentFollowupTests(unittest.TestCase):
    def arguments(self,root):
        selection=root/'selection'
        selection.mkdir()
        (selection/'plan.json').write_text('{}')
        scorer=root/'scorer.py'
        scorer.write_text('must not execute')
        intake=root/'intake.py'
        intake.write_text('must not import')
        baseline=root/'baseline'
        baseline.mkdir()
        return argparse.Namespace(source=root/'source',out=root/'followup',baseline=baseline,
            selection=selection,scorer=scorer,intake_module=intake,dependency_pid=42,timeout_minutes=1,
            selection_sha256=hashlib.sha256((selection/'plan.json').read_bytes()).hexdigest(),
            scorer_sha256=hashlib.sha256(scorer.read_bytes()).hexdigest(),
            intake_sha256=hashlib.sha256(intake.read_bytes()).hexdigest())

    def test_failed_predecessor_never_starts_scorer_or_gpu_job(self):
        with tempfile.TemporaryDirectory() as directory:
            args=self.arguments(Path(directory))
            (args.baseline/'inference-status.json').write_text(json.dumps({'status':'failed'}))
            with patch('scripts.run_procedural_followup.subprocess.check_output',side_effect=['b4a757afc7c01332734fb6e4c2f08f3f7fcceef9','']),patch('scripts.run_procedural_followup.process_identity',return_value=None),patch('scripts.run_procedural_followup.subprocess.run') as launch:
                with self.assertRaisesRegex(RuntimeError,'without completion'):
                    main(args)
                launch.assert_not_called()
            record=json.loads((args.out/'status.json').read_text())
            self.assertEqual(record['status'],'failed')
            self.assertFalse((args.out/'natural-execution').exists())

    def test_completed_state_with_partial_raw_output_cannot_start_successor(self):
        with tempfile.TemporaryDirectory() as directory:
            args=self.arguments(Path(directory))
            (args.baseline/'inference-status.json').write_text(json.dumps({'status':'completed'}))
            for name in ('A','B3','B4'):
                path=args.baseline/name
                path.mkdir()
                (path/'manifest.json').write_text(json.dumps({'status':'completed','case_count':600}))
                (path/'predictions.jsonl').write_text('{}\n'*(599 if name=='B4' else 600))
            with patch('scripts.run_procedural_followup.subprocess.check_output',side_effect=['b4a757afc7c01332734fb6e4c2f08f3f7fcceef9','']),patch('scripts.run_procedural_followup.process_identity',return_value=None),patch('scripts.run_procedural_followup.subprocess.run') as launch:
                with self.assertRaisesRegex(ValueError,'Incomplete baseline'):
                    main(args)
                launch.assert_not_called()
            self.assertEqual(json.loads((args.out/'status.json').read_text())['status'],'failed')

    def test_stat_parser_handles_spaces_and_parentheses_in_process_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            process=root/'42'
            process.mkdir()
            # Fields 3..21, followed by starttime field22.
            (process/'stat').write_text('42 (a worker (name)) '+' '.join(['R']+['0']*18+['12345']))
            (process/'cmdline').write_bytes(b'/python\0/driver.py\0infer\0')
            result=process_identity(42,root)
            self.assertEqual(result,{'pid':42,'start_ticks':'12345','argv':['/python','/driver.py','infer']})
            self.assertEqual(dependency_state(result,process_identity(42,root)),'live')
            self.assertIsNone(process_identity(99,root))

    def test_pid_reuse_or_command_change_refuses_successor(self):
        expected={'pid':42,'start_ticks':'12345','argv':['/driver','infer']}
        for actual in [dict(expected,start_ticks='99999'),dict(expected,argv=['different-command'])]:
            with self.assertRaisesRegex(RuntimeError,'identity changed'):
                dependency_state(expected,actual)
        self.assertEqual(dependency_state(expected,None),'terminal')

    def test_exited_zombie_is_terminal_even_without_cmdline(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            process=root/'42'
            process.mkdir()
            (process/'stat').write_text('42 (exited worker) '+' '.join(['Z']+['0']*18+['12345']))
            self.assertIsNone(process_identity(42,root))
