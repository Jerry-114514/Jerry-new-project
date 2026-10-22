import json,subprocess,time
from datetime import datetime,timezone
from pathlib import Path

root=Path('/root/autodl-tmp/context-probe-20261023')
repo=Path('/root/autodl-tmp/Jerry-formal-v2-20261022')
python='/root/autodl-tmp/intentlab-venv/bin/python'
attempts=[]
for length in [1024,2048]:
 command=[python,'-m','intentlab.neural','--data',str(root/f'data-{length}-v2'),'--out',str(root/f'train-{length}'),
  '--model','/root/autodl-tmp/models/Qwen3.5-9B','--mode','qlora','--device','cuda','--schedule','cosine',
  '--steps','2','--eval-every','1','--batch-size','1','--accumulation','2','--max-length',str(length),
  '--lr','0.00005','--minimum-lr','0.000005','--rank','16','--alpha','32','--seed','0','--limit','0','--threads','2','--defer-test']
 record={'length':length,'command':command,'status':'running','created_utc':datetime.now(timezone.utc).isoformat()}
 attempts.append(record)
 (root/'attempts.json').write_text(json.dumps({'scope':'synthetic_hardware_stress_only','attempts':attempts},indent=2)+'\n')
 started=time.perf_counter()
 with (root/f'train-{length}.log').open('w') as stream:
  proc=subprocess.run(command,cwd=repo,stdout=stream,stderr=subprocess.STDOUT)
 record.update(status='completed' if proc.returncode==0 else 'failed',exit_code=proc.returncode,wall_seconds=time.perf_counter()-started)
 (root/'attempts.json').write_text(json.dumps({'scope':'synthetic_hardware_stress_only','attempts':attempts},indent=2)+'\n')
 print(json.dumps(record),flush=True)
