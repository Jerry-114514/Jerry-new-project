"""CPU tokenizer-only audit of selected training and A/B diagnostic prompts.

Never loads model weights or heldout gold. Public output contains lengths and
asset verification only; no case IDs, raw prompts, target text or data hashes.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from intentlab.core import digest
from intentlab.formal_data import read_jsonl
from intentlab.formal_inference import diagnostic_prompt
from intentlab.neural import encode_pair
from intentlab.prompts import prompt_ids


def lengths(values,limit):
    ordered=sorted(values)
    return {'rows':len(values),'min':min(values),'max':max(values),
            'mean':sum(values)/len(values),'p95':ordered[math.ceil(.95*len(values))-1],
            'over_limit':sum(v>limit for v in values),'limit':limit}


def build(selected,base,protocol,out,expected_manifest_sha,expected_protocol_sha):
    selected,base,protocol,out=map(Path,(selected,base,protocol,out))
    if out.exists():raise FileExistsError('Preserve previous length measurements')
    manifest_raw=(selected/'export/manifest.json').read_bytes();protocol_raw=protocol.read_bytes()
    if hashlib.sha256(manifest_raw).hexdigest()!=expected_manifest_sha or hashlib.sha256(protocol_raw).hexdigest()!=expected_protocol_sha:
        raise ValueError('Selection or original examples protocol binding changed')
    manifest=json.loads(manifest_raw);prior=json.loads(protocol_raw)
    provenance=json.loads((base/'download-provenance.json').read_text(encoding='utf-8'))
    if (provenance['model'],provenance['revision'])!=('Qwen/Qwen3.5-9B','c202236235762e1c871ad0ccb60c8ee5ba337b9a'):
        raise ValueError('Unexpected original model provenance')
    records={r['rfilename']:r for r in provenance['files']}
    assets=('config.json','tokenizer_config.json','tokenizer.json','vocab.json','merges.txt','chat_template.jinja')
    for name in assets:
        raw=(base/name).read_bytes();r=records[name]
        if len(raw)!=r['size']:raise ValueError('Tokenizer asset size mismatch')
        actual=(hashlib.sha256(raw).hexdigest() if 'lfs' in r else
                hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest())
        expected=r['lfs']['sha256'] if 'lfs' in r else r['blobId']
        if actual!=expected:raise ValueError('Tokenizer asset does not match original revision')
    os.environ['CUDA_VISIBLE_DEVICES']='-1'
    from transformers import AutoTokenizer
    import transformers,tokenizers
    tokenizer=AutoTokenizer.from_pretrained(base,local_files_only=True,trust_remote_code=False)
    def rows(relative):
        path=selected/'export'/relative
        if hashlib.sha256(path.read_bytes()).hexdigest()!=manifest['files_sha256'][relative]:
            raise ValueError('Selected export changed')
        return read_jsonl(path)
    pairs={};training={}
    for split in ('train','validation'):
        data=rows(split+'.jsonl');total=[];targets=0
        for row in data:
            item=encode_pair(tokenizer,row,12288)
            total.append(len(item['input_ids']));targets+=sum(x!=-100 for x in item['labels'])
            pairs[row['case_id']]=row
        training[split]={**lengths(total,12288),'supervised_tokens_in_one_pass':targets}
    source=read_jsonl(selected/'cases.jsonl')
    if digest(source)!=manifest['cases_hash']:raise ValueError('Selected public cases changed')
    by_id={c['case_id']:c for c in source};examples=[]
    for cid in prior['spec']['few_shot_case_ids']:
        c=by_id[cid]
        if c['split'] not in ('train','validation'):raise ValueError('Example is not development data')
        examples.append({'case':c,'findings':json.loads(pairs[cid]['completion'])['findings']})
    diagnostics={}
    for split in ('test','ood'):
        cases=rows('heldout/'+split+'/cases.jsonl')
        for condition,shots in (('A',()),('B',examples)):
            count=[len(prompt_ids(tokenizer,diagnostic_prompt(c,shots))) for c in cases]
            diagnostics[split+'/'+condition]=lengths([n+1536 for n in count],17408)
            diagnostics[split+'/'+condition]['max_prompt_tokens']=max(count)
            diagnostics[split+'/'+condition]['reserved_new_tokens']=1536
    result={'kind':'actual_cpu_tokenizer_length_audit','status':'completed',
        'tokenizer_class':type(tokenizer).__name__,'transformers':transformers.__version__,'tokenizers':tokenizers.__version__,
        'original_revision_assets_verified':len(assets),'training':training,'diagnostics_prompt_plus_reserved_generation':diagnostics,
        'frozen_B_examples':len(examples),'model_weights_loaded':False,'heldout_gold_loaded':False,
        'model_calls':0,'gpu_training_or_generation_performed':False,
        'all_lengths_fit':all(r['over_limit']==0 for r in diagnostics.values()),
        'warning':'Actual token lengths only. Does not measure training/inference memory, throughput or model accuracy.'}
    if not result['all_lengths_fit']:result['status']='failed_context_limit'
    out.mkdir(parents=True,exist_ok=False)
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('selected','base','example-protocol','out'):p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--manifest-sha256',required=True);p.add_argument('--example-protocol-sha256',required=True);a=p.parse_args()
    r=build(a.selected,a.base,a.example_protocol,a.out,a.manifest_sha256,a.example_protocol_sha256)
    print(json.dumps(r));raise SystemExit(0 if r['status']=='completed' else 1)
