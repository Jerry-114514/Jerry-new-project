"""Local backup gate before the already frozen, one-shot M5 scoring commands."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import sys
import tarfile
import time

WORKSPACE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WORKSPACE))
from intentlab.core import digest
from m5_observer_transport_20261025 import run_remote

BACKUP = WORKSPACE / 'runs/formal-diagnostic-backup-20261026-recovery2'
LOCAL = WORKSPACE / 'runs/formal-reveal-handoff-20261026'
REMOTE = '/root/autodl-tmp/formal-diagnostic-run-20261025'
PYTHON = '/root/autodl-tmp/intentlab-venv/bin/python'
DRIVER = '/root/autodl-tmp/run_formal_reveal_handoff_20261026.py'
LOCK = 'a1b0440b0f93cfcb76ad9971cbfe73e8f08b30e45a6fef091c7cb74cc31fc027'
BINDING = 'd27c35ff115f969cbe7a3b45e0b22f1bdb284d925e58f89819be83301523a003'
CONDITIONS = ['A', 'B', 'C'] + [f'{name}-seed-{seed}' for name in ('D', 'E') for seed in (0, 1, 2)]


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def backup_gate(root):
    status = read(root / 'watcher-status.json')
    if status['status'] in {'watching', 'backing_up', 'observation_unavailable'}:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(status['observed_utc'])).total_seconds()
        if age > 180:
            raise RuntimeError('Backup observer is stale; no scoring launch')
        return None
    if status['status'] != 'completed':
        raise RuntimeError('Backup did not complete; no scoring launch')
    expected = read(root / 'source-inventory.json')
    archive = root / 'sealed-predictions.tar'
    backup = status['backup']
    for key in ('archive_sha256', 'archive_bytes', 'prediction_seal_hash'):
        assert backup[key] == expected[key]
    assert archive.stat().st_size == expected['archive_bytes'] and sha(archive) == expected['archive_sha256']
    with tarfile.open(archive, 'r:') as handle:
        members = handle.getmembers()
        assert len(members) == len({m.name for m in members}) == len(expected['files']) == backup['verified_members']
        assert {m.name for m in members} == set(expected['files'])
        for member in members:
            path = PurePosixPath(member.name)
            assert member.isfile() and not path.is_absolute() and '..' not in path.parts
            assert str(path) == member.name and '\\' not in member.name and ':' not in member.name
            record = expected['files'][member.name]
            assert member.size == record['bytes']
            with handle.extractfile(member) as stream:
                assert hashlib.file_digest(stream, 'sha256').hexdigest() == record['sha256']
        manifest = json.load(handle.extractfile('manifest.json'))
    assert manifest['kind'] == 'frozen_diagnostic_predictions' and manifest['status'] == 'sealed'
    assert manifest['scope'] == 'formal' and manifest['gold_loaded'] is False
    assert manifest['protocol_hash'] == LOCK and manifest['model_binding_hash'] == BINDING
    assert manifest['conditions'] == CONDITIONS and manifest['test_backend_injected'] is False
    assert manifest['seal_hash'] == expected['prediction_seal_hash'] == digest({k: v for k, v in manifest.items() if k != 'seal_hash'})
    assert manifest['files_sha256'] == {name: row['sha256'] for name, row in expected['files'].items() if name != 'manifest.json'}
    assert all(f'{condition}/predictions.jsonl' in expected['files'] and f'{condition}/manifest.json' in expected['files'] for condition in CONDITIONS)
    return {'kind': 'observed_off_host_prediction_backup_gate', 'scope': 'formal',
            'protocol_hash': LOCK, 'binding_hash': BINDING, 'prediction_seal_hash': manifest['seal_hash'],
            'archive_sha256': expected['archive_sha256'], 'archive_bytes': expected['archive_bytes'],
            'verified_members': len(expected['files']), 'all_archive_members_reverified': True,
            'gold_read': False, 'raw_predictions_parsed': False, 'created_utc': datetime.now(timezone.utc).isoformat()}


def remote_code(script):
    return json.loads(run_remote(WORKSPACE, PYTHON + ' -c ' + shlex.quote(script), timeout=180))


def launch(attestation):
    driver_sha = sha(WORKSPACE / 'tmp/run_formal_reveal_handoff_20261026.py')
    code = '''import hashlib,json,subprocess,time
from pathlib import Path
driver=Path(DRIVER)
assert hashlib.sha256(driver.read_bytes()).hexdigest()==DRIVER_SHA
root=Path(ROOT)
with (root/'off-host-reveal-attestation-20261026.json').open('x') as handle:json.dump(ATTESTATION,handle)
with (root/'reveal-handoff-supervisor.log').open('x') as log:
    child=subprocess.Popen([PYTHON,str(driver)],cwd='/root/autodl-tmp/intentlab-history-cpu-source-20261023',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
raw=Path('/proc/'+str(child.pid)+'/stat').read_text()
ticks=raw[raw.rfind(')')+2:].split()[19]
print(json.dumps({'pid':child.pid,'start_ticks':ticks,'driver_sha256':DRIVER_SHA}))
'''.replace('Path(DRIVER)', 'Path(' + repr(DRIVER) + ')').replace('DRIVER_SHA', repr(driver_sha)).replace('Path(ROOT)', 'Path(' + repr(REMOTE) + ')').replace('ATTESTATION', repr(attestation)).replace('[PYTHON,', '[' + repr(PYTHON) + ',')
    return remote_code(code)


def main():
    if '--probe' in sys.argv:
        print(json.dumps({'backup_gate_ready': backup_gate(BACKUP) is not None, 'scoring_launched': False}))
        return
    LOCAL.mkdir(exist_ok=False)
    status = {'kind': 'local_frozen_scoring_handoff', 'status': 'waiting_for_verified_backup',
              'no_automatic_retry': True, 'scoring_launched': False, 'm5_complete': False, 'm8_complete': False}
    def save():
        status['observed_utc'] = datetime.now(timezone.utc).isoformat()
        target = LOCAL / 'status.tmp'
        target.write_text(json.dumps(status, indent=2) + '\n')
        target.replace(LOCAL / 'status.json')
    save()
    try:
        while True:
            attestation = backup_gate(BACKUP)
            if attestation is not None:
                break
            save()
            time.sleep(60)
        (LOCAL / 'off-host-attestation.json').write_text(json.dumps(attestation, indent=2) + '\n')
        # Do not retry this launch, even when SSH completion cannot be observed.
        status.update(status='dispatching_once', launch_requested=True)
        save()
        job = launch(attestation)
        status.update(status='remote_scoring_dispatched', scoring_launched=True, job=job)
        save()
    except BaseException as exc:
        status.update(status='failed', error_type=type(exc).__name__, error=str(exc))
        save()
        raise


if __name__ == '__main__':
    main()
