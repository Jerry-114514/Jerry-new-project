import hashlib,json,sys
from pathlib import Path
src=Path('/root/autodl-tmp/intentlab-history-cpu-source-20261023')
sys.path.insert(0,str(src))
from intentlab.core import canonical
from intentlab.neural import encode_pair
from intentlab.prompts import prompt_ids
from transformers import AutoTokenizer
root=Path('/root/autodl-tmp/history-augmented-candidate-20261023/export')
out=Path('/root/autodl-tmp/history-candidate-full-profile-20261023');out.mkdir(mode=0o700,exist_ok=False)
model=Path('/root/autodl-tmp/models/Qwen3.5-9B')
official=json.loads((src/'configs/qwen35-official-assets.json').read_text())
assets={}
for asset in official['assets']:
    if asset['path'] not in {'config.json','tokenizer.json','tokenizer_config.json','chat_template.jinja','merges.txt','vocab.json'}:continue
    raw=(model/asset['path']).read_bytes()
    actual=hashlib.sha256(raw).hexdigest() if 'sha256' in asset else hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    assert actual==asset.get('sha256',asset.get('git_blob_sha1'))
    assets[asset['path']]=hashlib.sha256(raw).hexdigest()
assert len(assets)==6
tokenizer=AutoTokenizer.from_pretrained(model,local_files_only=True,trust_remote_code=False)
examples=json.loads(Path('/root/autodl-tmp/procedural-fewshot-development-20261023/examples.json').read_text())[:3]
prefix='Reviewed examples (do not reuse their answers for the new observation):\n'+canonical([{'input':r['case']['public'],'output':{'findings':r['findings']}} for r in examples])+'\n'
def stats(v):
    v=sorted(v);return {'count':len(v),'sum':sum(v),'minimum':v[0],'p50':v[(len(v)-1)//2],'p95':v[(len(v)-1)*95//100],'maximum':v[-1]}
summary={'scope':'complete_history_augmented_train_validation','source_commit':'71a361d5437d59294696f40ee015c599441df4ec','training_source_sha256':hashlib.sha256((src/'intentlab/neural.py').read_bytes()).hexdigest(),'tokenizer_assets_sha256':assets,'official_revision':official['revision'],'weights_loaded':False,'gpu_used':False,'heldout_files_read':False,'truncation':False,'splits':{}}
for split,wanted in [('train',2464),('validation',664)]:
    raw=(root/(split+'.jsonl')).read_bytes();rows=[json.loads(l) for l in raw.decode().splitlines()]
    assert len(rows)==wanted
    lengths=[];targets=[];b3=[]
    for r in rows:
        n=len(prompt_ids(tokenizer,r['prompt']));m=len(tokenizer.encode(r['completion'],add_special_tokens=False))+int(tokenizer.eos_token_id is not None)
        encoded=encode_pair(tokenizer,r,12288)
        assert len(encoded['input_ids'])==n+m and sum(x!=-100 for x in encoded['labels'])==m
        lengths.append(n+m);targets.append(m)
        if split=='validation':b3.append(len(prompt_ids(tokenizer,prefix+r['prompt'])))
    summary['splits'][split]={'file_sha256':hashlib.sha256(raw).hexdigest(),'source_groups':len({r['task_id'] for r in rows}),'sequence_tokens':stats(lengths),'supervised_tokens':stats(targets),'over_training_context_12288':sum(n>12288 for n in lengths)}
    if b3:summary['splits'][split].update(B3_prompt_tokens=stats(b3),B3_over_17408_with_1536_reserve=sum(n+1536>17408 for n in b3))
(out/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
print(json.dumps(summary,indent=2),flush=True)
