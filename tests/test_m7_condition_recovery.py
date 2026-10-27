"""Engineering stream fixtures, not resumed formal model evidence."""
from copy import deepcopy
import hashlib
import inspect
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from m7_condition_recovery import build_resume_interact
from intentlab import frozen_execution as frozen


class ConditionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.tasks = [{'id': str(i), 'source_task_id': str(i), 'split': 'validation'} for i in range(2)]
        self.conditions = {str(i): {'policy': 'fixed-full', 'hard_guard': True} for i in range(6)}
        self.prefix = b''.join((json.dumps({'condition': str(i), 'task_id': str(j)}) + '\n').encode()
                               for i in range(3) for j in range(2))
        (self.out / 'interactions.jsonl').write_bytes(self.prefix)
        self.source = inspect.getsource(frozen.interact)
        self.manifest = {'status': 'running', 'model_residency': 'shared-condition-v1',
                         'conditions': self.conditions, 'claim': {'phase': 'original-engineering-claim'},
                         'condition_timings': {str(i): {'seconds_including_loading_and_release': float(i + 1)} for i in range(3)}}
        self.recovery = {'source_sha256': hashlib.sha256(self.source.encode()).hexdigest(), 'manifest': self.manifest,
                         'completed_conditions': ['0', '1', '2'], 'completed_seconds': 6.,
                         'archive_sha256': 'a' * 64, 'prefix_sha256': hashlib.sha256(self.prefix).hexdigest(),
                         'ignored_partial_records': 1}
        self.calls = []
        owner = self
        class Pool:
            instances = 0
            def __init__(self, *args, **kwargs):
                Pool.instances += 1
                self.resident = False
            def close(self):self.resident = False
            def reset(self):self.at_start = self.resident
            def role(self, name):return name
            def snapshot(self):
                value = {'resident_at_task_start': self.at_start}
                self.resident = True
                return value
        class Analyzer:
            def __init__(self, backend):self.errors = []
        def run(task, actor, policy, *args, **kwargs):
            owner.calls.append(task['id'])
            return dict(metrics={}, initial_metrics={}, feasible_at_repair_start=False,
                        repair_introduced_hard_violations=[], task_id=task['id'])
        self.Pool = Pool
        self.namespace = dict(frozen.__dict__, preflight=lambda *args: ({'receipt_hash': 'r'}, self.tasks),
                              runtime_plan=lambda *args: (self.conditions, {}), run_task=run,
                              LanguageModelActor=lambda *args, **kwargs: None, SchemaLanguageModelAnalyzer=Analyzer)
        self.protocol = {'scope': 'engineering', 'lock_hash': 'p', 'spec': {
            'execution': {'settings': {'model_residency': 'shared-condition-v1', 'actor_envelope': 'strict',
                                      'analyzer_mode': 'lm', 'redact_events': False, 'max_tool_steps': 3}},
            'training': {'device': 'cpu'}, 'budgets': {'max_new_tokens': 1, 'token_budget': 10,
                                                     'context_limit': 10, 'max_repairs': 1}}}
        self.binding = {'binding_hash': 'b', 'models': {'actor': {'path': 'base'}, 'analyzer': {'path': 'adapter'}}}

    def invoke(self):
        function, patch = build_resume_interact(self.source, self.namespace, self.recovery)
        return function(self.protocol, self.binding, None, None, self.out, engineering=True, pool_factory=self.Pool), patch

    def test_prefix_byte_preserved_remaining_conditions_run_whole_and_cold(self):
        result, patch = self.invoke()
        raw = (self.out / 'interactions.jsonl').read_bytes()
        self.assertTrue(raw.startswith(self.prefix))
        rows = [json.loads(line) for line in raw.splitlines()]
        self.assertEqual([(r['condition'], r['task_id']) for r in rows],
                         [(str(i), str(j)) for i in range(6) for j in range(2)])
        self.assertEqual(self.calls, ['0', '1'] * 3)
        for index in (6, 8, 10):
            self.assertFalse(rows[index]['model_pool']['resident_at_task_start'])
            self.assertTrue(rows[index + 1]['model_pool']['resident_at_task_start'])
        self.assertEqual(set(result['condition_timings']), set(self.conditions))
        self.assertEqual(result['condition_timings']['0'], self.manifest['condition_timings']['0'])
        self.assertGreaterEqual(result['seconds_including_loading'], sum(
            row['seconds_including_loading_and_release'] for row in result['condition_timings'].values()))
        self.assertEqual(result['status'], 'sealed')
        self.assertEqual(result['recovery']['partial_condition_records_preserved_separately'], 1)
        self.assertEqual(patch['enumerated_replacements'], 6)

    def test_changed_prefix_fails_before_model_or_output_modification(self):
        (self.out / 'interactions.jsonl').write_bytes(self.prefix + b'changed')
        with self.assertRaises(ValueError):self.invoke()
        self.assertEqual(self.Pool.instances, 0)
        self.assertFalse((self.out / 'manifest.json').exists())

    def test_nonprefix_or_incomplete_condition_selection_and_source_drift_rejected(self):
        for completed in ([], ['1'], ['0', '2'], list(self.conditions)):
            changed = deepcopy(self.recovery)
            changed['completed_conditions'] = completed
            with self.assertRaises(ValueError):build_resume_interact(self.source, self.namespace, changed)
        with self.assertRaises(ValueError):build_resume_interact(self.source + '\n', self.namespace, self.recovery)
        changed_source = self.source.replace('Choose a fresh frozen execution directory', 'unexpected source')
        changed = deepcopy(self.recovery)
        changed['source_sha256'] = hashlib.sha256(changed_source.encode()).hexdigest()
        with self.assertRaises(ValueError):build_resume_interact(changed_source, self.namespace, changed)


if __name__ == '__main__':
    unittest.main()
