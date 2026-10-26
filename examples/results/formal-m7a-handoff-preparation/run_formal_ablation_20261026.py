"""One-shot frozen M7 controls and scoring after verified M6 off-host backup."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

SOURCE = Path('/root/autodl-tmp/intentlab-history-cpu-source-20261023')
ROOT = Path('/root/autodl-tmp/formal-ablation-run-20261025')
M6 = Path('/root/autodl-tmp/formal-execution-run-20261025')
M5 = Path('/root/autodl-tmp/formal-diagnostic-run-20261025')
PROTOCOL = Path('/root/autodl-tmp/history-shared-freeze-preparation-20261023/formal-protocol.lock.json')
BINDING = Path('/root/autodl-tmp/formal-model-binding-20261025.json')
ATTESTATION = Path('/root/autodl-tmp/formal-m6-backup-attestation-20261026.json')
PYTHON = '/root/autodl-tmp/intentlab-venv/bin/python'
COMMIT = '20214fb28ba1c8a4a2be0be075c97e33eedb2ba0'
LOCK = 'a1b0440b0f93cfcb76ad9971cbfe73e8f08b30e45a6fef091c7cb74cc31fc027'
BINDING_HASH = 'd27c35ff115f969cbe7a3b45e0b22f1bdb284d925e58f89819be83301523a003'
GUARD_HASH = '454fa5c55c510ed4521ba7e59d38869e1bcde6d7d6fd697e96198bc3db7cb689'


def read(path):
    return json.loads(path.read_text())


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def validate_m6_gate(status, execution, attestation, digest):
    """Validate terminal receipts before any M7 directory or claim is created."""
    assert status['pid'] == 412780 and status['start_ticks'] == '889586178'
    assert status['runtime_commit'] == COMMIT
    assert status['protocol_hash'] == LOCK and status['binding_hash'] == BINDING_HASH
    assert status['status'] == 'completed' and status['m6_complete'] is True
    assert [row['action'] for row in status['stages']] == ['interact', 'verify', 'reveal', 'verify-reveal']
    assert all(row['status'] == 'completed' and row['exit_code'] == 0 for row in status['stages'])
    assert execution['kind'] == 'frozen_execution_reveal' and execution['status'] == 'completed'
    assert execution['scope'] == 'formal' and execution['protocol_hash'] == LOCK
    assert execution['model_binding_hash'] == BINDING_HASH
    assert execution['receipt_hash'] == status['execution_receipt_hash']
    assert execution['receipt_hash'] == digest({k: v for k, v in execution.items() if k != 'receipt_hash'})
    assert attestation['kind'] == 'observed_off_host_m6_backup_gate'
    assert attestation['protocol_hash'] == LOCK and attestation['binding_hash'] == BINDING_HASH
    assert attestation['execution_receipt_hash'] == execution['receipt_hash']
    assert attestation['all_archive_members_reverified'] is True
    assert attestation['interaction_records'] == attestation['scored_records'] == 1200


def main():
    if not __debug__:
        raise RuntimeError('Assertion checks must remain enabled')
    sys.path.insert(0, str(SOURCE))
    from intentlab.core import digest
    from intentlab.gpu_lease import compute_processes, process_identity

    def clean_and_budget():
        assert subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip() == COMMIT
        assert not subprocess.check_output(['git', '-C', str(SOURCE), 'status', '--porcelain'])
        base = Path('/root/autodl-tmp/intentlab-budget-20261023')
        guard = read(base / 'status.json')
        assert guard['config_sha256'] == GUARD_HASH == sha(base / 'config.json')
        assert guard['pid'] == 181444 and guard['start_ticks'] == '867274705'
        assert process_identity(guard['pid']).get('start_ticks') == guard['start_ticks']
        assert guard['status'] == 'monitoring' and 0 <= time.time() - guard['unix'] < 120
        assert guard['remaining_operating_seconds'] > 3600

    clean_and_budget()
    lock, binding = read(PROTOCOL), read(BINDING)
    assert lock['lock_hash'] == LOCK == digest({k: v for k, v in lock.items() if k != 'lock_hash'})
    assert binding['training_protocol_hash'] == LOCK
    assert binding['binding_hash'] == BINDING_HASH == digest({k: v for k, v in binding.items() if k != 'binding_hash'})
    completed = read(M5 / 'reveal-handoff-status.json')
    assert completed['pid'] == 395747 and completed['start_ticks'] == '889287066'
    assert completed['status'] == 'completed' and completed['m5_complete'] is True
    assert [row['action'] for row in completed['stages']] == ['verify', 'reveal', 'verify-reveal']
    assert all(row['status'] == 'completed' and row['exit_code'] == 0 for row in completed['stages'])
    assert not process_identity(395747).get('proc_visible')
    assert not process_identity(395798).get('proc_visible')
    diagnostic = read(M5 / 'reveal/manifest.json')
    assert diagnostic['kind'] == 'frozen_diagnostic_reveal' and diagnostic['status'] == 'completed'
    assert diagnostic['scope'] == 'formal' and diagnostic['protocol_hash'] == LOCK
    assert diagnostic['model_binding_hash'] == BINDING_HASH
    assert diagnostic['receipt_hash'] == completed['reveal_receipt_hash']
    assert diagnostic['receipt_hash'] == digest({k: v for k, v in diagnostic.items() if k != 'receipt_hash'})
    execution_status = read(M6 / 'supervisor-status.json')
    execution = read(M6 / 'reveal/manifest.json')
    attestation = read(ATTESTATION)
    validate_m6_gate(execution_status, execution, attestation, digest)
    assert not process_identity(execution_status['pid']).get('proc_visible')
    assert all(not process_identity(row['child_pid']).get('proc_visible') for row in execution_status['stages'])
    assert attestation['archive_sha256'] == sha(M6 / 'sealed-execution.tar')
    assert not compute_processes(), 'GPU must be empty before M7 begins'
    assert not ROOT.exists(), 'Existing M7 output requires coordinator investigation'
    for phase in ('ablation-interactions', 'ablation-reveal'):
        assert not (Path(lock['dataset_export']['root']).parent / f'diagnostic-{LOCK}-{phase}.claim.json').exists()
    ROOT.mkdir(mode=0o700, exist_ok=False)
    status = {'kind': 'frozen_m7_ablation_supervisor', 'status': 'starting', 'pid': os.getpid(),
              'start_ticks': process_identity(os.getpid())['start_ticks'], 'runtime_commit': COMMIT,
              'protocol_hash': LOCK, 'binding_hash': BINDING_HASH, 'diagnostic_receipt_hash': diagnostic['receipt_hash'],
              'execution_receipt_hash': execution['receipt_hash'], 'backup_attestation_sha256': sha(ATTESTATION), 'driver_sha256': sha(Path(__file__)),
              'started_unix': time.time(), 'stages': [], 'no_automatic_retry': True,
              'm7_complete': False, 'm8_complete': False}
    with (ROOT / 'supervisor.claim.json').open('x') as handle:
        json.dump(status, handle)

    def save():
        temporary = ROOT / 'supervisor-status.tmp'
        temporary.write_text(json.dumps(status, indent=2) + '\n')
        temporary.replace(ROOT / 'supervisor-status.json')

    common = ['--protocol', str(PROTOCOL), '--binding', str(BINDING),
              '--predictions', str(M5 / 'predictions'), '--diagnostic-reveal', str(M5 / 'reveal'),
              '--execution-interactions', str(M6 / 'interactions'), '--execution-reveal', str(M6 / 'reveal')]
    stages = [('interact', ['--out', str(ROOT / 'interactions')]),
              ('verify', ['--interactions', str(ROOT / 'interactions')]),
              ('reveal', ['--interactions', str(ROOT / 'interactions'), '--out', str(ROOT / 'reveal')]),
              ('verify-reveal', ['--interactions', str(ROOT / 'interactions'), '--ablation-reveal', str(ROOT / 'reveal')])]
    save()
    try:
        for action, extra in stages:
            clean_and_budget()
            command = [PYTHON, '-m', 'intentlab.frozen_ablation', action, *common, *extra]
            entry = {'action': action, 'command': command, 'status': 'starting', 'started_unix': time.time()}
            status['stages'].append(entry)
            status.update(status='running', active_action=action)
            save()
            env = dict(os.environ, OMP_NUM_THREADS='2', MKL_NUM_THREADS='2',
                       INTENTLAB_CUDA_AUDIT_LOG=str(ROOT / 'gpu-interference.jsonl'))
            with (ROOT / (action + '.log')).open('x') as log:
                child = subprocess.Popen(command, cwd=SOURCE, env=env, stdout=log, stderr=subprocess.STDOUT)
                entry.update(status='running', child_pid=child.pid, child_start_ticks=process_identity(child.pid)['start_ticks'])
                save()
                code = child.wait()
            entry.update(status='completed' if code == 0 else 'failed', exit_code=code, finished_unix=time.time())
            save()
            if code:
                raise RuntimeError(f'Frozen M7 {action} failed with exit {code}; no retry')
        clean_and_budget()
        result = read(ROOT / 'reveal/manifest.json')
        assert result['kind'] == 'frozen_ablation_reveal' and result['status'] == 'completed' and result['scope'] == 'formal'
        assert result['upstream']['execution_receipt_hash'] == execution['receipt_hash']
        status.update(status='completed', m7_complete=True, ablation_receipt_hash=result['receipt_hash'], finished_unix=time.time())
        save()
    except BaseException as exc:
        status.update(status='failed', error_type=type(exc).__name__, error=str(exc), finished_unix=time.time())
        save()
        raise


if __name__ == '__main__':
    main()
