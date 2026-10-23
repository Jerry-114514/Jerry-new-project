"""One additional synthetic hardware probe; no human task target or formal SFT."""
from datetime import datetime, timezone
import json
from pathlib import Path
import runpy
import subprocess
import sys
import time

repo = Path('/root/autodl-tmp/Jerry-formal-v2-20261022')
sys.path.insert(0,str(repo))
from transformers import AutoTokenizer
root = Path('/root/autodl-tmp/context-coverage-20261023')
assert not (root/'attempt-3328.json').exists()
assert subprocess.check_output(['git','-C',str(repo),'rev-parse','HEAD']).decode().strip() == 'c28173490b646a37927aadcdab841a517f56a9b0'
tokenizer = AutoTokenizer.from_pretrained('/root/autodl-tmp/models/Qwen3.5-9B',local_files_only=True,trust_remote_code=False)
probe = runpy.run_path(str(repo/'examples/results/formal-m3a-context-probe/context_probe.py'))
probe['stress_data'](tokenizer,3328,root/'data-3328')
command = [sys.executable,'-m','intentlab.neural','--data',str(root/'data-3328'),'--out',str(root/'train-3328'),
    '--model','/root/autodl-tmp/models/Qwen3.5-9B','--mode','qlora','--device','cuda','--schedule','cosine',
    '--steps','2','--eval-every','1','--batch-size','1','--accumulation','2','--max-length','3328',
    '--lr','0.00005','--minimum-lr','0.000005','--rank','16','--alpha','32','--seed','0','--limit','0','--threads','2','--defer-test']
record = {'scope':'synthetic_3328_hardware_only','actual_sequence_tokens':3328,'formal_training':False,
    'human_task_labels':False,'command':command,'status':'running','created_utc':datetime.now(timezone.utc).isoformat()}
(root/'attempt-3328.json').write_text(json.dumps(record,indent=2)+'\n')
started = time.perf_counter()
with (root/'train-3328.log').open('w') as log:
    result = subprocess.run(command,cwd=repo,stdout=log,stderr=subprocess.STDOUT)
record.update(status='completed' if result.returncode==0 else 'failed',exit_code=result.returncode,wall_seconds=time.perf_counter()-started)
(root/'attempt-3328.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record,indent=2),flush=True)
