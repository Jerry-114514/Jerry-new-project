"""Synthetic archives only. Completion fixtures are not real experiment receipts."""
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from build_execution_development import development_tasks
import postformal_evidence_support as entry
from test_evidence_support import case_for
from intentlab.core import canonical, digest, initial_state
from intentlab.formal_data import evidence_catalog
from intentlab.programmatic_labels import generate_labels


def encoded(value):
    return (canonical(value) + '\n').encode()


def jsonl(rows):
    return b''.join(encoded(row) for row in rows)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class PostformalEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        all_tasks, all_refs = development_tasks()
        self.tasks = deepcopy(all_tasks[:2])
        self.refs = [deepcopy(next(r for r in all_refs if r['task_id'] == t['id'])) for t in self.tasks]
        self.cases = []
        for split, task, reference in zip(('test', 'ood'), self.tasks, self.refs):
            task['split'] = split
            state = initial_state(task)
            state.apply([{'op': 'validate', 'ok': True}] + [
                {'op': 'write', 'path': p, 'value': deepcopy(v)} for p, v in reference['files'].items()])
            self.cases += [case_for(task, state, visible, str(visible)) for visible in (True, False)]
        labels = generate_labels(self.cases, self.tasks, {r['task_id']: r for r in self.refs})
        exports = {'train.jsonl': b'', 'validation.jsonl': b'', 'manifest.json': b'{}\n',
                   'programmatic-labels.jsonl': jsonl(labels)}
        for split in ('test', 'ood'):
            cases = [c for c in self.cases if c['split'] == split]
            exports[f'heldout/{split}/cases.jsonl'] = jsonl(cases)
            exports[f'heldout/{split}/gold.jsonl'] = jsonl([
                {'case_id': row['case_id'], 'findings': row['findings']}
                for row in labels if row['case_id'] in {c['case_id'] for c in cases}])
        data = {'dataset/cases.jsonl': jsonl(self.cases), 'dataset/tasks.jsonl': jsonl(self.tasks),
                'dataset/references.jsonl': jsonl(self.refs),
                'dataset/execution-tasks.jsonl': jsonl(self.tasks),
                'dataset/execution-references.jsonl': jsonl(self.refs)}
        lock = {'scope': 'formal', 'annotation_inputs': {
            key: {'sha256': sha(data['dataset/' + key + '.jsonl'])} for key in ('cases', 'tasks', 'references')},
            'dataset_export': {'files_sha256': {name: sha(raw) for name, raw in exports.items()}},
            'execution_binding': {'files': {key: {'sha256': sha(data['dataset/execution-' + key + '.jsonl'])}
                                            for key in ('tasks', 'references')}}}
        lock['lock_hash'] = digest(lock)
        self.protocol, self.binding = lock['lock_hash'], 'b' * 64
        data.update({'dataset/export/' + name: raw for name, raw in exports.items()})
        data['protocol/formal-protocol.lock.json'] = encoded(lock)
        predictions = {}
        for condition in entry.CONDITIONS:
            predictions[condition + '/manifest.json'] = encoded({'status': 'completed'})
            predictions[condition + '/predictions.jsonl'] = jsonl([
                {'case_id': case['case_id'], 'text': canonical({'findings': [
                    {'id': req['id'], 'status': 'satisfied', 'evidence': sorted(evidence_catalog(case['public']))}
                    for req in case['public']['requirements']]})} for case in self.cases])
        pred = self.seal(predictions, '', 'frozen_diagnostic_predictions', 'sealed', 'seal_hash',
                         conditions=entry.CONDITIONS, gold_loaded=False, test_backend_injected=False,
                         cases_hash=digest(self.cases))
        scoring = {'scores.json': b'{}\n'}
        score = self.seal(scoring, '', 'frozen_diagnostic_reveal', 'completed', 'receipt_hash',
                          prediction_seal_hash=pred['seal_hash'], gold_opened_after_claim=True, test_loss_injected=False)
        m7 = {'interactions/interactions.jsonl': b'{}\n' * 1800, 'reveal/runs.jsonl': b'{}\n' * 1800}
        upstream = {'execution_receipt_hash': 'e' * 64}
        interaction = self.seal(m7, 'interactions/', 'frozen_ablation_interactions', 'sealed', 'seal_hash',
                                upstream=upstream, injected_pool=False, offline_references_opened=False,
                                conditions={name: {} for name in entry.ABLATIONS},
                                diagnostic_receipt_hash=score['receipt_hash'])
        reveal = self.seal(m7, 'reveal/', 'frozen_ablation_reveal', 'completed', 'receipt_hash',
                           upstream=upstream, references_accessed_after_claim=True,
                           interaction_seal_hash=interaction['seal_hash'])
        m7['supervisor-status.json'] = encoded({'kind': 'frozen_m7_ablation_supervisor', 'status': 'completed',
            'm7_complete': True, 'protocol_hash': self.protocol, 'binding_hash': self.binding,
            'ablation_receipt_hash': reveal['receipt_hash'], 'execution_receipt_hash': upstream['execution_receipt_hash'],
            'stages': [{'action': action, 'status': 'completed', 'exit_code': 0}
                       for action in ('interact', 'verify', 'reveal', 'verify-reveal')]})
        self.payloads = {'m7': m7, 'scientific': data, 'predictions': predictions, 'scoring': scoring}
        self.archives = {name: self.write(name, files) for name, files in self.payloads.items()}

    def seal(self, files, prefix, kind, status, seal, **extra):
        manifest = {'kind': kind, 'status': status, 'scope': 'formal', 'protocol_hash': self.protocol,
                    'model_binding_hash': self.binding, 'files_sha256': {
                        name[len(prefix):]: sha(raw) for name, raw in files.items() if name.startswith(prefix)}, **extra}
        manifest[seal] = digest(manifest)
        files[prefix + 'manifest.json'] = encoded(manifest)
        return manifest

    def write(self, name, files):
        path = self.root / (name + '.tar')
        with tarfile.open(path, 'w') as handle:
            for member, raw in files.items():
                info = tarfile.TarInfo(member)
                info.size = len(raw)
                handle.addfile(info, io.BytesIO(raw))
        return path, sha(path.read_bytes())

    def run_assessment(self, name='out'):
        return entry.assess(self.archives, self.protocol, self.binding, self.root / name)

    def test_full_roundtrip_and_fresh_replay_are_identical(self):
        first, second = self.run_assessment(), self.run_assessment('replay')
        self.assertEqual(first, second)
        self.assertEqual(len(first['files_sha256']), 9)
        for name, checksum in first['files_sha256'].items():
            self.assertEqual(sha((self.root / 'out' / name).read_bytes()), checksum)
            self.assertEqual((self.root / 'out' / name).read_bytes(), (self.root / 'replay' / name).read_bytes())
        self.assertFalse(first['model_called'])
        self.assertFalse(first['m8_complete'])
        with self.assertRaises(ValueError):
            self.run_assessment()

    def test_incomplete_gate_never_opens_other_archives(self):
        files = self.payloads['m7']
        status = json.loads(files['supervisor-status.json'])
        status['status'] = 'running'
        files['supervisor-status.json'] = encoded(status)
        self.archives['m7'] = self.write('incomplete', files)
        original = entry.BoundArchive
        opened = []
        def tracked(path, checksum):
            opened.append(path)
            return original(path, checksum)
        with patch.object(entry, 'BoundArchive', side_effect=tracked):
            with self.assertRaises(ValueError):
                self.run_assessment()
        self.assertEqual(opened, [self.archives['m7'][0]])
        self.assertFalse((self.root / 'out').exists())

    def test_changed_bytes_fail_external_or_internal_binding(self):
        path, expected = self.archives['scientific']
        self.archives['scientific'] = (path, '0' * 64)
        with self.assertRaises(ValueError):
            self.run_assessment()
        self.payloads['scientific']['dataset/tasks.jsonl'] += b'\n'
        self.archives['scientific'] = self.write('changed-data', self.payloads['scientific'])
        with self.assertRaises(ValueError):
            self.run_assessment()
        self.assertFalse((self.root / 'out').exists())

    def test_unsafe_or_duplicate_members_fail(self):
        path, checksum = self.write('unsafe', {'../escape': b'x'})
        with self.assertRaises(ValueError):
            entry.BoundArchive(path, checksum)
        path = self.root / 'duplicate.tar'
        with tarfile.open(path, 'w') as handle:
            for _ in range(2):
                info = tarfile.TarInfo('same')
                info.size = 1
                handle.addfile(info, io.BytesIO(b'x'))
        with self.assertRaises(ValueError):
            entry.BoundArchive(path, sha(path.read_bytes()))

    def test_nonzero_or_boolean_stage_exit_is_rejected(self):
        for exit_code in (1, False):
            files = deepcopy(self.payloads['m7'])
            status = json.loads(files['supervisor-status.json'])
            status['stages'][2]['exit_code'] = exit_code
            files['supervisor-status.json'] = encoded(status)
            self.archives['m7'] = self.write('bad-stage', files)
            with self.assertRaises(ValueError):
                self.run_assessment()

    def test_missing_ablation_or_truncated_records_fail_even_when_resealed(self):
        for mutation in ('missing-condition', 'short-records'):
            files = deepcopy(self.payloads['m7'])
            interaction = json.loads(files['interactions/manifest.json'])
            if mutation == 'missing-condition':
                interaction['conditions'].pop('fixed-k-3')
            else:
                files['interactions/interactions.jsonl'] = b'{}\n' * 1799
                interaction['files_sha256']['interactions.jsonl'] = sha(files['interactions/interactions.jsonl'])
            interaction.pop('seal_hash')
            interaction['seal_hash'] = digest(interaction)
            files['interactions/manifest.json'] = encoded(interaction)
            reveal = json.loads(files['reveal/manifest.json'])
            reveal['interaction_seal_hash'] = interaction['seal_hash']
            reveal.pop('receipt_hash')
            reveal['receipt_hash'] = digest(reveal)
            files['reveal/manifest.json'] = encoded(reveal)
            status = json.loads(files['supervisor-status.json'])
            status['ablation_receipt_hash'] = reveal['receipt_hash']
            files['supervisor-status.json'] = encoded(status)
            self.archives['m7'] = self.write(mutation, files)
            with self.assertRaises(ValueError):
                self.run_assessment()
            self.assertFalse((self.root / 'out').exists())

    def test_gzip_scientific_archive_is_supported(self):
        path = self.root / 'scientific.tar.gz'
        with tarfile.open(path, 'w:gz') as handle:
            for name, raw in self.payloads['scientific'].items():
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                handle.addfile(info, io.BytesIO(raw))
        self.archives['scientific'] = (path, sha(path.read_bytes()))
        self.assertEqual(self.run_assessment()['status'], 'completed')


if __name__ == '__main__':
    unittest.main()
