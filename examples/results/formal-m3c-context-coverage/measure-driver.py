"""Tokenize public development prompts without model weights or labels."""
import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import runpy
import subprocess
import sys


def measure(source, model, out):
    sys.path.insert(0, str(source))
    from intentlab.core import digest
    from intentlab.formal_data import read_jsonl, formal_prompt
    from intentlab.formal_inference import diagnostic_prompt
    from intentlab.protocol import source_snapshot
    from transformers import AutoTokenizer

    assert not subprocess.check_output(['git','-C',str(source),'status','--porcelain'])
    assert subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD']).decode().strip() == 'c28173490b646a37927aadcdab841a517f56a9b0'
    official = json.loads((source / 'configs/qwen35-official-assets.json').read_text(encoding='utf-8'))
    wanted = {'config.json','tokenizer.json','tokenizer_config.json','chat_template.jinja','merges.txt','vocab.json'}
    assets = {}
    for row in official['assets']:
        if row['path'] not in wanted: continue
        raw = (model / row['path']).read_bytes()
        actual = hashlib.sha256(raw).hexdigest() if 'sha256' in row else hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
        assert actual == row.get('sha256',row.get('git_blob_sha1'))
        assets[row['path']] = hashlib.sha256(raw).hexdigest()
    assert set(assets) == wanted
    adapted = Path('/root/autodl-tmp/wikisql-adapter-validation-20261023/source/runs/private-adaptation-v1')
    natural = Path('/root/autodl-tmp/wikisql-natural-collection-20261023/private-export')
    batches = {'legacy-development':read_jsonl(source/'examples/results/formal-m2b-source-triage/triage/coordinator-cases.jsonl'),
        'wikisql-injected':read_jsonl(adapted/'cases.jsonl'),
        'wikisql-natural':read_jsonl(natural/'first-two/intake/coordinator-cases.jsonl')+read_jsonl(natural/'remaining-ten/intake/coordinator-cases.jsonl')}
    cases = [c for rows in batches.values() for c in rows]
    assert len(cases) == len({c['case_id'] for c in cases}) == 104
    expected = json.loads((source/'examples/results/formal-m2f-source-coverage/summary.json').read_text())
    assert {k:digest(sorted(v,key=lambda c:c['case_id'])) for k,v in batches.items()} == expected['batch_case_hashes']
    assert all(diagnostic_prompt(c) == formal_prompt(c['public']) for c in cases)
    tokenizer = AutoTokenizer.from_pretrained(model,local_files_only=True,trust_remote_code=False)
    probe = runpy.run_path(str(source/'examples/results/formal-m3a-context-probe/context_probe.py'))
    reports = {str(n):probe['lengths'](tokenizer,cases,context=n,maximum=512,budget=8192) for n in (2048,3072,4096)}
    membership = {c['case_id']:batch for batch,rows in batches.items() for c in rows}
    by_batch = {}
    for batch in batches:
        subset = [r for r in reports['2048']['rows'] if membership[r['case_id']] == batch]
        by_batch[batch] = {'views':len(subset),'minimum_prompt_tokens':min(r['prompt_tokens'] for r in subset),
            'maximum_prompt_tokens':max(r['prompt_tokens'] for r in subset),
            'cannot_reserve_512_by_context':{n:sum(not r['full_generation_reservation_fits'] for r in report['rows'] if membership[r['case_id']]==batch) for n,report in reports.items()}}
    summary = {'scope':'development_zero_shot_prompt_lengths_only','views':104,'batches':by_batch,
        'minimum_prompt_tokens':reports['2048']['min_prompt_tokens'],'maximum_prompt_tokens':reports['2048']['max_prompt_tokens'],
        'cannot_reserve_512_by_context':{n:r['cannot_reserve_full_generation'] for n,r in reports.items()},
        'cannot_generate_by_context':{n:r['cannot_generate'] for n,r in reports.items()},
        'human_labels_read':False,'fewshot_audited':False,'reviewed_SFT_target_lengths_audited':False,
        'training_memory_measured':False,'formal_budget_approved':False,'formal_training_started':False,
        'warning':'Prompt plus 512 generation allowance is an inference feasibility measurement, not a guarantee of SFT target fit, few-shot context, training memory or formal budget approval. No prompt truncation.'}
    out.mkdir(exist_ok=False)
    for name,data in [('lengths-by-context.json',reports),('summary.json',summary),('case-batches.json',membership),
        ('runtime-identity.json',{'source_commit':'c28173490b646a37927aadcdab841a517f56a9b0','source_normalized_sha256':source_snapshot(source),
        'python':platform.python_version(),'packages':{n:importlib.metadata.version(n) for n in ('transformers','tokenizers')},
        'official_model':official['model'],'official_revision':official['revision'],'tokenizer_files_sha256':assets,
        'probe_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'model_weights_loaded':False,'gpu_used':False})]:
        (out/name).write_text(json.dumps(data,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(summary,indent=2),flush=True)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,required=True)
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    measure(args.source,args.model,args.out)
