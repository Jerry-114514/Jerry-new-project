"""One-shot dependent development jobs; never restart a failed predecessor."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def process_identity(pid, proc_root=Path('/proc')):
    try:
        root=proc_root/str(pid)
        raw=(root/'stat').read_text()
        fields=raw.rsplit(')',1)[1].split()
        if fields[0]=='Z':
            return None  # Exited and awaiting parent reap, not a live job.
        return {'pid':pid,'start_ticks':fields[19],
                'argv':(root/'cmdline').read_bytes().decode().strip('\0').split('\0')}
    except FileNotFoundError:
        return None


def dependency_state(expected, actual):
    if actual is None:
        return 'terminal'
    if actual != expected:
        raise RuntimeError('Dependency PID identity changed; no successor started')
    return 'live'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(args):
    source=args.source.resolve()
    root=args.out.resolve()
    baseline=args.baseline.resolve()
    selection=args.selection.resolve()
    root.mkdir(mode=0o700,parents=True,exist_ok=False)
    record={'status':'running','phase':'preflight','pid':os.getpid(),
            'dependency_pid':args.dependency_pid,'started_unix':time.time(),
            'formal_training':False,'restarts_allowed':False}
    def update(**values):
        record.update(values)
        temporary=root/'status.tmp'
        temporary.write_text(json.dumps(record,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        temporary.replace(root/'status.json')
    def source_check():
        head=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip()
        changed=subprocess.check_output(['git','-C',str(source),'status','--porcelain'],text=True)
        if head!='b4a757afc7c01332734fb6e4c2f08f3f7fcceef9' or changed:
            raise RuntimeError('Development execution source changed; retain record and review')
    def command(stage, argv):
        source_check()
        update(phase=stage,command=argv)
        with (root/(stage+'.log')).open('x',encoding='utf-8') as log:
            result=subprocess.run(argv,cwd=source,stdout=log,stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f'{stage} exited {result.returncode}; no automatic retry')
    def external_inputs_check():
        if sha(selection/'plan.json')!=args.selection_sha256:
            raise ValueError('Preselected natural collection plan changed')
        intake_bytes=args.intake_module.read_bytes()
        if hashlib.sha256(intake_bytes.replace(b'\r\n',b'\n')).hexdigest()!=args.intake_sha256:
            raise ValueError('Programmatic intake implementation changed')
        if sha(args.scorer)!=args.scorer_sha256:
            raise ValueError('Recorded development scorer changed')
    update()
    try:
        source_check()
        external_inputs_check()
        initial=process_identity(args.dependency_pid)
        expected_script='/root/autodl-tmp/develop_fewshot.py'
        if initial is not None and (expected_script not in initial['argv'] or initial['argv'][-1]!='infer'):
            raise RuntimeError('Dependency PID is not the expected baseline inference')
        update(phase='waiting_for_baseline',dependency_identity=initial)
        deadline=time.monotonic()+args.timeout_minutes*60
        while initial is not None and dependency_state(initial,process_identity(args.dependency_pid))=='live':
            if time.monotonic()>deadline:
                raise TimeoutError('Known dependency still live at wait deadline; no successor started')
            time.sleep(15)
        # Terminal/missing PID alone is insufficient: require completed raw
        # artifacts and the existing scorer's immutable-plan/hash checks.
        state=json.loads((baseline/'inference-status.json').read_text())
        if state['status']!='completed':
            raise RuntimeError('Baseline terminated without completion; no scoring/collection')
        for name in ('A','B3','B4'):
            manifest=json.loads((baseline/name/'manifest.json').read_text())
            predictions=(baseline/name/'predictions.jsonl').read_text().splitlines()
            if manifest['status']!='completed' or manifest['case_count']!=600 or len(predictions)!=600:
                raise ValueError('Incomplete baseline condition; no scoring/collection')
        if (baseline/'scoring').exists():
            raise FileExistsError('Scoring already exists; retain it and review instead of repeating')
        external_inputs_check()
        command('score_baseline',[sys.executable,str(args.scorer.resolve())])
        sys.path.insert(0,str(source))
        from intentlab.core import digest
        from intentlab.execution_data import load_execution_tasks, load_references
        from intentlab.protocol import model_snapshot, verify_official_assets
        tasks=load_execution_tasks(selection/'tasks.jsonl')
        refs=load_references(selection/'references.jsonl',tasks)
        plan=json.loads((selection/'plan.json').read_text())
        if digest(tasks)!=plan['tasks_hash'] or digest(refs)!=plan['references_hash']:
            raise ValueError('Natural collection inputs changed')
        if len(tasks)!=32 or any(t['split'] not in {'train','validation'} for t in tasks):
            raise ValueError('Expected all 32 preselected development contracts')
        model='/root/autodl-tmp/models/Qwen3.5-9B'
        assets=verify_official_assets(model_snapshot(model),source)
        update(phase='natural_preflight',official_assets=assets)
        expected_settings={'policies':['none'],'max_repairs':0,'max_tool_steps':3,'actor_envelope':'extract',
            'max_new_tokens':1536,'context_limit':13312,'token_budget':24576,'analyzer_mode':'rule','hard_guard_enabled':True}
        if plan['collector_settings']!=expected_settings:
            raise ValueError('Collection settings differ from the before-outcome plan')
        execution=root/'natural-execution'
        command('collect_natural',[sys.executable,'-m','intentlab.execution',
            '--tasks',str(selection/'tasks.jsonl'),'--references',str(selection/'references.jsonl'),
            '--out',str(execution),'--actor-model',model,'--device','cuda','--policies','none',
            '--max-repairs','0','--max-tool-steps','3','--actor-envelope','extract','--analyzer-mode','rule',
            '--context-limit','13312','--max-new-tokens','1536','--token-budget','24576'])
        source_check()
        external_inputs_check()
        update(phase='label_natural')
        spec=importlib.util.spec_from_file_location('intentlab.followup_programmatic_intake',args.intake_module)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        labeled=module.build_programmatic(selection/'tasks.jsonl',selection/'references.jsonl',execution,root/'natural-intake')
        update(status='completed',phase='completed',natural_raw_runs=labeled['raw_runs'],natural_views=labeled['views'],
               finished_unix=time.time())
        print(json.dumps(record,indent=2),flush=True)
    except BaseException as exc:
        update(status='failed',error_type=type(exc).__name__,error=str(exc),finished_unix=time.time())
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('source','baseline','selection','out','scorer','intake-module'):
        parser.add_argument('--'+name,type=Path,required=True)
    for name in ('selection-sha256','scorer-sha256','intake-sha256'):
        parser.add_argument('--'+name,required=True)
    parser.add_argument('--dependency-pid',type=int,required=True)
    parser.add_argument('--timeout-minutes',type=int,default=360)
    args=parser.parse_args()
    if args.timeout_minutes<1 or args.dependency_pid<1:
        parser.error('Positive dependency PID and wait deadline required')
    main(args)
