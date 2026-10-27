"""Admission checks use byte fixtures, never pretend to load a real model."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verify_restored_inference import JOBS, assets, completed_statistics, digest, sha, replace_active_adapter


class RestoredInferenceAdmissionTests(unittest.TestCase):
    def test_replacement_keeps_active_configuration_valid_during_every_load(self):
        class AdapterLifecycle:
            def __init__(self):
                self.active = JOBS[0]
                self.configs = {self.active: object()}

            def load_adapter(self, path, *, adapter_name, is_trainable, local_files_only):
                # Mirrors the PEFT lookup that failed in the real probe.
                self.configs[self.active]
                self.configs[adapter_name] = object()

            def set_adapter(self, name, *, inference_mode):
                self.configs[name]
                self.active = name

            def delete_adapter(self, name):
                del self.configs[name]

        model = AdapterLifecycle()
        for previous, job in zip(JOBS, JOBS[1:]):
            replace_active_adapter(model, Path(job), job, previous)
            self.assertEqual(model.active, job)
            self.assertEqual(set(model.configs), {job})

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def statistics(self):
        path = self.root / 'statistics.json'
        value = {'kind': 'frozen_statistics_reproduction_supervisor', 'status': 'completed',
                 'statistics_reproduction_complete': True, 'canonical_reports_identical': True, 'pid': 10,
                 'stages': [{'action': action, 'status': 'completed', 'exit_code': 0, 'child_pid': i}
                            for i, action in enumerate(('analysis', 'verify', 'replay', 'verify-replay'), 20)]}
        path.write_text(json.dumps(value))
        return path, value

    def fixture(self):
        root = self.root / 'payload'
        root.mkdir()
        files = []
        values = {'base/config.json': {'fixture': True}}
        for job in JOBS:
            for name in ('adapter_config.json', 'adapter_model.safetensors', 'tokenizer.json', 'tokenizer_config.json'):
                values[f'endpoints/{job}/model/{name}'] = {'peft_type': 'LORA', 'bias': 'none'} if name == 'adapter_config.json' else {'byte_fixture': True}
        for name, value in values.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(value))
            files.append({'path': name, 'bytes': path.stat().st_size, 'sha256': sha(path)})
        plan = {'remote_root': str(root), 'files': files, 'file_count': len(files),
                'total_bytes': sum(r['bytes'] for r in files)}
        (root / 'transfer-plan.json').write_text(json.dumps(plan))
        (root / 'restore-receipt.json').write_text('{}')
        return root, plan

    def test_statistics_must_be_hash_bound_complete_and_all_processes_gone(self):
        path, value = self.statistics()
        self.assertEqual(completed_statistics(path, sha(path), lambda _: {'proc_visible': False}), value)
        with self.assertRaises(ValueError):
            completed_statistics(path, '0' * 64, lambda _: {})
        with self.assertRaises(ValueError):
            completed_statistics(path, sha(path), lambda pid: {'proc_visible': pid == 22})
        for change in ('status', 'canonical_reports_identical', 'exit_code'):
            path, value = self.statistics()
            if change == 'exit_code':
                value['stages'][0]['exit_code'] = False
            else:
                value[change] = 'running' if change == 'status' else False
            path.write_text(json.dumps(value))
            with self.assertRaises(ValueError):
                completed_statistics(path, sha(path), lambda _: {})

    def test_all_six_exports_and_every_file_are_bound_before_any_model_load(self):
        root, plan = self.fixture()
        self.assertEqual(assets(root, digest(plan)), plan)
        with self.assertRaises(ValueError):
            assets(root, '0' * 64)
        first = root / plan['files'][0]['path']
        first.write_text('{changed}')
        with self.assertRaises(ValueError):
            assets(root, digest(plan))

    def test_unexpected_payload_and_rebound_missing_export_are_rejected(self):
        root, plan = self.fixture()
        extra = root / 'extra.txt'
        extra.write_text('unexpected')
        with self.assertRaises(ValueError):
            assets(root, digest(plan))
        extra.unlink()
        removed = plan['files'].pop()
        (root / removed['path']).unlink()
        plan['file_count'] -= 1
        plan['total_bytes'] -= removed['bytes']
        (root / 'transfer-plan.json').write_text(json.dumps(plan))
        with self.assertRaises(ValueError):
            assets(root, digest(plan))

    def test_rebound_traversal_plan_is_rejected(self):
        root, plan = self.fixture()
        plan['files'][0]['path'] = '../outside'
        (root / 'transfer-plan.json').write_text(json.dumps(plan))
        with self.assertRaises(ValueError):
            assets(root, digest(plan))


if __name__ == '__main__':
    unittest.main()
