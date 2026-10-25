"""Remote one-shot M5 scoring, admitted only after observed off-host backup."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

SOURCE = Path('/root/autodl-tmp/intentlab-history-cpu-source-20261023')
ROOT = Path('/root/autodl-tmp/formal-diagnostic-run-20261025')
PROTOCOL = Path('/root/autodl-tmp/history-shared-freeze-preparation-20261023/formal-protocol.lock.json')
BINDING = Path('/root/autodl-tmp/formal-model-binding-20261025.json')
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


def main():
    sys.path.insert(0, str(SOURCE))
    from intentlab.core import digest
    from intentlab.gpu_lease import compute_processes, process_identity

    def clean_and_budget():
        assert subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip() == COMMIT
        assert not subprocess.check_output(['git', '-C', str(SOURCE), 'status', '--porcelain'])
        guard_root = Path('/root/autodl-tmp/intentlab-budget-20261023')
        guard = read(guard_root / 'status.json')
        assert guard['config_sha256'] == GUARD_HASH == sha(guard_root / 'config.json')
        assert guard['pid'] == 181444 and guard['start_ticks'] == '867274705'
        assert process_identity(guard['pid']).get('start_ticks') == guard['start_ticks']
        assert guard['status'] == 'monitoring' and 0 <= time.time() - guard['unix'] < 120
        assert guard['remaining_operating_seconds'] > 3600

    clean_and_budget()
    lock = read(PROTOCOL)
    binding = read(BINDING)
    assert lock['lock_hash'] == LOCK == digest({k: v for k, v in lock.items() if k != 'lock_hash'})
    assert binding['training_protocol_hash'] == LOCK and binding['binding_hash'] == BINDING_HASH
    assert binding['binding_hash'] == digest({k: v for k, v in binding.items() if k != 'binding_hash'})
    supervisor = read(ROOT / 'supervisor-status.json')
    assert supervisor['pid'] == 326276 and supervisor['start_ticks'] == '880494232'
    assert supervisor['generation_pid'] == 326282 and supervisor['generation_start_ticks'] == '880494240'
    assert supervisor['status'] == 'completed' and supervisor['exit_code'] == 0
    assert not process_identity(326282).get('proc_visible'), 'Generation handle must be gone before scoring'
    prediction = read(ROOT / 'predictions/manifest.json')
    assert prediction['status'] == 'sealed' and prediction['gold_loaded'] is False
    assert prediction['protocol_hash'] == LOCK and prediction['model_binding_hash'] == BINDING_HASH
    attestation = read(ROOT / 'off-host-reveal-attestation-20261026.json')
    assert attestation['kind'] == 'observed_off_host_prediction_backup_gate'
    assert attestation['protocol_hash'] == LOCK and attestation['binding_hash'] == BINDING_HASH
    assert attestation['prediction_seal_hash'] == prediction['seal_hash']
    assert attestation['all_archive_members_reverified'] is True
    assert attestation['gold_read'] is False and attestation['scope'] == 'formal'
    assert attestation['archive_sha256'] == sha(ROOT / 'sealed-predictions.tar')
    assert not compute_processes(), 'GPU must be empty before the one-shot scoring handoff'
    assert not (ROOT / 'reveal').exists()
    reveal_claim = Path(lock['dataset_export']['root']).parent / f'diagnostic-{LOCK}-reveal.claim.json'
    assert not reveal_claim.exists(), 'Existing formal claim requires investigation, never automatic retry'
    status = {'kind': 'frozen_m5_reveal_handoff', 'status': 'starting', 'pid': os.getpid(),
              'start_ticks': process_identity(os.getpid())['start_ticks'], 'protocol_hash': LOCK,
              'binding_hash': BINDING_HASH, 'runtime_commit': COMMIT,
              'driver_sha256': sha(Path(__file__)), 'backup_attestation_sha256': sha(ROOT / 'off-host-reveal-attestation-20261026.json'),
              'no_automatic_retry': True, 'stages': [], 'started_unix': time.time(), 'm5_complete': False, 'm8_complete': False}
    with (ROOT / 'reveal-handoff.claim.json').open('x') as handle:
        json.dump(status, handle)

    def save():
        temporary = ROOT / 'reveal-handoff-status.tmp'
        temporary.write_text(json.dumps(status, indent=2) + '\n')
        temporary.replace(ROOT / 'reveal-handoff-status.json')

    save()
    common = ['--protocol', str(PROTOCOL), '--binding', str(BINDING), '--predictions', str(ROOT / 'predictions')]
    stages = [('verify', []), ('reveal', ['--out', str(ROOT / 'reveal')]),
              ('verify-reveal', ['--reveal', str(ROOT / 'reveal')])]
    try:
        for action, extra in stages:
            clean_and_budget()
            command = [PYTHON, '-m', 'intentlab.diagnostic_protocol', action, *common, *extra]
            entry = {'action': action, 'command': command, 'status': 'starting', 'started_unix': time.time()}
            status['stages'].append(entry)
            status.update(status='running', active_action=action)
            save()
            env = dict(os.environ, OMP_NUM_THREADS='2', MKL_NUM_THREADS='2',
                       INTENTLAB_CUDA_AUDIT_LOG=str(ROOT / 'reveal-gpu-interference.jsonl'))
            with (ROOT / ('reveal-handoff-' + action + '.log')).open('x') as log:
                child = subprocess.Popen(command, cwd=SOURCE, env=env, stdout=log, stderr=subprocess.STDOUT)
                entry.update(status='running', child_pid=child.pid, child_start_ticks=process_identity(child.pid)['start_ticks'])
                save()
                code = child.wait()
            entry.update(status='completed' if code == 0 else 'failed', exit_code=code, finished_unix=time.time())
            save()
            if code:
                raise RuntimeError(f'Frozen scoring {action} failed with exit {code}; no retry')
        clean_and_budget()
        result = read(ROOT / 'reveal/manifest.json')
        assert result['status'] == 'completed' and result['scope'] == 'formal'
        status.update(status='completed', m5_complete=True, reveal_receipt_hash=result['receipt_hash'], finished_unix=time.time())
        save()
    except BaseException as exc:
        status.update(status='failed', error_type=type(exc).__name__, error=str(exc), finished_unix=time.time())
        save()
        raise


if __name__ == '__main__':
    main()
