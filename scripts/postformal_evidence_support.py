"""Assess sealed M5 citations only after a hash-bound completed M7 archive.

Expected archive hashes must come from previously observed off-host receipts,
not values calculated ad hoc to bless unknown input. No archive is extracted.
This supplementary entry neither runs models nor changes frozen experiments.
"""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from intentlab.core import digest
from score_evidence_support import score_evidence_support

CONDITIONS = ['A', 'B', 'C'] + [f'{kind}-seed-{seed}' for kind in ('D', 'E') for seed in range(3)]
ABLATIONS = {'fixed-k-1', 'fixed-k-2', 'fixed-k-3', 'dynamic-k',
             'dynamic-k-remove_hard_weight', 'dynamic-k-remove_unknown_weight'}


class BoundArchive:
    def __init__(self, path, expected):
        if not isinstance(expected, str) or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected):
            raise ValueError('Trusted SHA256 required')
        self.path, self.expected = Path(path), expected
        self.stream = self.path.open('rb')
        try:
            self.verify_outer()
            self.tar = tarfile.open(fileobj=self.stream, mode='r:*')
            self.members = {}
            for member in self.tar.getmembers():
                name = PurePosixPath(member.name)
                if not member.isfile() or member.name in self.members or name.is_absolute() \
                        or '..' in name.parts or str(name) != member.name or '\\' in member.name or ':' in member.name:
                    raise ValueError('Duplicate, unsafe or nonregular archive member')
                self.members[member.name] = member
        except BaseException:
            if hasattr(self, 'tar'):
                self.tar.close()
            self.stream.close()
            raise

    def verify_outer(self):
        self.stream.seek(0)
        if hashlib.file_digest(self.stream, 'sha256').hexdigest() != self.expected:
            raise ValueError('Archive differs from trusted SHA256')
        self.stream.seek(0)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.tar.close()
        self.stream.close()

    def raw(self, name):
        if name not in self.members:
            raise ValueError('Missing archive member')
        with self.tar.extractfile(self.members[name]) as stream:
            return stream.read()

    def json(self, name):
        return json.loads(self.raw(name))

    def rows(self, name):
        return [json.loads(line) for line in self.raw(name).splitlines() if line.strip()]

    def member_hash(self, name):
        with self.tar.extractfile(self.members[name]) as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()

    def sealed(self, prefix, kind, status, seal, protocol, binding):
        manifest_name = prefix + 'manifest.json'
        manifest = self.json(manifest_name)
        if manifest['kind'] != kind or manifest['scope'] != 'formal' or manifest['status'] != status \
                or manifest['protocol_hash'] != protocol or manifest['model_binding_hash'] != binding \
                or manifest[seal] != digest({k: v for k, v in manifest.items() if k != seal}):
            raise ValueError('Incomplete or mismatched sealed manifest')
        actual = {name[len(prefix):]: self.member_hash(name) for name in self.members
                  if name.startswith(prefix) and name != manifest_name}
        if actual != manifest['files_sha256']:
            raise ValueError('Sealed member bytes or population differ')
        return manifest


def completed_m7(archive, protocol, binding):
    """Must run before any scientific cases, gold or predictions are decoded."""
    status = archive.json('supervisor-status.json')
    if status['kind'] != 'frozen_m7_ablation_supervisor' or status['status'] != 'completed' \
            or status['m7_complete'] is not True or status['protocol_hash'] != protocol \
            or status['binding_hash'] != binding \
            or [s['action'] for s in status['stages']] != ['interact', 'verify', 'reveal', 'verify-reveal'] \
            or any(s['status'] != 'completed' or type(s['exit_code']) is not int or s['exit_code'] != 0
                   for s in status['stages']):
        raise ValueError('All original M7 stages must have completed successfully')
    interaction = archive.sealed('interactions/', 'frozen_ablation_interactions', 'sealed', 'seal_hash', protocol, binding)
    reveal = archive.sealed('reveal/', 'frozen_ablation_reveal', 'completed', 'receipt_hash', protocol, binding)
    if interaction['injected_pool'] is not False or interaction['offline_references_opened'] is not False \
            or reveal['references_accessed_after_claim'] is not True \
            or reveal['interaction_seal_hash'] != interaction['seal_hash'] \
            or reveal['receipt_hash'] != status['ablation_receipt_hash'] \
            or reveal['upstream'] != interaction['upstream'] \
            or reveal['upstream']['execution_receipt_hash'] != status['execution_receipt_hash']:
        raise ValueError('M7 isolation or receipt chain mismatch')
    if set(interaction['conditions']) != ABLATIONS:
        raise ValueError('All six registered M7 conditions required')
    for name in ('interactions/interactions.jsonl', 'reveal/runs.jsonl'):
        raw = archive.raw(name)
        if len(raw.splitlines()) != 1800 or not raw.endswith(b'\n') or any(not line.strip() for line in raw.splitlines()):
            raise ValueError('Exactly 1800 retained M7 records required')
    return interaction, reveal


