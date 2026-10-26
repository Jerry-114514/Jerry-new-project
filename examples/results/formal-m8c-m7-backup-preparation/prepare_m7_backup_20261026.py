"""Probe the original M7 handles or exclusively archive completed M7 outputs."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path('/root/autodl-tmp/formal-ablation-run-20261025')
SOURCE = Path('/root/autodl-tmp/intentlab-history-cpu-source-20261023')
COMMIT = '20214fb28ba1c8a4a2be0be075c97e33eedb2ba0'
LOCK = 'a1b0440b0f93cfcb76ad9971cbfe73e8f08b30e45a6fef091c7cb74cc31fc027'
BINDING = 'd27c35ff115f969cbe7a3b45e0b22f1bdb284d925e58f89819be83301523a003'


def identity(pid):
    try:
        raw = Path('/proc', str(pid), 'stat').read_text()
    except FileNotFoundError:
        return None
    fields = raw[raw.rfind(')') + 2:].split()
    return {'start_ticks': fields[19], 'state': fields[0]}


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def count(path):
    with path.open('rb') as stream:
        return sum(block.count(b'\n') for block in iter(lambda: stream.read(1024 * 1024), b''))


def main():
    if not __debug__:
        raise RuntimeError('Assertion checks must remain enabled')
    status = json.loads((ROOT / 'supervisor-status.json').read_text())
    claim = json.loads((ROOT / 'supervisor.claim.json').read_text())
    assert status['kind'] == 'frozen_m7_ablation_supervisor'
    assert status['driver_sha256'] == 'd97fff09401b8579c52b25f68883b1e37adf4b57174cfe8a877650b26cdd06b7'
    assert all(status[k] == claim[k] for k in ('pid', 'start_ticks', 'driver_sha256', 'started_unix'))
    assert status['runtime_commit'] == COMMIT and status['protocol_hash'] == LOCK and status['binding_hash'] == BINDING
    parent = identity(status['pid'])
    if parent is not None:
        assert parent['start_ticks'] == status['start_ticks']
    children = []
    for stage in status['stages']:
        if 'child_pid' not in stage:
            continue
        child = identity(stage['child_pid'])
        if child is not None:
            assert child['start_ticks'] == stage['child_start_ticks']
            children.append(child)
    if status['status'] == 'failed':
        raise RuntimeError('Original M7 failed; investigate without retrying')
    ready = status['status'] == 'completed' and parent is None and not children
    if sys.argv[1:] == ['--probe']:
        print(json.dumps({'ready': ready, 'supervisor_status': status['status'],
                          'active_action': status.get('active_action'), 'parent': parent, 'active_children': children}))
        return
    assert sys.argv[1:] == ['--create'] and ready and status['m7_complete'] is True
    assert [s['action'] for s in status['stages']] == ['interact', 'verify', 'reveal', 'verify-reveal']
    assert all(s['status'] == 'completed' and s['exit_code'] == 0 for s in status['stages'])
    assert subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip() == COMMIT
    assert not subprocess.check_output(['git', '-C', str(SOURCE), 'status', '--porcelain'])
    sys.path.insert(0, str(SOURCE))
    from intentlab.core import digest
    manifests = {}
    for name, kind, state, seal in [('interactions', 'frozen_ablation_interactions', 'sealed', 'seal_hash'),
                                    ('reveal', 'frozen_ablation_reveal', 'completed', 'receipt_hash')]:
        manifest = json.loads((ROOT / name / 'manifest.json').read_text())
        assert manifest['kind'] == kind and manifest['status'] == state and manifest['scope'] == 'formal'
        assert manifest['protocol_hash'] == LOCK and manifest['model_binding_hash'] == BINDING
        assert manifest[seal] == digest({k: v for k, v in manifest.items() if k != seal})
        manifests[name] = manifest
    assert manifests['reveal']['receipt_hash'] == status['ablation_receipt_hash']
    assert manifests['reveal']['upstream']['execution_receipt_hash'] == status['execution_receipt_hash']
    assert manifests['interactions']['upstream'] == manifests['reveal']['upstream']
    assert manifests['reveal']['interaction_seal_hash'] == manifests['interactions']['seal_hash']
    assert manifests['interactions']['offline_references_opened'] is False
    assert manifests['interactions']['injected_pool'] is False
    counts = {'interaction_records': count(ROOT / 'interactions/interactions.jsonl'),
              'scored_records': count(ROOT / 'reveal/runs.jsonl')}
    assert counts['interaction_records'] == counts['scored_records'] == 1800
    archive = ROOT / 'sealed-ablation.tar'
    assert not archive.exists(), 'Existing archive must be inspected, never overwritten'

    def inventory():
        paths = list(ROOT.rglob('*'))
        assert not ROOT.is_symlink() and all(not p.is_symlink() for p in paths)
        return {p.relative_to(ROOT).as_posix(): {'bytes': p.stat().st_size, 'sha256': sha(p)}
                for p in sorted(paths) if p.is_file() and p != archive}

    before = inventory()
    for name, manifest in manifests.items():
        prefix = name + '/'
        assert {k[len(prefix):]: v['sha256'] for k, v in before.items()
                if k.startswith(prefix) and k != prefix + 'manifest.json'} == manifest['files_sha256']
    with tarfile.open(archive, 'x') as handle:
        for name in before:
            handle.add(ROOT / name, arcname=name, recursive=False)
    assert before == inventory(), 'Completed outputs changed during archival'
    print(json.dumps({'archive_sha256': sha(archive), 'archive_bytes': archive.stat().st_size, 'files': before,
                      'protocol_hash': LOCK, 'binding_hash': BINDING, 'runtime_commit': COMMIT,
                      'ablation_receipt_hash': manifests['reveal']['receipt_hash'],
                      'interaction_seal_hash': manifests['interactions']['seal_hash'],
                      'm7_supervisor_completed': True, 'references_reopened_for_backup': False, **counts}))


if __name__ == '__main__':
    main()
