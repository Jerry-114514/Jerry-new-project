"""Replay planning and check platform numerical agreement; no experiment data."""
import hashlib
import importlib.util
import json
from pathlib import Path

root=Path(__file__).resolve().parent
repo=root.parents[2]
for name,expected in json.loads((root/'checksums.json').read_text()).items():
    assert hashlib.sha256((root/name).read_bytes()).hexdigest()==expected,name
spec=importlib.util.spec_from_file_location('power_sensitivity',repo/'scripts/power_sensitivity.py')
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
local=json.loads((root/'sensitivity.json').read_text())
remote=json.loads((root/'sensitivity-autodl.json').read_text())
replay=module.planning()
def compare(a,b):
    if isinstance(a,dict):
        assert isinstance(b,dict) and set(a)==set(b)
        for key in a: compare(a[key],b[key])
    elif isinstance(a,list):
        assert len(a)==len(b)
        for left,right in zip(a,b): compare(left,right)
    elif isinstance(a,float):
        assert abs(a-b)<=1e-14,(a,b)
    else:
        assert a==b,(a,b)
compare(local,remote)
compare(local,replay)
assert all(a['normal_approx_sufficient_n']==b['normal_approx_sufficient_n'] for a,b in zip(local['normal_approximation_grid'],remote['normal_approximation_grid']))
print('Planning replay and platform comparison passed at absolute tolerance 1e-14. No empirical power or formal approval.')
