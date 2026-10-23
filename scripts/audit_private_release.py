"""Read-only audit of known private markers in a committed Git snapshot."""
import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile


PATTERNS={
    'private_seed':re.compile(rb'[0-9a-f]{64}'),
    'heldout_source_id':re.compile(rb'proc-v1-[0-9a-f]{24}'),
    'heldout_input_identity':re.compile(rb'[0-9a-f]{12}-[0-9]+-[0-9]+')}


def scan(members, needles):
    hits={key:{} for key in PATTERNS}
    count=total=0
    private_paths=[]
    weight_paths=[]
    names=set()
    for name,content in members:
        count+=1
        total+=len(content)
        names.add(name)
        data=name.encode()+b'\n'+content
        safe_name=name.encode()
        for key,pattern in PATTERNS.items():
            safe_name=pattern.sub(lambda match:b'[redacted]' if match.group() in needles[key] else match.group(),safe_name)
        safe_name=safe_name.decode('utf-8',errors='replace')
        if name.split('/')[0] in {'runs','tmp','checkpoints'}:
            private_paths.append(safe_name)
        if Path(name).suffix in {'.safetensors','.pt','.bin'}:
            weight_paths.append(safe_name)
        for key,pattern in PATTERNS.items():
            matched=set(pattern.findall(data)) & needles[key]
            if matched:
                hits[key][safe_name]=len(matched)
    return {'tracked_files':count,'tracked_bytes_scanned':total,
        'known_literal_marker_hits':hits,'private_root_paths_tracked':private_paths,
        'weight_suffix_paths_tracked':weight_paths,
        'root_license_file_present':bool(names & {'LICENSE','LICENSE.md','LICENSE.txt','COPYING'}),
        'no_known_private_marker_exposure':not any(hits.values()) and not private_paths}


def main(args):
    repo=args.repo.resolve()
    head=subprocess.check_output(['git','-C',str(repo),'rev-parse',args.commit],text=True).strip()
    def committed_json(path):
        return json.loads(subprocess.check_output(['git','-C',str(repo),'show',head+':'+path]))
    expected_base=committed_json('examples/results/formal-m2j-procedural-candidates/private-file-sha256.json')
    expected_matched=committed_json('examples/results/formal-m2m-matched-test/private-file-sha256-local.json')
    seed_base=committed_json('examples/results/formal-m2j-procedural-candidates/summary.json')['seed_commitments']
    seed_matched=committed_json('examples/results/formal-m2m-matched-test/summary.json')['seed_commitment']
    # Explicit private inputs are dataset seeds/public contracts, not SSH keys,
    # private gold or current predictions. Existing public Git blobs are scanned
    # as bytes, including any historical public result files.
    seeds=json.loads(args.base_seeds.read_text(encoding='utf-8'))
    fresh=json.loads(args.matched_seed.read_text(encoding='utf-8'))['seed']
    private_seeds=set(seeds.values())|{fresh}
    if len(private_seeds)!=5 or any(not re.fullmatch('[0-9a-f]{64}',seed) for seed in private_seeds):
        raise ValueError('Expected five distinct research split seeds')
    if {key:hashlib.sha256(bytes.fromhex(value)).hexdigest() for key,value in seeds.items()}!=seed_base \
            or hashlib.sha256(bytes.fromhex(fresh)).hexdigest()!=seed_matched:
        raise ValueError('Private seeds differ from committed research seed commitments')
    roots=[args.base,args.matched]
    tasks_by_id={}
    fingerprints={}
    provenance={}
    for root in roots:
        raw=(root/'tasks.jsonl').read_bytes()
        fingerprints[root.name]=hashlib.sha256(raw).hexdigest()
        expected=expected_base if root==args.base else expected_matched
        if fingerprints[root.name]!=expected['tasks.jsonl']:
            raise ValueError('Private public-contract file differs from committed identity')
        tasks=[json.loads(line) for line in raw.decode().splitlines()]
        provenance[root.name]={'origins':dict(Counter(t['source']['origin'] for t in tasks)),
            'declared_data_licenses':dict(Counter(t['source']['license'] for t in tasks))}
        for task in tasks:
            if task['split'] in {'test','ood'}:
                if task['id'] in tasks_by_id and tasks_by_id[task['id']]!=task:
                    raise ValueError('Shared heldout identity has conflicting contracts')
                tasks_by_id[task['id']]=task
    if len(tasks_by_id)!=500:
        raise ValueError('Expected 200 archived structural, 200 matched and 100 shared OOD sources')
    identities={row['rid'].encode() for task in tasks_by_id.values() for rows in task['inputs'].values()
                for row in rows if 'rid' in row}
    needles={'private_seed':{s.encode() for s in private_seeds},
             'heldout_source_id':{tid.encode() for tid in tasks_by_id},'heldout_input_identity':identities}
    archive=subprocess.check_output(['git','-C',str(repo),'archive',head])
    with tarfile.open(fileobj=io.BytesIO(archive),mode='r:') as handle:
        result=scan(((member.name,handle.extractfile(member).read()) for member in handle if member.isfile()),needles)
    allowed={
        'examples/results/neural-smoke/cosine/model/model.safetensors':'config.json',
        'examples/results/neural-smoke/plateau/model/model.safetensors':'config.json',
        'examples/results/neural-smoke/lora/model/adapter_model.safetensors':'tiny_base_recipe.json'}
    weight_review=[]
    for path in result['weight_suffix_paths_tracked']:
        if path not in allowed:
            weight_review.append({'path':path,'reviewed_tiny_fixture':False})
            continue
        config=committed_json(str(Path(path).parent/allowed[path]).replace('\\','/'))
        config=config.get('config',config)
        tiny=config.get('model_type')=='gpt2' and config.get('n_layer')==2 and config.get('n_embd')==48 and config.get('vocab_size')==768
        weight_review.append({'path':path,'reviewed_tiny_fixture':tiny,
                             'model_type':config.get('model_type'),'n_layer':config.get('n_layer'),'n_embd':config.get('n_embd')})
    result.update(kind='observed_private_release_boundary_audit',commit=head,
        private_seed_count=5,heldout_source_count=len(tasks_by_id),heldout_input_identity_count=len(identities),
        private_task_file_sha256=fingerprints,declared_provenance=provenance,
        committed_data_and_seed_bindings_verified=True,weight_review=weight_review,
        no_unreviewed_weight_suffix_paths=all(r['reviewed_tiny_fixture'] for r in weight_review),
        private_gold_files_read=False,private_model_outputs_read=False,
        public_git_blobs_scanned_as_bytes=True,human_review_claim=False,
        formal_protocol_frozen=False,legal_license_review_claim=False,
        limitations=['Literal known markers only; not a proof against encoded, fragmented or unidentified content exposure.',
            'Declared generated origin is cross-checked with task metadata, not independent legal certification.',
            'A public code snapshot audit does not prove access isolation of private filesystem files.',
            'No new code/data/weight license is granted by this report. No model endpoint is approved.'])
    args.out.mkdir(parents=True,exist_ok=False)
    (args.out/'summary.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:result[k] for k in ['commit','tracked_files','no_known_private_marker_exposure','root_license_file_present']},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,default=Path('.'))
    parser.add_argument('--commit',default='HEAD')
    for name in ('base','matched','base-seeds','matched-seed','out'):
        parser.add_argument('--'+name,type=Path,required=True)
    main(parser.parse_args())
