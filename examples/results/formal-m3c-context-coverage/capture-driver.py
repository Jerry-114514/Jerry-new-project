import hashlib
import json
from pathlib import Path
import sys
from zipfile import ZipFile, ZIP_DEFLATED

source=Path('/root/autodl-tmp/Jerry-formal-v2-20261022')
sys.path.insert(0,str(source))
from intentlab.protocol import model_snapshot,verify_official_assets
root=Path('/root/autodl-tmp/context-coverage-20261023')
assert json.loads((root/'attempt-4096.json').read_text())['exit_code']==1
assert json.loads((root/'attempt-3328.json').read_text())['exit_code']==0
log=(root/'train-4096.log').read_text()
assert 'Triton Error [CUDA]: out of memory' in log
assert not (root/'train-4096/result.json').exists()
passed=json.loads((root/'train-3328/result.json').read_text())
assert passed['completed'] and passed['step']==2 and passed['test_deferred'] is True
summary={'scope':'two_synthetic_length_probes_only','failed_sequence_tokens':4096,
    'failure':'RuntimeError: Triton Error [CUDA]: out of memory','failed_wall_seconds':json.loads((root/'attempt-4096.json').read_text())['wall_seconds'],
    'passed_sequence_tokens':3328,'successful_updates':2,'peak_allocated_bytes':passed['peak_allocated_bytes'],
    'peak_reserved_bytes':passed['peak_reserved_bytes'],'successful_wall_seconds':json.loads((root/'attempt-3328.json').read_text())['wall_seconds'],
    'formal_training':False,'human_task_targets':False,'fits_all_formal_targets_or_fewshot':False,
    'warning':'Two synthetic updates in one configuration do not establish a universal memory threshold or formal training runtime. Failed first attempt retained; no 48/80GB hardware tested.'}
(root/'hardware-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
assets=verify_official_assets(model_snapshot('/root/autodl-tmp/models/Qwen3.5-9B'),source)
(root/'official-assets-after-run.json').write_text(json.dumps(assets,indent=2)+'\n')
with ZipFile(root/'public-results.zip','w',ZIP_DEFLATED) as zipped:
    for path in root.rglob('*'):
        if path.is_file() and path.suffix in {'.json','.jsonl','.log'} and '__pycache__' not in path.parts:
            zipped.write(path,path.relative_to(root))
print(json.dumps(summary,indent=2),flush=True)
