"""Supplementary synthetic capacity measurement, never a formal-task rerun.

Uses the frozen BF16 shared-role backend and budget caps. EOS stopping is
disabled only in this process to exercise the full allowed generation length.
Original M6/M7 peaks remain missing; these measurements must not backfill them.
"""
import argparse
import gc
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import time

from verify_restored_inference import completed_statistics, digest, read, sha


def public_prompt(tokenizer, token_ids, target):
    prefix='Synthetic resource measurement. Continue writing the word count separated by spaces.\n'
    low,high=0,target
    while low<high:
        middle=(low+high+1)//2
        if len(token_ids(tokenizer,prefix+' count'*middle))<=target:low=middle
        else:high=middle-1
    prompt=prefix+' count'*low
    count=len(token_ids(tokenizer,prompt))
    if not target-2<=count<=target:
        raise ValueError('Synthetic prompt could not match the declared token shape')
    return prompt,count


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('source','protocol','binding','statistics-status','budget-config','budget-status','out'):
        p.add_argument('--'+name,type=Path,required=True)
    for name in ('source-commit','protocol-hash','binding-hash','statistics-status-sha256','budget-config-sha256'):
        p.add_argument('--'+name,required=True)
    a=p.parse_args()
    if a.out.exists() or a.out.resolve().is_relative_to(a.source.resolve()):
        raise ValueError('Use a fresh output directory outside frozen source')
    if subprocess.check_output(['git','-C',str(a.source),'rev-parse','HEAD'],text=True).strip()!=a.source_commit \
            or subprocess.check_output(['git','-C',str(a.source),'status','--porcelain']):
        raise ValueError('Frozen source must be clean and unchanged')
    sys.path.insert(0,str(a.source.resolve()))
    from intentlab.gpu_lease import ensure_gpu_lease,process_identity
    from intentlab.prompts import prompt_ids
    from intentlab.shared_role_backend import SharedRoleBackend,compatible_base_adapter
    stats=completed_statistics(a.statistics_status,a.statistics_status_sha256,process_identity)
    protocol,binding=read(a.protocol),read(a.binding)
    if protocol['lock_hash']!=a.protocol_hash or digest({k:v for k,v in protocol.items() if k!='lock_hash'})!=a.protocol_hash \
            or binding['binding_hash']!=a.binding_hash or digest({k:v for k,v in binding.items() if k!='binding_hash'})!=a.binding_hash \
            or binding['training_protocol_hash']!=a.protocol_hash or stats['protocol_hash']!=a.protocol_hash \
            or stats['runtime_commit']!=a.source_commit:
        raise ValueError('Protocol/model/statistics binding mismatch')
    environment=protocol['environment']
    if platform.python_version()!=environment['python'] or any(importlib.metadata.version(n)!=v for n,v in environment['packages'].items()):
        raise ValueError('Frozen runtime packages changed')
    budgets=protocol['spec']['budgets']
    if budgets!={'context_limit':17408,'max_new_tokens':1536,'max_repairs':3,'token_budget':49152}:
        raise ValueError('Unexpected frozen resource caps')
    settings=protocol['spec']['execution']['settings']
    if settings['model_residency']!='shared-condition-v1' or settings['analyzer_condition']!='D' or settings['analyzer_seed']!=0:
        raise ValueError('Expected the original registered role residency and analyzer')
    paths={r:binding['models'][r]['path'] for r in ('actor','analyzer')}
    if not compatible_base_adapter(paths):raise ValueError('Bound models no longer support shared residency')
    if any(a.out.resolve().is_relative_to(Path(path).resolve()) for path in paths.values()):
        raise ValueError('Output must be outside model assets')
    def budget():
        guard=read(a.budget_status);actual=process_identity(guard['pid'])
        if sha(a.budget_config)!=a.budget_config_sha256 or guard['config_sha256']!=a.budget_config_sha256 \
                or guard['status']!='monitoring' or actual.get('start_ticks')!=guard['start_ticks'] \
                or not 0<=time.time()-guard['unix']<120 or guard['remaining_operating_seconds']<3600:
            raise ValueError('Unchanged live budget guard with sufficient time required')
    budget()
    # Verify bytes of both actual role snapshots without reading task or gold files.
    for role,snapshot in binding['models'].items():
        if role not in paths:continue
        for name,expected in snapshot['files_sha256'].items():
            if sha(Path(snapshot['path'])/name)!=expected:raise ValueError('Bound role asset changed')
    budget();ensure_gpu_lease()
    import torch
    torch.set_num_threads(2);torch.manual_seed(0)
    if not torch.cuda.is_available() or '5090' not in torch.cuda.get_device_name(0):
        raise ValueError('Original RTX 5090 required')
    a.out.mkdir(parents=True,exist_ok=False)
    state={'kind':'supplementary_public_synthetic_inference_capacity','status':'running','pid':__import__('os').getpid(),
        'source_commit':a.source_commit,'protocol_hash':a.protocol_hash,'binding_hash':a.binding_hash,
        'driver_sha256':sha(__file__),'device':torch.cuda.get_device_name(0),
        'device_total_bytes':torch.cuda.get_device_properties(0).total_memory,
        'inference_dtype':'bfloat16','quantization':None,'residency':'shared-condition-v1',
        'test_or_gold_files_opened':False,'formal_experiment_restarted':False,
        'formal_peak_memory_backfilled':False,'model_or_controller_selected':False,
        'decode_override':'EOS disabled; min_new_tokens=max_new_tokens for synthetic full-budget stress only',
        'cases':[],'m8_complete':False}
    def save():
        temp=a.out/'status.pending.json';temp.write_text(json.dumps(state,indent=2)+'\n',encoding='utf-8');temp.replace(a.out/'status.json')
    save();backend=None;started=time.perf_counter()
    try:
        backend=SharedRoleBackend(paths,device='cuda',max_new_tokens=256,
            token_budget=budgets['token_budget'],context_limit=budgets['context_limit'])
        backend.role_eos={'actor':[],'analyzer':[]}
        backend.model.generation_config.max_time=900
        shapes=[('short',1024,256),('full_budget',budgets['context_limit']-budgets['max_new_tokens'],budgets['max_new_tokens'])]
        for label,target,new_tokens in shapes:
            for role in ('actor','analyzer'):
                budget();ensure_gpu_lease()
                prompt,length=public_prompt(backend.role_tokenizers[role],prompt_ids,target)
                backend.max_new_tokens=new_tokens
                backend.model.generation_config.min_new_tokens=new_tokens
                state['active_case']={'shape':label,'role':role,'prompt_tokens':length,'requested_new_tokens':new_tokens};save()
                torch.cuda.synchronize();torch.cuda.reset_peak_memory_stats()
                baseline={'allocated_bytes':torch.cuda.memory_allocated(),'reserved_bytes':torch.cuda.memory_reserved()}
                start=time.perf_counter();response=backend.complete(prompt,role=role);torch.cuda.synchronize()
                elapsed=time.perf_counter()-start
                free,total=torch.cuda.mem_get_info()
                row={'shape':label,'role':role,'prompt_tokens':length,'requested_new_tokens':new_tokens,
                    'actual_new_tokens':response['usage']['completion_tokens'],'seconds':elapsed,
                    'baseline':baseline,'peak_allocated_bytes':torch.cuda.max_memory_allocated(),
                    'peak_reserved_bytes':torch.cuda.max_memory_reserved(),'device_used_bytes_after':total-free,
                    'output_text_retained':False}
                state['cases'].append(row);save();del response
                if row['actual_new_tokens']!=new_tokens:raise ValueError('Synthetic case stopped before its full requested budget')
                ensure_gpu_lease();budget()
                print(json.dumps({'case_complete':label,'role':role,'prompt_tokens':length,'new_tokens':new_tokens}),flush=True)
        state.update(status='completed',seconds_including_loading=time.perf_counter()-started,
            limitations=['Synthetic resource measurement, not formal M6/M7 historical peaks or task quality.',
                'EOS/min-length stress override differs from formal natural stopping.',
                'Allocator reservation carries over sequential calls; allocated and reserved are not added.',
                'Device-used sample after a call is not a device-wide peak.'])
        save()
    except BaseException as exc:
        state.update(status='failed',error_type=type(exc).__name__,error=str(exc));save();raise
    finally:
        if backend is not None:backend.close()
        gc.collect();torch.cuda.empty_cache()


if __name__=='__main__':main()
