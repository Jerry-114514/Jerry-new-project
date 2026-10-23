"""One-shot development length, full-validation cost and resume probe."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time


def profile(values):
    values=sorted(values)
    return {'count':len(values),'minimum':values[0],'maximum':values[-1],
            'p50':values[(len(values)-1)//2],'p95':values[(len(values)-1)*95//100],'sum':sum(values)}


def pressure_ids(lengths):
    ordered=sorted(lengths,key=lambda row:(row['total_tokens'],row['case_id']))
    if len(ordered)<2 or len({r['case_id'] for r in ordered})!=len(ordered):
        raise ValueError('At least two unique training cases required')
    return [ordered[(len(ordered)-1)//2]['case_id'],ordered[-1]['case_id']]


def main(args):
    root=args.out.resolve()
    source=args.source.resolve()
    root.mkdir(mode=0o700,parents=True,exist_ok=False)
    record={'scope':'development_resource_probe_not_formal_training','status':'running',
            'phase':'preflight','dependency_pid':args.dependency_pid,'formal_training':False,
            'heldout_files_read':False,'started_unix':time.time()}
    def save(name,value):
        (root/name).write_text(json.dumps(value,indent=2,sort_keys=True)+'\n',encoding='utf-8',newline='\n')
    def update(**values):
        record.update(values)
        save('status.json',record)
    def source_check():
        head=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
        if head!='b4a757afc7c01332734fb6e4c2f08f3f7fcceef9' or subprocess.check_output(['git','-C',str(source),'status','--porcelain']):
            raise RuntimeError('Benchmark source changed; no automatic retry')
    update()
    try:
        source_check()
        if hashlib.sha256(args.training_wrapper.read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=args.wrapper_sha256:
            raise ValueError('Evaluation timing wrapper changed')
        raw=args.helper.read_bytes()
        if hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()!=args.helper_sha256:
            raise ValueError('Dependency helper changed')
        spec=importlib.util.spec_from_file_location('development_dependency_helper',args.helper)
        helper=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        initial=helper.process_identity(args.dependency_pid)
        if initial is not None and '/root/autodl-tmp/run_procedural_followup.py' not in initial['argv']:
            raise ValueError('Unexpected predecessor command')
        update(phase='waiting_for_natural_intake',dependency_identity=initial)
        deadline=time.monotonic()+args.timeout_minutes*60
        while initial is not None and helper.dependency_state(initial,helper.process_identity(args.dependency_pid))=='live':
            if time.monotonic()>deadline:
                raise TimeoutError('Predecessor remains live; probe not started')
            time.sleep(15)
        preceding=json.loads((args.followup/'status.json').read_text())
        if preceding['status']!='completed' or preceding['natural_raw_runs']!=32 or preceding['natural_views']!=64:
            raise ValueError('Natural intake incomplete; no resource training')
        source_check()
        update(phase='measure_complete_development_pairs')
        sys.path.insert(0,str(source))
        from intentlab.formal_data import read_jsonl, write_jsonl
        from intentlab.neural import encode_pair
        from intentlab.protocol import model_snapshot, verify_official_assets
        from intentlab.sft_data import validate_splits
        from transformers import AutoTokenizer
        expected=json.loads((source/'examples/results/formal-m2j-procedural-candidates/private-file-sha256.json').read_text())
        intake=args.followup/'natural-intake'
        manifest=json.loads((intake/'manifest.json').read_text())
        if manifest['kind']!='programmatic_natural_development_intake' or manifest['human_evaluation_claim']:
            raise ValueError('Unexpected natural label source')
        splits={}
        bindings={}
        for split,original_count in [('train',2400),('validation',600)]:
            original=args.base/'export'/(split+'.jsonl')
            extra=intake/'export'/(split+'.jsonl')
            actual=hashlib.sha256(original.read_bytes()).hexdigest()
            extra_sha=hashlib.sha256(extra.read_bytes()).hexdigest()
            if actual!=expected['export/'+original.name] or extra_sha!=manifest['files_sha256']['export/'+extra.name]:
                raise ValueError('Development SFT input changed')
            original_rows,extra_rows=read_jsonl(original),read_jsonl(extra)
            if len(original_rows)!=original_count or len(extra_rows)!=32:
                raise ValueError('Unexpected original/natural view coverage')
            splits[split]=original_rows+extra_rows
            if len({r['case_id'] for r in splits[split]})!=len(splits[split]):
                raise ValueError('Development case ID overlap')
            bindings[split]={'original_sha256':actual,'natural_sha256':extra_sha}
        validate_splits(splits)
        model='/root/autodl-tmp/models/Qwen3.5-9B'
        official=verify_official_assets(model_snapshot(model),source)
        tokenizer=AutoTokenizer.from_pretrained(model,local_files_only=True,trust_remote_code=False)
        lengths={}
        aggregates={}
        for split,pairs in splits.items():
            rows=[]
            for pair in pairs:
                encoded=encode_pair(tokenizer,pair,10**9)
                supervised=sum(t!=-100 for t in encoded['labels'])
                rows.append({'case_id':pair['case_id'],'source_task_id':pair['task_id'],
                    'total_tokens':len(encoded['input_ids']),'target_tokens':supervised})
            lengths[split]=rows
            aggregates[split]={'sequence_tokens':profile([r['total_tokens'] for r in rows]),
                'supervised_tokens':profile([r['target_tokens'] for r in rows]),
                'source_groups':len({r['source_task_id'] for r in rows})}
        chosen=pressure_ids(lengths['train'])
        maximum=max(r['total_tokens'] for rows in lengths.values() for r in rows)
        context=math.ceil(maximum/1024)*1024
        save('lengths-private.json',lengths)
        save('profile.json',{'scope':'complete_original_and_natural_development_SFT',
            'aggregates':aggregates,'file_bindings':bindings,'official_assets':official,
            'maximum_required_sequence_length':maximum,'proposed_probe_max_length':context,
            'pressure_train_case_ids':chosen,'formal_budget_approved':False,'heldout_files_read':False})
        if context>16384:
            raise ValueError('Complete data exceeds this registered 16384 probe cap; retain lengths and review, never truncate')
        if shutil.disk_usage(root).free<4*1024**3:
            raise RuntimeError('Insufficient free disk for resumable development checkpoint')
        data=root/'data'
        data.mkdir()
        by_id={r['case_id']:r for r in splits['train']}
        write_jsonl(data/'train.jsonl',[by_id[cid] for cid in chosen])
        write_jsonl(data/'validation.jsonl',splits['validation'])
        (data/'test.jsonl').write_text('INVALID JSON: must be deferred, never read\n')
        neural_args=['--data',str(data),'--out',str(root/'train'),
            '--model',model,'--mode','qlora','--device','cuda','--schedule','cosine',
            '--steps','4','--eval-every','2','--batch-size','1','--accumulation','2',
            '--max-length',str(context),'--lr','0.00005','--minimum-lr','0.000005',
            '--rank','16','--alpha','32','--seed','0','--limit','0','--threads','2','--defer-test']
        timings=[]
        for phase,extra in [('first_two_updates',['--stop-after','2']),('resume_to_four_updates',['--resume',str(root/'train/latest.pt')])]:
            source_check()
            if hashlib.sha256(args.training_wrapper.read_bytes().replace(b'\r\n',b'\n')).hexdigest()!=args.wrapper_sha256:
                raise ValueError('Evaluation timing wrapper changed while waiting')
            command=[sys.executable,str(args.training_wrapper.resolve()),'--source',str(source),
                '--timing-output',str(root/'validation-timings.jsonl'),'--invocation',phase,'--']+neural_args
            update(phase=phase,command=command+extra)
            started=time.perf_counter()
            with (root/(phase+'.log')).open('x') as log:
                result=subprocess.run(command+extra,cwd=source,stdout=log,stderr=subprocess.STDOUT)
            timings.append({'phase':phase,'wall_seconds':time.perf_counter()-started,'exit_code':result.returncode})
            save('invocation-timings.json',timings)
            if result.returncode:
                raise RuntimeError(f'{phase} failed; no automatic retry or truncation')
            shutil.copyfile(root/'train/result.json',root/(phase+'-result.json'))
        first=json.loads((root/'first_two_updates-result.json').read_text())
        final=json.loads((root/'resume_to_four_updates-result.json').read_text())
        expected_targets=sum(r['target_tokens'] for r in lengths['validation'])
        if first['step']!=2 or first['completed'] or final['step']!=4 or not final['completed'] or not final.get('test_deferred'):
            raise ValueError('Stop/resume/deferred-test contract failed')
        if first['data_hash']!=final['data_hash'] or first['base_identity']!=final['base_identity']:
            raise ValueError('Resume input/base binding changed')
        if final['history'][:len(first['history'])]!=first['history'] or final['supervised_tokens']!=2*first['supervised_tokens']:
            raise ValueError('Resume history or supervision counters changed')
        if any(r['validation']['target_tokens']!=expected_targets for r in final['history']):
            raise ValueError('Full validation supervision denominator changed')
        validation_times=read_jsonl(root/'validation-timings.jsonl')
        if len(validation_times)!=2 or any(r['status']!='completed' or r['target_tokens']!=expected_targets for r in validation_times):
            raise ValueError('Full validation timing coverage changed')
        update(status='completed',phase='completed',finished_unix=time.time(),
            full_validation_views=len(splits['validation']),maximum_required_sequence_length=maximum,
            warning='Four updates on two pressure train examples, full development validation. Not six formal trainings, not a continuous-vs-resume numerical equivalence proof.')
        print(json.dumps(record,indent=2),flush=True)
    except BaseException as exc:
        update(status='failed',error_type=type(exc).__name__,error=str(exc),finished_unix=time.time())
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','base','followup','out','helper','training-wrapper'):
        parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--helper-sha256',required=True)
    parser.add_argument('--wrapper-sha256',required=True)
    parser.add_argument('--dependency-pid',type=int,required=True)
    parser.add_argument('--timeout-minutes',type=int,default=360)
    args=parser.parse_args()
    if args.timeout_minutes<1 or args.dependency_pid<1:
        parser.error('Positive dependency PID and deadline required')
    main(args)