def assess(archives, expected_protocol, expected_binding, out):
    """archives maps m7/scientific/predictions/scoring to (path, trusted SHA256)."""
    if set(archives) != {'m7', 'scientific', 'predictions', 'scoring'}:
        raise ValueError('All four independently bound archives are required')
    out = Path(out)
    if out.exists():
        raise ValueError('Refusing to overwrite prior supplementary assessment')
    with ExitStack() as stack:
        # The M7 gate deliberately precedes opening all data/prediction archives.
        m7 = stack.enter_context(BoundArchive(*archives['m7']))
        interaction, reveal = completed_m7(m7, expected_protocol, expected_binding)
        scientific = stack.enter_context(BoundArchive(*archives['scientific']))
        predictions = stack.enter_context(BoundArchive(*archives['predictions']))
        scoring = stack.enter_context(BoundArchive(*archives['scoring']))
        lock_name = 'protocol/formal-protocol.lock.json'
        lock = scientific.json(lock_name)
        if lock['lock_hash'] != expected_protocol or lock['scope'] != 'formal' \
                or digest({k: v for k, v in lock.items() if k != 'lock_hash'}) != expected_protocol:
            raise ValueError('Scientific protocol identity mismatch')
        expected_data = {lock_name: scientific.member_hash(lock_name)}
        for key in ('cases', 'tasks', 'references'):
            expected_data['dataset/' + key + '.jsonl'] = lock['annotation_inputs'][key]['sha256']
        for name, value in lock['dataset_export']['files_sha256'].items():
            expected_data['dataset/export/' + name] = value
        for key in ('tasks', 'references'):
            expected_data['dataset/execution-' + key + '.jsonl'] = lock['execution_binding']['files'][key]['sha256']
        if set(scientific.members) != set(expected_data) or any(
                scientific.member_hash(name) != value for name, value in expected_data.items()):
            raise ValueError('Scientific archive differs from frozen protocol')
        pred = predictions.sealed('', 'frozen_diagnostic_predictions', 'sealed', 'seal_hash', expected_protocol, expected_binding)
        score = scoring.sealed('', 'frozen_diagnostic_reveal', 'completed', 'receipt_hash', expected_protocol, expected_binding)
        if pred['conditions'] != CONDITIONS or pred['gold_loaded'] is not False or pred['test_backend_injected'] is not False \
                or score['prediction_seal_hash'] != pred['seal_hash'] or score['test_loss_injected'] is not False \
                or score['gold_opened_after_claim'] is not True or interaction['diagnostic_receipt_hash'] != score['receipt_hash']:
            raise ValueError('M5/M7 diagnostic binding or model isolation mismatch')
        cases, gold = [], {}
        for split in ('test', 'ood'):
            subset = scientific.rows(f'dataset/export/heldout/{split}/cases.jsonl')
            if not subset or any(row['split'] != split for row in subset):
                raise ValueError('Both exact heldout splits required')
            cases.extend(subset)
            for row in scientific.rows(f'dataset/export/heldout/{split}/gold.jsonl'):
                if set(row) != {'case_id', 'findings'} or row['case_id'] in gold:
                    raise ValueError('Duplicate or malformed heldout gold')
                gold[row['case_id']] = row['findings']
        if digest(cases) != pred['cases_hash']:
            raise ValueError('Prediction case population/order differs from frozen cases')
        sources = {row['source_task_id'] for row in cases}
        tasks = [row for row in scientific.rows('dataset/tasks.jsonl') if row['source_task_id'] in sources]
        task_ids = {row['id'] for row in tasks}
        refs = [row for row in scientific.rows('dataset/references.jsonl') if row['task_id'] in task_ids]
        population = {row['case_id'] for row in cases}
        results = {}
        for condition in CONDITIONS:
            if predictions.json(condition + '/manifest.json')['status'] != 'completed':
                raise ValueError('Incomplete diagnostic condition')
            rows = predictions.rows(condition + '/predictions.jsonl')
            if len(rows) != len(cases) or {row['case_id'] for row in rows} != population:
                raise ValueError('Every condition must retain every case, including failures')
            results[condition] = score_evidence_support(cases, tasks, refs, gold, rows)
        # Recheck actual archive bytes; no output is accepted after a change.
        for archive in (m7, scientific, predictions, scoring):
            archive.verify_outer()
        out.mkdir(parents=True, exist_ok=False)
        files = {}
        for condition, result in results.items():
            path = out / (condition + '.json')
            path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False) + '\n', encoding='utf-8')
            files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        receipt = {'kind': 'postformal_supplementary_evidence_support', 'status': 'completed',
                   'supplementary_exploratory': True, 'protocol_hash': expected_protocol,
                   'model_binding_hash': expected_binding, 'ablation_receipt_hash': reveal['receipt_hash'],
                   'diagnostic_receipt_hash': score['receipt_hash'], 'prediction_seal_hash': pred['seal_hash'],
                   'input_archives_sha256': {k: v[1] for k, v in archives.items()}, 'conditions': CONDITIONS,
                   'files_sha256': files, 'frozen_scores_modified': False, 'model_called': False,
                   'evaluator_files_sha256': {name: hashlib.sha256(
                       (Path(__file__).resolve().parents[1] / name).read_bytes()).hexdigest()
                       for name in ('scripts/postformal_evidence_support.py', 'scripts/score_evidence_support.py',
                                    'scripts/evidence_support.py', 'intentlab/core.py', 'intentlab/contracts.py',
                                    'intentlab/formal_data.py', 'intentlab/formal_eval.py', 'intentlab/execution_data.py')},
                   'm8_complete': False}
        receipt['receipt_hash'] = digest(receipt)
        (out / 'manifest.json').write_text(json.dumps(receipt, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('m7', 'scientific', 'predictions', 'scoring'):
        parser.add_argument('--' + name + '-archive', type=Path, required=True)
        parser.add_argument('--' + name + '-sha256', required=True)
    parser.add_argument('--protocol-hash', required=True)
    parser.add_argument('--binding-hash', required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    archives = {k: (getattr(args, k + '_archive'), getattr(args, k + '_sha256'))
                for k in ('m7', 'scientific', 'predictions', 'scoring')}
    receipt = assess(archives, args.protocol_hash, args.binding_hash, args.out)
    print(json.dumps({'status': receipt['status'], 'receipt_hash': receipt['receipt_hash'], 'm8_complete': False}))


if __name__ == '__main__':
    main()
