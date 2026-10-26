"""Copy completed M7 interactions and scoring off host; optionally dispatch frozen statistics reproduction once."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shlex
import sys
import tarfile
import time
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.core import digest
from m5_observer_transport_20261025 import run_remote

WORKSPACE = Path(__file__).resolve().parents[1]
LOCAL = WORKSPACE / 'runs/formal-m7-backup-20261026'
WATCH = WORKSPACE / 'runs/formal-m7-statistics-wait-20261026'
REMOTE = '/root/autodl-tmp/formal-ablation-run-20261025'
PYTHON = '/root/autodl-tmp/intentlab-venv/bin/python'
PREPARE = '/root/autodl-tmp/prepare_m7_backup_20261026.py'
STATISTICS_DRIVER = '/root/autodl-tmp/run_formal_statistics_reproduction_20261026.py'
LOCK = 'a1b0440b0f93cfcb76ad9971cbfe73e8f08b30e45a6fef091c7cb74cc31fc027'
BINDING = 'd27c35ff115f969cbe7a3b45e0b22f1bdb284d925e58f89819be83301523a003'



def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verify_archive(archive, expected):
    assert expected['protocol_hash'] == LOCK and expected['binding_hash'] == BINDING
    assert expected['m7_supervisor_completed'] is True
    assert archive.stat().st_size == expected['archive_bytes'] and sha(archive) == expected['archive_sha256']
    with tarfile.open(archive, 'r:') as handle:
        members = handle.getmembers()
        assert len(members) == len({m.name for m in members}) == len(expected['files'])
        assert {m.name for m in members} == set(expected['files'])
        for member in members:
            path = PurePosixPath(member.name)
            assert member.isfile() and not path.is_absolute() and '..' not in path.parts
            assert str(path) == member.name and '\\' not in member.name and ':' not in member.name
            assert member.size == expected['files'][member.name]['bytes']
            with handle.extractfile(member) as stream:
                assert hashlib.file_digest(stream, 'sha256').hexdigest() == expected['files'][member.name]['sha256']
        manifests = {}
        for directory, kind, state, seal in [('interactions', 'frozen_ablation_interactions', 'sealed', 'seal_hash'),
                                            ('reveal', 'frozen_ablation_reveal', 'completed', 'receipt_hash')]:
            manifest = json.load(handle.extractfile(directory + '/manifest.json'))
            assert manifest['kind'] == kind and manifest['status'] == state and manifest['scope'] == 'formal'
            assert manifest['protocol_hash'] == LOCK and manifest['model_binding_hash'] == BINDING
            assert manifest[seal] == digest({k: v for k, v in manifest.items() if k != seal})
            prefix = directory + '/'
            assert manifest['files_sha256'] == {n[len(prefix):]: row['sha256'] for n, row in expected['files'].items()
                                                if n.startswith(prefix) and n != prefix + 'manifest.json'}
            manifests[directory] = manifest
        assert manifests['interactions']['injected_pool'] is False
        assert manifests['interactions']['offline_references_opened'] is False
        assert manifests['reveal']['interaction_seal_hash'] == manifests['interactions']['seal_hash'] == expected['interaction_seal_hash']
        assert manifests['reveal']['receipt_hash'] == expected['ablation_receipt_hash']
        supervisor = json.load(handle.extractfile('supervisor-status.json'))
        assert supervisor['status'] == 'completed' and supervisor['m7_complete'] is True
        assert supervisor['ablation_receipt_hash'] == manifests['reveal']['receipt_hash']
        assert supervisor['execution_receipt_hash'] == manifests['reveal']['upstream']['execution_receipt_hash']
        assert manifests['interactions']['upstream'] == manifests['reveal']['upstream']
        assert [s['action'] for s in supervisor['stages']] == ['interact', 'verify', 'reveal', 'verify-reveal']
        assert all(s['status'] == 'completed' and s['exit_code'] == 0 for s in supervisor['stages'])
        counts = {}
        for name, key in [('interactions/interactions.jsonl', 'interaction_records'), ('reveal/runs.jsonl', 'scored_records')]:
            with handle.extractfile(name) as stream:
                counts[key] = sum(1 for line in stream if line.endswith(b'\n'))
        assert counts['interaction_records'] == counts['scored_records'] == 1800
        assert all(counts[k] == expected[k] for k in counts)
    return {'kind': 'observed_off_host_m7_backup_gate', 'scope': 'formal',
            'protocol_hash': LOCK, 'binding_hash': BINDING,
            'ablation_receipt_hash': expected['ablation_receipt_hash'],
            'archive_sha256': expected['archive_sha256'], 'archive_bytes': expected['archive_bytes'],
            'verified_members': len(expected['files']), 'all_archive_members_reverified': True,
            'references_reopened_for_backup': False, 'raw_metrics_parsed_for_tuning': False,
            'created_utc': datetime.now(timezone.utc).isoformat(), **counts}


def dispatch_statistics(attestation):
    driver_sha = sha(WORKSPACE / 'tmp/run_formal_statistics_reproduction_20261026.py')
    code = '''import hashlib,json,subprocess
from pathlib import Path
driver=Path(DRIVER)
assert hashlib.sha256(driver.read_bytes()).hexdigest()==DRIVER_SHA
with Path('/root/autodl-tmp/formal-m7-backup-attestation-20261026.json').open('x') as handle:json.dump(ATTESTATION,handle)
with Path('/root/autodl-tmp/formal-statistics-supervisor-20261026.log').open('x') as log:
    child=subprocess.Popen([PYTHON,str(driver)],cwd='/root/autodl-tmp/intentlab-history-cpu-source-20261023',stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
raw=Path('/proc/'+str(child.pid)+'/stat').read_text()
ticks=raw[raw.rfind(')')+2:].split()[19]
print(json.dumps({'pid':child.pid,'start_ticks':ticks,'driver_sha256':DRIVER_SHA}))
'''.replace('Path(DRIVER)', 'Path(' + repr(STATISTICS_DRIVER) + ')').replace('DRIVER_SHA', repr(driver_sha)).replace('ATTESTATION', repr(attestation)).replace('[PYTHON,', '[' + repr(PYTHON) + ',')
    return json.loads(run_remote(WORKSPACE, PYTHON + ' -c ' + shlex.quote(code), timeout=180))


def await_m7():
    WATCH.mkdir(exist_ok=False)
    state = {'kind': 'one_shot_m7_to_statistics_wait', 'pid': os.getpid(), 'status': 'waiting_for_m7',
             'no_automatic_model_retry': True, 'statistics_dispatched_by_wait_phase': False}
    def save():
        state['observed_utc'] = datetime.now(timezone.utc).isoformat()
        target = WATCH / 'status.tmp'
        target.write_text(json.dumps(state, indent=2) + '\n')
        target.replace(WATCH / 'status.json')
    save()
    try:
        while True:
            observed = json.loads(run_remote(WORKSPACE, PYTHON + ' ' + PREPARE + ' --probe'))
            state['observation'] = observed
            if observed['ready'] is True:
                state.update(status='m7_ready_for_backup', wait_phase_completed=True)
                save()
                return observed
            assert observed['supervisor_status'] in {'running', 'completed'} and (observed['parent'] is not None or observed.get('active_children')), 'M7 admission needs investigation; no STATISTICS dispatch'
            save()
            time.sleep(60)
    except BaseException as exc:
        state.update(status='observation_or_admission_failed', error_type=type(exc).__name__, error=str(exc))
        save()
        raise


def main():
    if not __debug__:
        raise RuntimeError('Assertion checks must remain enabled')
    observed = (await_m7() if '--wait' in sys.argv else
                json.loads(run_remote(WORKSPACE, PYTHON + ' ' + PREPARE + ' --probe')))
    if '--probe' in sys.argv:
        print(json.dumps(observed))
        return
    assert observed['ready'] is True, 'M7 must finish before any scoring backup or STATISTICS dispatch'
    LOCAL.mkdir(exist_ok=False)
    status = {'kind': 'm7_scoring_backup_then_optional_statistics', 'status': 'creating_ablation_archive',
              'statistics_launch_requested': False, 'statistics_dispatched': False, 'no_automatic_model_retry': True, 'm8_complete': False}
    def save():
        status['observed_utc'] = datetime.now(timezone.utc).isoformat()
        target = LOCAL / 'status.tmp'
        target.write_text(json.dumps(status, indent=2) + '\n')
        target.replace(LOCAL / 'status.json')
    save()
    try:
        expected = json.loads(run_remote(WORKSPACE, PYTHON + ' ' + PREPARE + ' --create', timeout=1800))
        (LOCAL / 'source-inventory.json').write_text(json.dumps(expected, indent=2) + '\n')
        status.update(status='copying_ablation_archive')
        save()
        archive = LOCAL / 'sealed-ablation.tar'
        run_remote(WORKSPACE, 'get', REMOTE + '/sealed-ablation.tar', str(archive), timeout=1800)
        attestation = verify_archive(archive, expected)
        (LOCAL / 'off-host-attestation.json').write_text(json.dumps(attestation, indent=2) + '\n')
        status.update(status='ablation_backup_verified', backup=attestation)
        save()
        if '--launch-statistics' in sys.argv:
            status.update(status='dispatching_statistics_once', statistics_launch_requested=True)
            save()
            job = dispatch_statistics(attestation)
            status.update(status='statistics_dispatched', statistics_dispatched=True, job=job)
            save()
        print(json.dumps({'status': status['status'], 'ablation_backup_verified': True, 'statistics_dispatched': status['statistics_dispatched']}))
    except BaseException as exc:
        status.update(status='failed', error_type=type(exc).__name__, error=str(exc))
        save()
        raise


if __name__ == '__main__':
    main()
