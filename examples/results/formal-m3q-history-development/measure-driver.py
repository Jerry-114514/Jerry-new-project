import hashlib,json,sys,tarfile
from pathlib import Path
sys.path.insert(0,'/root/autodl-tmp/Jerry-formal-v2-20261022')
from intentlab.neural import encode_pair
from intentlab.prompts import prompt_ids
from transformers import AutoTokenizer
archive=Path('/root/autodl-tmp/history-development-input-20261023.tar.gz')
out=Path('/root/autodl-tmp/history-development-lengths-20261023')
out.mkdir(mode=0o700,exist_ok=False)
with tarfile.open(archive) as t:t.extractall(out,filter='data')
tokenizer=AutoTokenizer.from_pretrained('/root/autodl-tmp/models/Qwen3.5-9B',local_files_only=True,trust_remote_code=False)
result={'weights_loaded':False,'gpu_used':False,'heldout_model_outputs_read':False,'test_views_built':False,'truncation':False,'archive_sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'splits':{}}
for split in ['train','validation']:
    rows=[json.loads(l) for l in (out/(split+'.jsonl')).read_text().splitlines()]
    lengths=[];targets=[]
    for row in rows:
        n=len(prompt_ids(tokenizer,row['prompt']))
        m=len(tokenizer.encode(row['completion'],add_special_tokens=False))+int(tokenizer.eos_token_id is not None)
        encoded=encode_pair(tokenizer,row,n+m)
        assert len(encoded['input_ids'])==n+m
        lengths.append(n+m);targets.append(m)
    result['splits'][split]={'views':len(rows),'max_sequence_tokens':max(lengths),'min_sequence_tokens':min(lengths),'max_target_tokens':max(targets),'over_7168':sum(n>7168 for n in lengths),'over_13312':sum(n>13312 for n in lengths),'over_16384':sum(n>16384 for n in lengths)}
(out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
