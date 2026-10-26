"""Read live M7 identities and counts without emitting task IDs or actor outputs."""
import json
from pathlib import Path
import shlex
from m5_observer_transport_20261025 import run_remote

WORKSPACE = Path(__file__).resolve().parents[1]
PYTHON = '/root/autodl-tmp/intentlab-venv/bin/python'
CODE = '''import json,time
from pathlib import Path
root=Path('/root/autodl-tmp/formal-ablation-run-20261025')
status=json.loads((root/'supervisor-status.json').read_text())
assert status['pid']==448227 and status['start_ticks']=='893622222'
assert status['driver_sha256']=='d97fff09401b8579c52b25f68883b1e37adf4b57174cfe8a877650b26cdd06b7'
assert status['execution_receipt_hash']=='5a3bd558d8e0a28030193dbedefb69b8d45210c9e1ea62212729a34adddd2ea7'
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
    'diagnostic_receipt_hash':status['diagnostic_receipt_hash'],'execution_receipt_hash':status['execution_receipt_hash'],'m7_complete':status['m7_complete'],
    'interaction_status':manifest['status'],'active_condition':manifest.get('active_condition'),
    'completed_interaction_records':count,'conditions':manifest['conditions'],'tasks_per_condition':len(manifest['ordered_task_ids']),
    'model_residency':manifest.get('model_residency'),'offline_references_opened':manifest['offline_references_opened'],
    'injected_pool':manifest['injected_pool'],'upstream':manifest['upstream']}))
'''

if __name__ == '__main__':
    value = json.loads(run_remote(WORKSPACE, PYTHON + ' -c ' + shlex.quote(CODE)))
    path = WORKSPACE / 'runs/formal-m7-observation-20261026/live.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n')
    print(json.dumps(value))
