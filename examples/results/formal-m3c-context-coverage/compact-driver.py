"""Offline-only prompt-format proposal; no model inference or trainer change."""
import json
from pathlib import Path
import sys


def compact_prompt(public):
    from intentlab.core import canonical
    from intentlab.formal_data import evidence_catalog, formal_prompt, output_schema
    original = formal_prompt(public)
    prefix = original.split('\n', 1)[0] + '\n'
    payload = {'public':public,'evidence_catalog':dict.fromkeys(evidence_catalog(public)),
        'evidence_lookup':'Catalog values are omitted duplicates: request refers to public.request; input:<path> to public.inputs[path]; file:<path> to public.observation.files[path]; event:<index> to public.observation.events[index]; snapshot_paths is the complete sorted keys of public.observation.files.',
        'output_schema':output_schema(public['requirements'])}
    rebuilt = {}
    for ref in payload['evidence_catalog']:
        if ref == 'request': value=public['request']
        elif ref == 'snapshot_paths': value=sorted(public['observation']['files'])
        elif ref.startswith('input:'): value=public['inputs'][ref[len('input:'):]]
        elif ref.startswith('file:'): value=public['observation']['files'][ref[len('file:'):]]
        elif ref.startswith('event:'): value=public['observation']['events'][int(ref[len('event:'):])]
        else: raise ValueError('Unrecognized reference')
        rebuilt[ref]=value
    assert canonical(rebuilt)==canonical(evidence_catalog(public))
    encoded=canonical(payload)
    decoded=json.loads(encoded)
    assert canonical(decoded['public'])==canonical(public)
    assert decoded['output_schema']==output_schema(public['requirements'])
    return prefix+encoded+'\nJSON:\n'


if __name__=='__main__':
    source=Path('/root/autodl-tmp/Jerry-formal-v2-20261022')
    sys.path.insert(0,str(source))
    from intentlab.core import digest
    from intentlab.formal_data import read_jsonl
    from intentlab.prompts import prompt_ids
    from transformers import AutoTokenizer
    tokenizer=AutoTokenizer.from_pretrained('/root/autodl-tmp/models/Qwen3.5-9B',local_files_only=True,trust_remote_code=False)
    adapted=Path('/root/autodl-tmp/wikisql-adapter-validation-20261023/source/runs/private-adaptation-v1')
    natural=Path('/root/autodl-tmp/wikisql-natural-collection-20261023/private-export')
    cases=read_jsonl(source/'examples/results/formal-m2b-source-triage/triage/coordinator-cases.jsonl')+read_jsonl(adapted/'cases.jsonl')+read_jsonl(natural/'first-two/intake/coordinator-cases.jsonl')+read_jsonl(natural/'remaining-ten/intake/coordinator-cases.jsonl')
    rows=[]
    for case in cases:
        prompt=compact_prompt(case['public']);n=len(prompt_ids(tokenizer,prompt))
        rows.append({'case_id':case['case_id'],'prompt_hash':digest(prompt),'prompt_tokens':n})
    result={'scope':'offline_compact_catalog_format_proposal_only','cases_hash':digest(cases),'rows':rows,
        'minimum_prompt_tokens':min(r['prompt_tokens'] for r in rows),'maximum_prompt_tokens':max(r['prompt_tokens'] for r in rows),
        'cannot_reserve_512_by_context':{str(n):sum(r['prompt_tokens']+512>n for r in rows) for n in (2048,3072,4096)},
        'public_payload_and_schema_unchanged':True,'all_original_catalog_values_reconstructable':True,
        'core_prompt_changed':False,'inference_performed':False,'semantic_equivalence_for_model_verified':False,
        'formal_budget_approved':False,'warning':'Deterministic data preservation does not prove unchanged model behavior. Proposed format must be uniformly registered, human-reviewed and compared on development data before formal use.'}
    out=Path('/root/autodl-tmp/context-coverage-20261023/compact-trial.json')
    with out.open('x') as handle:handle.write(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))
