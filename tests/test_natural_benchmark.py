import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.benchmark_after_natural import main, pressure_ids, profile
from scripts.timed_neural_invocation import instrument_evaluation


class NaturalBenchmarkTests(unittest.TestCase):
    def test_pressure_selection_uses_lengths_and_stable_id_ties(self):
        rows=[{'case_id':'d','total_tokens':20},{'case_id':'b','total_tokens':10},
              {'case_id':'a','total_tokens':10},{'case_id':'c','total_tokens':15}]
        self.assertEqual(pressure_ids(rows),['b','d'])
        self.assertEqual(pressure_ids(list(reversed(rows))),['b','d'])
        self.assertEqual(profile([20,10,10,15]),{'count':4,'minimum':10,'maximum':20,'p50':10,'p95':15,'sum':55})
        with self.assertRaises(ValueError): pressure_ids([rows[0]])
        with self.assertRaises(ValueError): pressure_ids([rows[0],rows[0]])

    def test_timing_wrap_preserves_exact_evaluation_and_synchronizes(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'times.jsonl'
            torch=Mock()
            torch.cuda.is_available.return_value=True
            expected={'loss':0.25,'target_tokens':999}
            evaluate=Mock(return_value=expected)
            result=instrument_evaluation(evaluate,torch,path,'unit')('model','data',batch_size=1)
            self.assertIs(result,expected)
            evaluate.assert_called_once_with('model','data',batch_size=1)
            self.assertEqual(torch.cuda.synchronize.call_count,2)
            record=json.loads(path.read_text())
            self.assertEqual(record['target_tokens'],999)
            self.assertEqual(record['status'],'completed')

    def test_failed_evaluation_is_recorded_and_not_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'times.jsonl'
            torch=Mock()
            torch.cuda.is_available.return_value=False
            evaluate=Mock(side_effect=RuntimeError('synthetic unit failure'))
            with self.assertRaisesRegex(RuntimeError,'synthetic unit failure'):
                instrument_evaluation(evaluate,torch,path,'unit')('model')
            self.assertEqual(evaluate.call_count,1)
            self.assertEqual(json.loads(path.read_text())['status'],'failed')

    def test_failed_natural_predecessor_cannot_launch_training(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            followup=root/'followup'
            followup.mkdir()
            (followup/'status.json').write_text(json.dumps({'status':'failed'}))
            helper=root/'helper.py'
            helper.write_text('def process_identity(pid): return None\n')
            wrapper=root/'wrapper.py'
            wrapper.write_text('must not execute')
            args=argparse.Namespace(source=root/'source',out=root/'benchmark',base=root/'base',
                followup=followup,helper=helper,training_wrapper=wrapper,dependency_pid=42,timeout_minutes=1,
                helper_sha256=hashlib.sha256(helper.read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
                wrapper_sha256=hashlib.sha256(wrapper.read_bytes().replace(b'\r\n',b'\n')).hexdigest())
            with patch('scripts.benchmark_after_natural.subprocess.check_output',side_effect=['b4a757afc7c01332734fb6e4c2f08f3f7fcceef9',b'']),patch('scripts.benchmark_after_natural.subprocess.run') as run:
                with self.assertRaisesRegex(ValueError,'Natural intake incomplete'):
                    main(args)
                run.assert_not_called()
            self.assertEqual(json.loads((args.out/'status.json').read_text())['status'],'failed')
