"""Development proxy sensitivity for the actual 10000-flip primary test."""
import hashlib,json,math,random,sys,time
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from intentlab.research_statistics import sign_flip_test

root=Path('runs/fewshot-completed-local-20261023/procedural-fewshot-development-20261023')
out=Path('runs/development-power-calibration-20261023');out.mkdir(mode=0o700,exist_ok=False)
start=time.perf_counter()
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def save(name,value):(out/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
save('status.json',{'status':'running'})
def vector_p(d,signs):
    d=np.asarray(d,dtype=np.float64);observed=abs(math.fsum(d.tolist()))
    tolerance=1e-12*max(1.,observed,math.fsum(np.abs(d).tolist()))
    extremes=np.count_nonzero(np.abs(np.einsum('ij,j->i',signs,d,dtype=np.float64,optimize=False))>=observed-tolerance)
    return (int(extremes)+1)/(len(signs)+1)
# Audit the same Python sign sequence and plus-one/tolerance semantics used by
# the production routine, before using NumPy RNG for the simulation itself.
d=[.125,-.25,.375,-.125]*5
r=random.Random(20261023)
signs=np.array([[1 if r.getrandbits(1) else -1 for _ in d] for _ in range(10000)],dtype=np.int8)
assert vector_p(d,signs)==sign_flip_test(d,20261023,10000)['p_value']
a=load(root/'scoring/A.json')['per_task_error_rate'];b=load(root/'scoring/B3.json')['per_task_error_rate']
assert set(a)==set(b) and len(a)==150
cases=[json.loads(l) for l in (root/'validation-cases.jsonl').read_text().splitlines()]
family={c['source_task_id']:c['family'] for c in cases}
assert set(family)==set(a)
diff={key:a[key]-b[key] for key in a}
groups={f:np.array([diff[key] for key in sorted(diff) if family[key]==f]) for f in sorted(set(family.values()))}
assert len(groups)==8
residual={f:np.abs(v-v.mean()) for f,v in groups.items()}
proxy_sd=float(np.std(list(diff.values()),ddof=1))
def wilson(k,n):
    z=1.959963984540054;p=k/n;den=1+z*z/n
    middle=(p+z*z/(2*n))/den;half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [middle-half,middle+half]
rng=np.random.default_rng(20261023)
cells=[];replicates=400;permutations=10000;n=200
for scenario in ['symmetrized_A_B3_proxy','twice_proxy_residual','symmetric_sd_0.3','symmetric_sd_0.5']:
    for delta in [0.,.025,.05,.075]:
        rejected=0
        for _ in range(replicates):
            if scenario.startswith('symmetric_sd_'):
                magnitude=np.full(n,float(scenario.rsplit('_',1)[1]))
            else:
                magnitude=np.concatenate([rng.choice(v,25,replace=True) for v in residual.values()])
                if scenario=='twice_proxy_residual':magnitude*=2
            d=delta+magnitude*(2*rng.integers(0,2,n,dtype=np.int8)-1)
            assert np.max(np.abs(d))<=1,'Do not clip bounded task effects'
            signs=2*rng.integers(0,2,(permutations,n),dtype=np.int8)-1
            rejected+=vector_p(d,signs)<=.05
        cells.append({'scenario':scenario,'true_absolute_mean_improvement':delta,
            'source_tasks':n,'source_tasks_per_family':25,'replicates':replicates,
            'sign_flips_per_replicate':permutations,'rejections':rejected,
            'rejection_rate':rejected/replicates,'simulation_wilson_95':wilson(rejected,replicates)})
        save('partial.json',cells)
        print(json.dumps(cells[-1]),flush=True)
summary={'kind':'development_proxy_calibration_not_D_B_power_guarantee','development_sources':150,
    'development_A_minus_B3_mean':float(np.mean(list(diff.values()))),'development_A_minus_B3_sd':proxy_sd,
    'source_groups_per_family':{f:len(v) for f,v in groups.items()},'planned_test_sources':200,
    'simulation_seed':20261023,'numpy_version':np.__version__,
    'production_test_semantics_audit_passed':True,'alpha':.05,'cells':cells,
    'input_sha256':{str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in [root/'scoring/A.json',root/'scoring/B3.json',root/'validation-cases.jsonl']},
    'driver_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    'heldout_model_outputs_read':False,'new_model_calls':0,'formal_protocol_frozen':False,
    'limitations':['A/B3 was selected on the same development observations; its effect and residual spread are optimistic proxies, not D/B measurements.',
    'Residual magnitudes are centered within family then independently symmetrized; this imposes the sign-exchangeable null rather than validating it for real tasks.',
    'Family quotas fixed at 25; blocked/fault quotas and near-neighbor dependence are not simulated.',
    'Conditional on fixed fitted models; does not estimate training-seed population uncertainty.',
    'Two-point stress scenarios vary SD under symmetric bounded differences; they are assumptions, not fitted natural-error distributions.',
    'Wilson intervals quantify finite simulation error only, not uncertainty in the real experimental power.',
    'Calibration concerns the primary unadjusted sign-flip test, not CI coverage or Holm secondary power.'],
    'seconds':time.perf_counter()-start}
save('summary.json',summary);save('status.json',{'status':'completed','cells':len(cells)})
