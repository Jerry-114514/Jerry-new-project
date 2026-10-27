"""Exploratory only: reconstruct the exact pre-evaluation input masks first."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import sys
import argparse
import tarfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

def analyze(scientific,scientific_sha,scoring,scoring_sha,out):
    if not __debug__:
        raise RuntimeError('Integrity assertions require Python without -O')
    driver=ROOT/'examples/results/formal-m2n-matched-similarity/audit-driver.py'
    assert hashlib.sha256(driver.read_text().encode()).hexdigest()==json.loads((driver.parent/'summary.json').read_text())['driver_sha256']
    namespace={'__file__':str(driver),'__name__':'frozen_input_similarity_helpers'}
    exec(compile(driver.read_text().split('def main():')[0],str(driver),'exec'),namespace)
    normalize,distance=namespace['normalize'],namespace['distance']
    expected=json.loads((ROOT/'examples/results/formal-m2n-matched-similarity/overlap-summary.json').read_text())
    archive=Path(scientific)
    with archive.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==scientific_sha
    with tarfile.open(archive) as a:
        raw=a.extractfile('dataset/tasks.jsonl').read()
        assert hashlib.sha256(raw).hexdigest()==json.loads((driver.parent/'summary.json').read_text())['input_tasks_sha256']
        tasks=[json.loads(line) for line in raw.splitlines()]
    groups=defaultdict(list)
    for task in tasks:
        operation,tokens=normalize(task);groups[(task['family'],operation)].append((task,tokens))
    exact,near,dev_near=set(),set(),set();counts={'test_train_near_pairs':0,'test_train_exact_pairs':0,'test_validation_near_pairs':0}
    for group in groups.values():
        for i,(a,x) in enumerate(group):
            for b,y in group[i+1:]:
                pair={a['split'],b['split']}
                if 'test' not in pair or pair not in ({'test','train'},{'test','validation'}):continue
                d=distance(x,y)
                if d/max(len(x),len(y),1)>0.25:continue
                tid=a['id'] if a['split']=='test' else b['id']
                dev_near.add(tid)
                if 'train' in pair:
                    near.add(tid);counts['test_train_near_pairs']+=1
                    if d==0:exact.add(tid);counts['test_train_exact_pairs']+=1
                else:counts['test_validation_near_pairs']+=1
    all_test={t['id'] for t in tasks if t['split']=='test'}
    masks={'all_test':sorted(all_test),'normalized_exact_train_overlap':sorted(exact),
        'within_25pct_train_overlap':sorted(near),'no_normalized_exact_train_overlap':sorted(all_test-exact),
        'no_within_25pct_development_overlap':sorted(all_test-dev_near)}
    mask_raw=(json.dumps(masks,indent=2,sort_keys=True)+'\n').encode()
    assert hashlib.sha256(mask_raw).hexdigest()==expected['private_strata_sha256']
    assert {k:len(v) for k,v in masks.items()}==expected['stratum_source_counts']
    assert all(v==expected[k] for k,v in counts.items())
    # Only after binding masks to their pre-test commitment do we decode outcomes.
    path=Path(scoring)
    with path.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==scoring_sha
    with tarfile.open(path) as a:scores=json.load(a.extractfile('scores.json'))
    results={}
    for name,ids in masks.items():
        per={c:statistics.mean(g['test']['per_task_error_rate'][tid] for tid in ids) for c,g in scores.items()}
        dm=statistics.mean(per[f'D-seed-{i}'] for i in range(3));em=statistics.mean(per[f'E-seed-{i}'] for i in range(3))
        results[name]={'source_task_count':len(ids),'per_condition_error_rate':per,
                      'D_seed_mean':dm,'E_seed_mean':em,'D_minus_B':dm-per['B']}
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    report={'kind':'postformal_exploratory_fixed_input_strata','pre_evaluation_masks_exactly_reconstructed':True,
        'mask_defined_before_outcomes':True,'analysis_registered_before_outcomes':False,
        'results':results,'new_p_values_or_confidence_intervals':False,'primary_population_modified':False,
        'model_called':False,'source_independence_proven':False,
        'warning':'Descriptive post-test analysis, not a replacement for all 200 primary sources or proof of no semantic overlap.'}
    (out/'aggregate-results.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8',newline='\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('scientific','scoring'):
        p.add_argument('--'+n+'-archive',type=Path,required=True)
        p.add_argument('--'+n+'-sha256',required=True)
    p.add_argument('--out',type=Path,required=True)
    a=p.parse_args()
    print(json.dumps(analyze(a.scientific_archive,a.scientific_sha256,a.scoring_archive,a.scoring_sha256,a.out)))
