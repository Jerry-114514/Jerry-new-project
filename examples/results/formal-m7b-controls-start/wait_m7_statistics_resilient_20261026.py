"""Start a bounded read-only M7 observer; never retry model or statistics stages."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import backup_completed_m7_20261026 as bridge

ORIGINAL_BRIDGE_SHA = 'a5215007d7816ffaae9174b3d0c6079c3ce715b1c21983aca95aacc285dbba24'


def await_m7():
    bridge.WATCH.mkdir(exist_ok=False)
    state = {'kind': 'resilient_m7_to_statistics_read_only_wait', 'pid': os.getpid(), 'status': 'waiting_for_m7',
             'expected_m7_supervisor_pid': 448227, 'expected_m7_supervisor_ticks': '893622222', 'no_automatic_model_retry': True,
             'statistics_dispatched_by_wait_phase': False, 'probe_errors': [], 'consecutive_probe_errors': 0}

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
            state.update(observation=observed, consecutive_probe_errors=0, status='waiting_for_m7')
            if observed.get('parent') is not None:
                assert observed['parent']['start_ticks'] == '893622222', 'M7 process identity changed'
            if observed['ready'] is True:
                state.update(status='m7_ready_for_backup', wait_phase_completed=True)
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
    if not __debug__:
        raise RuntimeError('Assertion checks must remain enabled')
    assert sys.argv[1:] == ['--wait', '--launch-statistics']
    assert hashlib.sha256(Path(bridge.__file__).read_bytes()).hexdigest() == ORIGINAL_BRIDGE_SHA
    assert not bridge.WATCH.exists() and not bridge.LOCAL.exists()
    handoff = json.loads((bridge.WORKSPACE / 'runs/formal-m6-backup-20261026/status.json').read_text())
    assert handoff['status'] == 'm7_dispatched' and handoff['m7_launched'] is True
    assert handoff['job']['pid'] == 448227 and handoff['job']['start_ticks'] == '893622222'
    assert handoff['job']['driver_sha256'] == 'd97fff09401b8579c52b25f68883b1e37adf4b57174cfe8a877650b26cdd06b7'
    assert handoff['backup']['execution_receipt_hash'] == '5a3bd558d8e0a28030193dbedefb69b8d45210c9e1ea62212729a34adddd2ea7'
    verified = json.loads((bridge.WORKSPACE / 'runs/formal-m6-backup-20261026/coordinator-verification.json').read_text())
    assert verified['matches_original_attestation_except_observation_time'] is True
    assert verified['verification']['archive_sha256'] == handoff['backup']['archive_sha256']
    bridge.await_m7 = await_m7
    # Only observation is replaced. Archiving, copying and statistics dispatch
    # remain the original once-only routines, without mutation retries.
    bridge.main()


if __name__ == '__main__':
    main()
