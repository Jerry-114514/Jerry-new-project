import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
sys.path.insert(0,str(Path.cwd()))
sys.path.insert(0,str(Path.cwd()/'tests'))
from intentlab.core import canonical
from intentlab.research_statistics import STRATIFIED_ANALYSIS_PLAN, analyze_records, paired_cluster_statistics
from test_research_statistics import inputs

old_commit='0b84448a3d586b27581015b95e57b0bcb45b8882'
raw=subprocess.check_output(['git','show',old_commit+':intentlab/research_statistics.py'])
path=Path('tmp/statistics-before-strata.py')
path.write_bytes(raw)
spec=importlib.util.spec_from_file_location('intentlab.pre_strata_statistics',path)
old=importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)
args=inputs()
before=old.analyze_records(*deepcopy(args))
after=analyze_records(*deepcopy(args))
assert canonical(before)==canonical(after)
left={'a1':[0],'a2':[0],'b1':[1],'b2':[1]}
right={'a1':[1],'a2':[1],'b1':[0],'b2':[0]}
ordinary=paired_cluster_statistics(left,right)
fixed=paired_cluster_statistics(left,right,strata={'a1':'A','a2':'A','b1':'B','b2':'B'})
v2=deepcopy(args)
v2[0]['spec']['statistics']['analysis_plan']=deepcopy(STRATIFIED_ANALYSIS_PLAN)
report=analyze_records(*v2)
result={'kind':'arithmetic_only_fixed_quota_statistics_demo','model_calls':0,
    'heldout_data_read':False,'legacy_v1_report_exactly_reproduced':True,
    'legacy_source_commit':old_commit,'legacy_source_sha256':hashlib.sha256(raw).hexdigest(),
    'current_statistics_sha256':hashlib.sha256(Path('intentlab/research_statistics.py').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
    'ordinary_arithmetic_case':ordinary,'fixed_quota_arithmetic_case':fixed,
    'full_v2_fixture':{'report_schema_version':report['schema_version'],'secondary_family_size':report['secondary_family_size'],
        'rq1_effect':report['comparisons']['RQ1/test']['right_minus_left'],
        'rq1_seed_sd':report['comparisons']['RQ1/test']['seed_effect_sample_sd'],
        'rq1_family_counts':report['comparisons']['RQ1/test']['bootstrap_stratification']['source_groups_per_stratum']},
    'plan':STRATIFIED_ANALYSIS_PLAN,'formal_protocol_frozen':False,
    'warning':'Arithmetic fixtures only. Fixed quota changes the resampling design, not observed point effects or experimental success. Conditional inferential assumptions remain unverified.'}
parser=argparse.ArgumentParser(description='Replay arithmetic-only v1 compatibility and v2 fixed-quota examples')
parser.add_argument('--out',type=Path,required=True)
out=parser.parse_args().out
out.mkdir(parents=True,exist_ok=False)
(out/'arithmetic-check.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
print(json.dumps({'legacy_v1_report_exact':True,'ordinary_interval':ordinary['percentile_95_interval'],
    'fixed_quota_interval':fixed['percentile_95_interval'],'both_point_effects':ordinary['right_minus_left']},indent=2))
