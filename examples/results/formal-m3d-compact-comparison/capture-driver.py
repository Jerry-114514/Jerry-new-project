"""Export aggregate metadata only after all planned calls and asset check exist."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import runpy
import shutil
import subprocess
import sys
from zipfile import ZipFile,ZIP_DEFLATED

source=Path('/root/autodl-tmp/Jerry-formal-v2-20261022')
sys.path.insert(0,str(source))
from intentlab.core import digest
from intentlab.formal_data import read_jsonl,write_jsonl
root=Path('/root/autodl-tmp/compact-diagnostic-comparison-20261023')
manifest=json.loads((root/'manifest.json').read_text())
assert manifest['status']=='completed' and manifest['actual_calls']==208
assert (root/'official-assets-after-run.json').is_file()
assert hashlib.sha256((root/'raw-calls.jsonl').read_bytes()).hexdigest()==manifest['raw_calls_sha256']
adapted=Path('/root/autodl-tmp/wikisql-adapter-validation-20261023/source/runs/private-adaptation-v1')
natural=Path('/root/autodl-tmp/wikisql-natural-collection-20261023/private-export')
cases=read_jsonl(source/'examples/results/formal-m2b-source-triage/triage/coordinator-cases.jsonl')+read_jsonl(adapted/'cases.jsonl')+read_jsonl(natural/'first-two/intake/coordinator-cases.jsonl')+read_jsonl(natural/'remaining-ten/intake/coordinator-cases.jsonl')
assert digest(cases)==manifest['cases_hash']
records=read_jsonl(root/'raw-calls.jsonl')
analyze=runpy.run_path(str(root/'analyze.py'))['analyze']
report=analyze(cases,manifest,json.loads((root/'preflight.json').read_text()),records)
public=root/'public-evidence';public.mkdir(exist_ok=False)
for name in ('manifest.json','preflight.json','official-assets-after-run.json'):
    shutil.copyfile(root/name,public/name)
(public/'analysis.json').write_text(json.dumps(report,indent=2)+'\n')
runtime={'scope':'post_run_environment_capture','python':platform.python_version(),
    'packages':{name:importlib.metadata.version(name) for name in ('torch','transformers','tokenizers','peft','accelerate')},
    'gpu':subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total','--format=csv,noheader'],text=True).strip(),
    'analyzer_sha256':hashlib.sha256((root/'analyze.py').read_bytes()).hexdigest(),
    'driver_sha256':manifest['driver_sha256'],'versions_captured_after_run':True,
    'warning':'Post-run dependency capture, not external attestation of model execution or human review.'}
(public/'runtime-identity.json').write_text(json.dumps(runtime,indent=2)+'\n')
write_jsonl(root/'private-coordinator-cases.jsonl',cases)
private_names=('raw-calls.jsonl','manifest.json','preflight.json','official-assets-after-run.json','private-coordinator-cases.jsonl')
(public/'private-file-sha256.json').write_text(json.dumps({n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in private_names},indent=2)+'\n')
with ZipFile(root/'private-results.zip','w',ZIP_DEFLATED) as zipped:
    for name in private_names:zipped.write(root/name,name)
with ZipFile(root/'public-results.zip','w',ZIP_DEFLATED) as zipped:
    for p in public.iterdir():zipped.write(p,p.name)
print(json.dumps(report,indent=2),flush=True)
