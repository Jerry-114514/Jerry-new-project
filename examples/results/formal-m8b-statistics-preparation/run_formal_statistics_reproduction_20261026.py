"""Frozen statistics plus fresh-directory replay; never full M8 acceptance."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

SOURCE = Path('/root/autodl-tmp/intentlab-history-cpu-source-20261023')
ROOT = Path('/root/autodl-tmp/formal-statistics-supervision-20261026')
STATISTICS = Path('/root/autodl-tmp/formal-statistics-run-20261025')
REPLAY = Path('/root/autodl-tmp/formal-statistics-replay-20261026')
M5 = Path('/root/autodl-tmp/formal-diagnostic-run-20261025')
M6 = Path('/root/autodl-tmp/formal-execution-run-20261025')
M7 = Path('/root/autodl-tmp/formal-ablation-run-20261025')
PROTOCOL = Path('/root/autodl-tmp/history-shared-freeze-preparation-20261023/formal-protocol.lock.json')
BINDING = Path('/root/autodl-tmp/formal-model-binding-20261025.json')
ATTESTATION = Path('/root/autodl-tmp/formal-m7-backup-attestation-20261026.json')
PYTHON = '/root/autodl-tmp/intentlab-venv/bin/python'
COMMIT = '20214fb28ba1c8a4a2be0be075c97e33eedb2ba0'
LOCK = 'a1b0440b0f93cfcb76ad9971cbfe73e8f08b30e45a6fef091c7cb74cc31fc027'
BINDING_HASH = 'd27c35ff115f969cbe7a3b45e0b22f1bdb284d925e58f89819be83301523a003'
GUARD_HASH = '454fa5c55c510ed4521ba7e59d38869e1bcde6d7d6fd697e96198bc3db7cb689'
M7_DRIVER_HASH = 'd97fff09401b8579c52b25f68883b1e37adf4b57174cfe8a877650b26cdd06b7'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_m7_gate(status, claim, receipt, backup, digest):
    assert status['kind'] == 'frozen_m7_ablation_supervisor'
    assert status['driver_sha256'] == M7_DRIVER_HASH
    assert status['runtime_commit'] == COMMIT
    assert status['protocol_hash'] == LOCK and status['binding_hash'] == BINDING_HASH
    assert status['status'] == 'completed' and status['m7_complete'] is True
    assert all(status[k] == claim[k] for k in ('pid', 'start_ticks', 'driver_sha256', 'started_unix'))
    assert [r['action'] for r in status['stages']] == ['interact', 'verify', 'reveal', 'verify-reveal']
    assert all(r['status'] == 'completed' and r['exit_code'] == 0 for r in status['stages'])
    assert receipt['kind'] == 'frozen_ablation_reveal' and receipt['status'] == 'completed'
    assert receipt['scope'] == 'formal' and receipt['protocol_hash'] == LOCK
    assert receipt['model_binding_hash'] == BINDING_HASH
    assert receipt['receipt_hash'] == status['ablation_receipt_hash']
    assert receipt['receipt_hash'] == digest({k: v for k, v in receipt.items() if k != 'receipt_hash'})
    assert receipt['upstream']['execution_receipt_hash'] == status['execution_receipt_hash']
    assert backup['kind'] == 'observed_off_host_m7_backup_gate'
    assert backup['protocol_hash'] == LOCK and backup['binding_hash'] == BINDING_HASH
    assert backup['ablation_receipt_hash'] == receipt['receipt_hash']
    assert backup['all_archive_members_reverified'] is True
    assert backup['interaction_records'] == backup['scored_records'] == 1800


def commands():
    common = ['--protocol', str(PROTOCOL), '--binding', str(BINDING),
              '--predictions', str(M5 / 'predictions'), '--diagnostic-reveal', str(M5 / 'reveal'),
              '--execution-interactions', str(M6 / 'interactions'), '--execution-reveal', str(M6 / 'reveal'),
              '--ablation-interactions', str(M7 / 'interactions'), '--ablation-reveal', str(M7 / 'reveal')]
    return [(name, [PYTHON, '-m', 'intentlab.frozen_statistics', action, *common, flag, str(directory)])
            for name, action, flag, directory in
            [('analysis', 'run', '--out', STATISTICS), ('verify', 'verify', '--statistics', STATISTICS),
             ('replay', 'run', '--out', REPLAY), ('verify-replay', 'verify', '--statistics', REPLAY)]]


def main():
    if not __debug__:
        raise RuntimeError('Assertion checks must remain enabled')
    sys.path.insert(0, str(SOURCE))
    from intentlab.core import canonical, digest
    from intentlab.gpu_lease import process_identity, compute_processes

    def clean_and_budget():
        assert subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip() == COMMIT
        assert not subprocess.check_output(['git', '-C', str(SOURCE), 'status', '--porcelain'])
        base = Path('/root/autodl-tmp/intentlab-budget-20261023')
        guard = read(base / 'status.json')
        assert guard['config_sha256'] == GUARD_HASH == sha(base / 'config.json')
        assert guard['pid'] == 181444 and guard['start_ticks'] == '867274705'
        assert process_identity(guard['pid']).get('start_ticks') == guard['start_ticks']
        assert guard['status'] == 'monitoring' and 0 <= time.time() - guard['unix'] < 120
        assert guard['remaining_operating_seconds'] > 600

    clean_and_budget()
    lock, binding = read(PROTOCOL), read(BINDING)
    assert lock['lock_hash'] == LOCK == digest({k: v for k, v in lock.items() if k != 'lock_hash'})
    assert binding['training_protocol_hash'] == LOCK
    assert binding['binding_hash'] == BINDING_HASH == digest({k: v for k, v in binding.items() if k != 'binding_hash'})
    m7, claim = read(M7 / 'supervisor-status.json'), read(M7 / 'supervisor.claim.json')
    receipt, backup = read(M7 / 'reveal/manifest.json'), read(ATTESTATION)
    validate_m7_gate(m7, claim, receipt, backup, digest)
    assert not process_identity(m7['pid']).get('proc_visible')
    assert all(not process_identity(r['child_pid']).get('proc_visible') for r in m7['stages'])
    assert backup['archive_sha256'] == sha(M7 / 'sealed-ablation.tar')
    assert not compute_processes(), 'M7 GPU execution must end before statistics begin'
    assert not any(path.exists() for path in (ROOT, STATISTICS, REPLAY))
    ROOT.mkdir(mode=0o700, exist_ok=False)
    state = {'kind': 'frozen_statistics_reproduction_supervisor', 'status': 'starting', 'pid': os.getpid(),
             'start_ticks': process_identity(os.getpid())['start_ticks'], 'runtime_commit': COMMIT,
             'protocol_hash': LOCK, 'binding_hash': BINDING_HASH, 'ablation_receipt_hash': receipt['receipt_hash'],
             'backup_attestation_sha256': sha(ATTESTATION), 'driver_sha256': sha(Path(__file__)),
             'started_unix': time.time(), 'stages': [], 'no_automatic_retry': True,
             'statistics_reproduction_complete': False, 'm8_complete': False}
    with (ROOT / 'supervisor.claim.json').open('x') as handle:
        json.dump(state, handle)

    def save():
        temporary = ROOT / 'supervisor-status.tmp'
        temporary.write_text(json.dumps(state, indent=2) + '\n')
        temporary.replace(ROOT / 'supervisor-status.json')

    save()
    try:
        for name, command in commands():
            clean_and_budget()
            entry = {'action': name, 'command': command, 'status': 'starting', 'started_unix': time.time()}
            state['stages'].append(entry)
            state.update(status='running', active_action=name)
            save()
            with (ROOT / (name + '.log')).open('x') as log:
                child = subprocess.Popen(command, cwd=SOURCE, stdout=log, stderr=subprocess.STDOUT,
                                         env=dict(os.environ, OMP_NUM_THREADS='2', MKL_NUM_THREADS='2'))
                entry.update(status='running', child_pid=child.pid, child_start_ticks=process_identity(child.pid)['start_ticks'])
                save()
                code = child.wait()
            entry.update(status='completed' if code == 0 else 'failed', exit_code=code, finished_unix=time.time())
            save()
            if code:
                raise RuntimeError(f'Frozen statistics {name} failed with exit {code}; no retry')
        first, replay = read(STATISTICS / 'report.json'), read(REPLAY / 'report.json')
        assert canonical(first) == canonical(replay), 'Preserve both reports on replay mismatch'
        assert first['scope'] == 'formal' and first['protocol_hash'] == LOCK and first['m8_complete'] is False
        assert first['secondary_family_size'] == 17 and len(first['comparisons']) == 18
        manifests = [read(path / 'manifest.json') for path in (STATISTICS, REPLAY)]
        assert all(m['status'] == 'completed' and m['m8_complete'] is False for m in manifests)
        state.update(status='completed', statistics_reproduction_complete=True, m8_complete=False,
                     canonical_reports_identical=True, report_content_digest=digest(first),
                     statistics_receipt_hash=manifests[0]['receipt_hash'], replay_receipt_hash=manifests[1]['receipt_hash'],
                     remaining=['scientific assumptions and M2 acceptance', 'off-host statistics backup',
                                'final report, release and complete artifact acceptance'], finished_unix=time.time())
        save()
    except BaseException as exc:
        state.update(status='failed', error_type=type(exc).__name__, error=str(exc), finished_unix=time.time())
        save()
        raise


if __name__ == '__main__':
    main()
