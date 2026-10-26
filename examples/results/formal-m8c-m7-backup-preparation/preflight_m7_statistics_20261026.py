"""Record remote script hashes and unchanged source/budget identities; no GPU call."""
import hashlib
import json
from pathlib import Path
import shlex
from m5_observer_transport_20261025 import run_remote

workspace = Path(__file__).resolve().parents[1]
names = ('prepare_m7_backup_20261026.py', 'run_formal_statistics_reproduction_20261026.py')
local = {n: hashlib.sha256((workspace / 'tmp' / n).read_bytes()).hexdigest() for n in names}
code = '''import ast,hashlib,json,subprocess,time
from pathlib import Path
names=NAMES
hashes={}
for name in names:
    path=Path('/root/autodl-tmp')/name
    ast.parse(path.read_text())
    hashes[name]=hashlib.sha256(path.read_bytes()).hexdigest()
source=Path('/root/autodl-tmp/intentlab-history-cpu-source-20261023')
base=Path('/root/autodl-tmp/intentlab-budget-20261023')
guard=json.loads((base/'status.json').read_text())
raw=Path('/proc',str(guard['pid']),'stat').read_text()
ticks=raw[raw.rfind(')')+2:].split()[19]
assert ticks==guard['start_ticks'] and guard['status']=='monitoring'
assert 0<=time.time()-guard['unix']<120
print(json.dumps({'deployed_script_sha256':hashes,
    'runtime_commit':subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip(),
    'runtime_clean':not subprocess.check_output(['git','-C',str(source),'status','--porcelain']),
    'm7_output_exists':Path('/root/autodl-tmp/formal-ablation-run-20261025').exists(),
    'statistics_output_exists':Path('/root/autodl-tmp/formal-statistics-run-20261025').exists(),
    'guard_pid':guard['pid'],'guard_start_ticks':ticks,'budget_status':guard['status'],
    'budget_config_sha256':hashlib.sha256((base/'config.json').read_bytes()).hexdigest(),
    'estimated_proxy_spend_yuan':guard['estimated_proxy_spend_yuan'],
    'remaining_operating_hours':guard['remaining_operating_seconds']/3600,'observed_unix':time.time()}))
'''.replace('NAMES', repr(names))
result = json.loads(run_remote(workspace, '/root/autodl-tmp/intentlab-venv/bin/python -c ' + shlex.quote(code)))
assert result['deployed_script_sha256'] == local
assert result['runtime_commit'] == '20214fb28ba1c8a4a2be0be075c97e33eedb2ba0' and result['runtime_clean'] is True
assert result['guard_pid'] == 181444 and result['guard_start_ticks'] == '867274705'
assert result['budget_config_sha256'] == '454fa5c55c510ed4521ba7e59d38869e1bcde6d7d6fd697e96198bc3db7cb689'
out = workspace / 'runs/m7-statistics-admission-20261026'
out.mkdir(exist_ok=False)
(out / 'preflight.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps(result))
