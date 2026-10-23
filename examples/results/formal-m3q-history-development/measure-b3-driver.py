import json,sys
from pathlib import Path
sys.path.insert(0,'/root/autodl-tmp/Jerry-formal-v2-20261022')
from intentlab.core import canonical
from intentlab.prompts import prompt_ids
from transformers import AutoTokenizer
out=Path('/root/autodl-tmp/history-development-lengths-20261023')
examples=json.loads(Path('/root/autodl-tmp/procedural-fewshot-development-20261023/examples.json').read_text())[:3]
prefix='Reviewed examples (do not reuse their answers for the new observation):\n'+canonical([{'input':r['case']['public'],'output':{'findings':r['findings']}} for r in examples])+'\n'
tok=AutoTokenizer.from_pretrained('/root/autodl-tmp/models/Qwen3.5-9B',local_files_only=True,trust_remote_code=False)
rows=[json.loads(l) for l in (out/'validation.jsonl').read_text().splitlines()]
lengths=[len(prompt_ids(tok,prefix+r['prompt'])) for r in rows]
result={'split':'validation','condition':'B3_fixed_previous_selection','views':len(rows),'weights_loaded':False,'min_prompt_tokens':min(lengths),'max_prompt_tokens':max(lengths),'generation_reserve':1024,'over_16384_with_reserve':sum(n+1024>16384 for n in lengths),'over_17408_with_reserve':sum(n+1024>17408 for n in lengths),'formal_budget_frozen':False}
(out/'B3-summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
