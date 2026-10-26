"""Recover the failed local observer; retry read-only probes, never model stages."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import backup_completed_m6_20261026 as bridge

ORIGINAL = bridge.WATCH
RECOVERY = bridge.WORKSPACE / 'runs/formal-m6-m7-wait-recovery-20261026'
ORIGINAL_BRIDGE_SHA = 'd3cb0ae5b0bf2fb48c7ee8a90c2f9bb44ecfa13fda18feeff766822f109695c5'


def await_m6():
    bridge.WATCH.mkdir(exist_ok=False)
    state = {'kind': 'recovered_m6_to_m7_read_only_wait', 'pid': os.getpid(), 'status': 'waiting_for_m6',
             'original_waiter_pid': 28332, 'no_automatic_model_retry': True,
             'm7_dispatched_by_wait_phase': False, 'probe_errors': [], 'consecutive_probe_errors': 0}

    def save():
        state['observed_utc'] = datetime.now(timezone.utc).isoformat()
        target = bridge.WATCH / 'status.tmp'
        target.write_text(json.dumps(state, indent=2) + '\n')
        target.replace(bridge.WATCH / 'status.json')

    save()
    try:
        while True:
            try:
                # This is the sole retried operation. It cannot create archives,
                # claims, formal model runs, score reveals or dispatch children.
                raw = bridge.run_remote(bridge.WORKSPACE, bridge.PYTHON + ' ' + bridge.PREPARE + ' --probe')
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                if isinstance(exc, subprocess.CalledProcessError) and exc.returncode != 255:
                    raise
                state['consecutive_probe_errors'] += 1
                state['probe_errors'].append({'observed_utc': datetime.now(timezone.utc).isoformat(),
                    'error_type': type(exc).__name__, 'exit_code': getattr(exc, 'returncode', None)})
                state['status'] = 'read_only_probe_retry_pending'
                save()
                if state['consecutive_probe_errors'] >= 3:
                    raise RuntimeError('Three consecutive read-only SSH probe failures; investigate original handles') from exc
                time.sleep((10, 30)[state['consecutive_probe_errors'] - 1])
                continue
            observed = json.loads(raw)
            state.update(observation=observed, consecutive_probe_errors=0, status='waiting_for_m6')
            if observed['ready'] is True:
                state.update(status='m6_ready_for_backup', wait_phase_completed=True)
                save()
                return observed
            assert observed['supervisor_status'] in {'running', 'completed'}
            assert observed['parent'] is not None or observed.get('active_children'), 'Original handles missing; no dispatch'
            save()
            time.sleep(60)
    except BaseException as exc:
        state.update(status='observation_or_admission_failed', error_type=type(exc).__name__, error=str(exc))
        save()
        raise


def main():
    assert __debug__ and sys.argv[1:] == ['--wait', '--launch-m7']
    assert hashlib.sha256(Path(bridge.__file__).read_bytes()).hexdigest() == ORIGINAL_BRIDGE_SHA
    previous = json.loads((ORIGINAL / 'status.json').read_text())
    assert previous['pid'] == 28332 and previous['status'] == 'observation_or_admission_failed'
    assert previous['m7_dispatched_by_wait_phase'] is False
    assert not bridge.LOCAL.exists() and not RECOVERY.exists()
    command = "$prior = Get-Process -Id 28332 -ErrorAction SilentlyContinue; if ($null -ne $prior) { throw 'Original waiter still exists' }; 'ABSENT'"
    assert subprocess.check_output(['powershell', '-NoProfile', '-NonInteractive', '-Command', command], text=True).strip() == 'ABSENT'
    bridge.WATCH = RECOVERY
    bridge.await_m6 = await_m6
    # Mutation/backup/dispatch routines remain the original once-only functions;
    # exceptions there propagate immediately without transport or model retries.
    bridge.main()


if __name__ == '__main__':
    main()
