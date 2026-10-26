"""Read live M6 identities and counts without emitting task IDs or actor outputs."""
import json
from pathlib import Path
import shlex
from m5_observer_transport_20261025 import run_remote

WORKSPACE = Path(__file__).resolve().parents[1]
PYTHON = '/root/autodl-tmp/intentlab-venv/bin/python'
CODE = '''import json,time
from pathlib import Path
root=Path('/root/autodl-tmp/formal-execution-run-20261025')
status=json.loads((root/'supervisor-status.json').read_text())
def identity(pid):
    try:raw=Path('/proc',str(pid),'stat').read_text()
    except FileNotFoundError:return None
    fields=raw[raw.rfind(')')+2:].split()
    return {'pid':pid,'start_ticks':fields[19],'state':fields[0]}
parent=identity(status['pid'])
stage=status['stages'][-1]
child=identity(stage['child_pid']) if 'child_pid' in stage else None
if parent is not None:assert parent['start_ticks']==status['start_ticks']
if child is not None:assert child['start_ticks']==stage['child_start_ticks']
manifest=json.loads((root/'interactions/manifest.json').read_text())
count=0
with (root/'interactions/interactions.jsonl').open('rb') as handle:
    for block in iter(lambda:handle.read(1024*1024),b''):count+=block.count(b'\\n')
print(json.dumps({'observed_unix':time.time(),'supervisor_status':status['status'],'active_action':status.get('active_action'),
    'supervisor':parent,'child':child,'runtime_commit':status['runtime_commit'],'driver_sha256':status['driver_sha256'],
    'protocol_hash':status['protocol_hash'],'binding_hash':status['binding_hash'],
    'diagnostic_receipt_hash':status['diagnostic_receipt_hash'],'m6_complete':status['m6_complete'],
    'interaction_status':manifest['status'],'active_condition':manifest.get('active_condition'),
    'completed_interaction_records':count,'conditions':manifest['conditions'],'tasks_per_condition':len(manifest['ordered_task_ids']),
    'model_residency':manifest.get('model_residency'),'offline_references_opened':manifest['offline_references_opened'],
    'injected_pool':manifest['injected_pool']}))
'''

if __name__ == '__main__':
    value = json.loads(run_remote(WORKSPACE, PYTHON + ' -c ' + shlex.quote(CODE)))
    path = WORKSPACE / 'runs/formal-m5-scoring-backup-20261026/m6-live-observation.json'
    path.write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps(value))
