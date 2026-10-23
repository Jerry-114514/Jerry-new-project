"""Coordinator-side material seal; training verifies metadata without gold I/O."""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path

from .core import digest
from .formal_data import read_jsonl, validate_cases, validate_findings


POLICY = {'generation_attempts_per_protocol':1,'gold_access':'separate_reveal_after_all_predictions',
          'training_inputs':['train.jsonl','validation.jsonl'],'os_access_isolation_claim':False}


def normalized_spec(spec):
    result=deepcopy(spec)
    result['source_root']=str(Path(result['source_root']).resolve())
    for group in ['dataset','models','evidence']:
        result[group]={k:str(Path(v).resolve()) if v is not None else None for k,v in result[group].items()}
    for key in ['tasks','references']:
        result['execution'][key]=str(Path(result['execution'][key]).resolve())
    return result


def input_paths(spec):
    spec=normalized_spec(spec)
    paths={'annotation/'+key:spec['dataset'][key] for key in ['cases','labels','tasks','references']}
    for split in ['test','ood']:
        for name in ['cases.jsonl','gold.jsonl']:
            relative=f'heldout/{split}/{name}'
            paths['dataset/'+relative]=str(Path(spec['dataset']['export'])/relative)
    paths.update({'execution/'+key:spec['execution'][key] for key in ['tasks','references']})
    return paths


def fingerprints(spec):
    from .protocol import file_hash
    return {k:{'path':p,'sha256':file_hash(p)} for k,p in input_paths(spec).items()}


def validate_test_seal(spec, cases):
    from .programmatic_protocol import SCOPE
    from .protocol import file_hash
    path=Path(spec['evidence']['test_sealing'])
    before=file_hash(path)
    seal=json.loads(path.read_text(encoding='utf-8'))
    expected={'kind','schema_version','scope','candidate_spec_hash','files','heldout_case_counts',
              'policy','created_utc','known_claims_at_creation','warning'}
    counts=dict(Counter(c['split'] for c in cases if c['split'] in ['test','ood']))
    if spec.get('schema_version')!=3 or spec.get('label_scope')!=SCOPE:
        raise ValueError('Material seal requires explicit programmatic scope')
    if set(seal)!=expected or seal['kind']!='programmatic_test_material_seal' or type(seal['schema_version']) is not int or seal['schema_version']!=1 \
            or seal['scope']!=spec['scope'] or seal['candidate_spec_hash']!=digest(normalized_spec(spec)) \
            or seal['policy']!=POLICY or seal['known_claims_at_creation']!=[] \
            or seal['heldout_case_counts']!=counts or set(counts)!={'test','ood'} \
            or not isinstance(seal['created_utc'],str) or not seal['created_utc']:
        raise ValueError('Material seal schema, candidate, policy or coverage differs')
    if seal['files']!=fingerprints(spec):
        raise ValueError('Sealed test material content changed')
    if file_hash(path)!=before:
        raise ValueError('Material seal changed during verification')
    return {'kind':'validated_programmatic_test_material_seal','schema_version':1,
            'seal_sha256':before,'candidate_spec_hash':seal['candidate_spec_hash'],
            'files':deepcopy(seal['files']),'heldout_case_counts':counts,'policy':deepcopy(POLICY)}


def create_test_seal(spec, out):
    from .programmatic_protocol import SCOPE
    if spec.get('schema_version')!=3 or spec.get('label_scope')!=SCOPE:
        raise ValueError('Material seal requires explicit programmatic scope')
    out=Path(out).resolve()
    if out!=Path(spec['evidence']['test_sealing']).resolve():
        raise ValueError('Seal output must equal the candidate evidence path')
    if out.exists():raise FileExistsError('Do not overwrite an existing material seal')
    root=Path(spec['dataset']['export'])
    if list(root.parent.glob('diagnostic-*.claim.json')):
        raise ValueError('Existing inference/reveal claim requires investigation, not a fresh seal')
    cases=read_jsonl(spec['dataset']['cases']);validate_cases(cases)
    counts={}
    for split in ['test','ood']:
        expected=[c for c in cases if c['split']==split]
        public=read_jsonl(root/f'heldout/{split}/cases.jsonl')
        gold=read_jsonl(root/f'heldout/{split}/gold.jsonl')
        if not expected or public!=expected or [r.get('case_id') for r in gold]!=[c['case_id'] for c in expected]:
            raise ValueError('Seal requires complete ordered public/gold case coverage')
        for case,label in zip(public,gold):
            if set(label)!={'case_id','findings'}:raise ValueError('Unexpected heldout gold payload')
            validate_findings(label['findings'],case['public'])
        counts[split]=len(expected)
    seal={'kind':'programmatic_test_material_seal','schema_version':1,'scope':spec['scope'],
          'candidate_spec_hash':digest(normalized_spec(spec)),'files':fingerprints(spec),
          'heldout_case_counts':counts,'policy':deepcopy(POLICY),
          'created_utc':datetime.now(timezone.utc).isoformat(),'known_claims_at_creation':[],
          'warning':'Application input separation and content hashes only. Same-root access is not OS isolation; local clock and empty known claim set are not independent proof that nobody previously inspected material.'}
    out.parent.mkdir(parents=True,exist_ok=True)
    with out.open('x',encoding='utf-8',newline='\n') as f:json.dump(seal,f,indent=2);f.write('\n')
    return validate_test_seal(spec,cases)


def validate_test_seal_binding(lock):
    """Metadata only: never open annotations, reference files, gold or seal."""
    binding=lock.get('test_seal_binding')
    expected_keys={'kind','schema_version','seal_sha256','candidate_spec_hash','files','heldout_case_counts','policy'}
    if not isinstance(binding,dict) or set(binding)!=expected_keys \
            or binding['kind']!='validated_programmatic_test_material_seal' \
            or type(binding['schema_version']) is not int or binding['schema_version']!=1 \
            or binding['seal_sha256']!=lock['evidence']['test_sealing']['sha256'] \
            or binding['candidate_spec_hash']!=digest(normalized_spec(lock['spec'])) or binding['policy']!=POLICY:
        raise ValueError('Frozen test material seal binding missing or changed')
    records={'annotation/'+key:lock['annotation_inputs'][key] for key in ['cases','labels','tasks','references']}
    for split in ['test','ood']:
        for name in ['cases.jsonl','gold.jsonl']:
            relative=f'heldout/{split}/{name}'
            records['dataset/'+relative]={'path':str(Path(lock['dataset_export']['root'])/relative),
                'sha256':lock['dataset_export']['files_sha256'][relative]}
    records.update({'execution/'+key:lock['execution_binding']['files'][key] for key in ['tasks','references']})
    if binding['files']!=records or set(binding['heldout_case_counts'])!={'test','ood'} or any(
            type(n) is not int or n<lock['spec']['minimum_tasks'][s] for s,n in binding['heldout_case_counts'].items()):
        raise ValueError('Frozen seal inputs or heldout coverage differ from the protocol')
    return True


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--spec',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();result=create_test_seal(json.loads(args.spec.read_text(encoding='utf-8')),args.out)
    print(json.dumps({'sealed_material':True,'formal_protocol_frozen':False,'heldout_case_counts':result['heldout_case_counts']}))
