"""Remote read-only M5 admission probe, or exclusive archive of verified scores."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile

ROOT = Path('/root/autodl-tmp/formal-diagnostic-run-20261025')
SOURCE = Path('/root/autodl-tmp/intentlab-history-cpu-source-20261023')
COMMIT = '20214fb28ba1c8a4a2be0be075c97e33eedb2ba0'
LOCK = 'a1b0440b0f93cfcb76ad9971cbfe73e8f08b30e45a6fef091c7cb74cc31fc027'
BINDING = 'd27c35ff115f969cbe7a3b45e0b22f1bdb284d925e58f89819be83301523a003'


def identity(pid):
    try:
        raw = Path('/proc', str(pid), 'stat').read_text()
    except FileNotFoundError:
        return None
    tail = raw[raw.rfind(')') + 2:].split()
    return {'start_ticks': tail[19], 'state': tail[0]}


def sha(path):
    with path.open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def main():
    status = json.loads((ROOT / 'reveal-handoff-status.json').read_text())
    assert status['pid'] == 395747 and status['start_ticks'] == '889287066'
    assert status['protocol_hash'] == LOCK and status['binding_hash'] == BINDING
    parent = identity(status['pid'])
    if parent is not None:
        assert parent['start_ticks'] == status['start_ticks']
    last = status['stages'][-1]
    child = identity(last['child_pid']) if 'child_pid' in last else None
    if child is not None:
        assert child['start_ticks'] == last['child_start_ticks']
    if status['status'] == 'failed':
        raise RuntimeError('M5 failed; investigate without retrying scoring')
    ready = status['status'] == 'completed' and parent is None and child is None
    if '--probe' in sys.argv:
        print(json.dumps({'ready': ready, 'supervisor_status': status['status'],
                          'active_action': status.get('active_action'), 'parent': parent, 'active_child': child}))
        return
    assert '--create' in sys.argv and ready and status['m5_complete'] is True
    assert [s['action'] for s in status['stages']] == ['verify', 'reveal', 'verify-reveal']
    assert all(s['status'] == 'completed' and s['exit_code'] == 0 for s in status['stages'])
    assert subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip() == COMMIT
    assert not subprocess.check_output(['git', '-C', str(SOURCE), 'status', '--porcelain'])
    sys.path.insert(0, str(SOURCE))
    from intentlab.core import digest
    directory = ROOT / 'reveal'
    manifest = json.loads((directory / 'manifest.json').read_text())
    assert manifest['kind'] == 'frozen_diagnostic_reveal' and manifest['status'] == 'completed'
    assert manifest['scope'] == 'formal' and manifest['protocol_hash'] == LOCK and manifest['model_binding_hash'] == BINDING
    assert manifest['receipt_hash'] == status['reveal_receipt_hash'] == digest({k: v for k, v in manifest.items() if k != 'receipt_hash'})
    assert manifest['test_loss_injected'] is False and manifest['gold_opened_after_claim'] is True

    def inventory():
        paths = list(directory.rglob('*'))
        assert not directory.is_symlink() and all(not path.is_symlink() for path in paths)
        return {path.relative_to(directory).as_posix(): {'bytes': path.stat().st_size, 'sha256': sha(path)}
                for path in sorted(paths) if path.is_file()}

    before = inventory()
    assert {name: row['sha256'] for name, row in before.items() if name != 'manifest.json'} == manifest['files_sha256']
    loss_counts = {}
    for condition in ('D-seed-0', 'D-seed-1', 'D-seed-2', 'E-seed-0', 'E-seed-1', 'E-seed-2'):
        with (directory / (condition + '-loss.jsonl')).open('rb') as handle:
            loss_counts[condition] = sum(1 for _ in handle)
    assert set(loss_counts.values()) == {1240}
    archive = ROOT / 'sealed-scoring.tar'
    with tarfile.open(archive, 'x') as handle:
        for name in before:
            handle.add(directory / name, arcname=name, recursive=False)
    assert before == inventory()
    print(json.dumps({'archive_sha256': sha(archive), 'archive_bytes': archive.stat().st_size,
                      'files': before, 'loss_counts': loss_counts, 'diagnostic_receipt_hash': manifest['receipt_hash'],
                      'protocol_hash': LOCK, 'binding_hash': BINDING, 'runtime_commit': COMMIT,
                      'm5_supervisor_completed': True, 'gold_or_references_reopened_for_backup': False}))


if __name__ == '__main__':
    main()
