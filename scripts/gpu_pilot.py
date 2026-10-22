"""Run a bounded, reproducible GPU pilot; synthetic holdout is not a benchmark.

Run from the repository root. Model weights and checkpoints stay under runs/.
"""
from __future__ import annotations

import argparse
from collections import Counter
import gc
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

from intentlab.core import digest
from intentlab.report import save_json


def diagnostic(model_path, output, limit):
    import torch
    from intentlab.model_backend import LocalBackend, json_response
    rows = [json.loads(line) for line in Path('data/sft/test.jsonl').read_text(encoding='utf-8').splitlines()]
    rows = rows[:limit] if limit else rows
    backend = LocalBackend(model_path, device='cuda', max_new_tokens=768, token_budget=8192)
    from intentlab.neural import encode_pair, evaluate_loss
    # Evaluate all validation/test targets at identical BF16 inference precision.
    losses = {}
    for split in ('validation', 'test'):
        pairs = [json.loads(line) for line in Path(f'data/sft/{split}.jsonl').read_text(encoding='utf-8').splitlines()]
        examples = [encode_pair(backend.tokenizer, row, 4096) for row in pairs]
        losses[split] = evaluate_loss(backend.model, examples, backend.tokenizer, 'cuda', batch_size=1)
    save_json(output / 'inference-loss.json', losses)
    counts = Counter(samples=len(rows))
    records = []
    output.mkdir(parents=True, exist_ok=True)
    records_path = output / 'diagnostic-records.jsonl'
    records_path.write_text('', encoding='utf-8')
    started = time.perf_counter()
    for row in rows:
        backend.reset()
        output_text = backend.complete(row['prompt'])
        gold = {f['id']: f for f in json.loads(row['completion'])['findings']}
        record = {'task_id': row['task_id'], 'kind': row['kind'], 'events_visible': row['events_visible'],
                  'prompt_hash': digest(row['prompt']), 'gold': gold, **output_text}
        try:
            findings = json_response(output_text['text'])['findings']
            if not isinstance(findings, list) or len(findings) != 4:
                raise ValueError('Need exactly four findings')
            predicted = {f['id']: f for f in findings}
            if len(predicted) != 4 or set(predicted) != set(gold):
                raise ValueError('Invalid or duplicate requirement IDs')
            # Compare raw output; do not force hidden-history predictions to unknown.
            observation = json.loads(row['prompt'].split('\n', 1)[1].rsplit('\nJSON:', 1)[0])['observation']
            allowed = {e['index'] for e in (observation.get('events') or [])}
            for finding in findings:
                if finding['status'] not in {'satisfied', 'violated', 'unknown'}:
                    raise ValueError('Invalid status')
                evidence = finding.get('evidence', [])
                if not isinstance(evidence, list) or any(type(i) is not int or i not in allowed for i in evidence):
                    raise ValueError('Invalid evidence indices')
            correct = sum(predicted[r]['status'] == gold[r]['status'] for r in gold)
            counts['valid_outputs'] += 1
            counts['correct_statuses'] += correct
            counts['exact_status_samples'] += correct == 4
            for rid, expected in gold.items():
                counts['gold_' + expected['status']] += 1
                counts['correct_' + expected['status']] += predicted[rid]['status'] == expected['status']
            record['prediction'] = predicted
        except (ValueError, TypeError, KeyError) as exc:
            counts['invalid_outputs'] += 1
            record['error'] = str(exc)
            for expected in gold.values():
                counts['gold_' + expected['status']] += 1
        records.append(record)
        with records_path.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
        print('diagnostic', Path(model_path).name, len(records), '/', len(rows), flush=True)
    summary = dict(counts)
    summary.update(valid_output_rate=counts['valid_outputs'] / len(rows),
                   status_accuracy=counts['correct_statuses'] / (4 * len(rows)),
                   exact_status_accuracy=counts['exact_status_samples'] / len(rows),
                   seconds=time.perf_counter() - started,
                   inference_losses=losses,
                   warning='Synthetic smoke holdout. Invalid outputs count as wrong. Evidence index validity does not establish semantic support.')
    for status in ('satisfied', 'violated', 'unknown'):
        summary['recall_' + status] = counts['correct_' + status] / counts['gold_' + status] if counts['gold_' + status] else None
    save_json(output / 'diagnostic-summary.json', summary)
    output.mkdir(parents=True, exist_ok=True)
    del backend
    gc.collect()
    torch.cuda.empty_cache()
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--steps', type=int, default=24)
    parser.add_argument('--seeds', nargs='+', type=int, default=[0])
    parser.add_argument('--diagnostic-limit', type=int, default=12, help='0 evaluates all 48 smoke views')
    parser.add_argument('--closed-loop-limit', type=int, default=2)
    args = parser.parse_args()
    import torch
    if not torch.cuda.is_available():
        raise RuntimeError('A real CUDA GPU is required')
    args.out.mkdir(parents=True, exist_ok=True)
    provenance = args.model / 'download-provenance.json'
    manifest = {'kind': '5090_qlora_pilot', 'protocol': 'explicit-requirement-ids-v2', 'gpu': torch.cuda.get_device_name(),
                'gpu_memory_bytes': torch.cuda.get_device_properties(0).total_memory,
                'cuda': torch.version.cuda, 'python': platform.python_version(),
                'versions': {name: importlib.metadata.version(name) for name in ('torch', 'transformers', 'peft', 'bitsandbytes', 'accelerate')},
                'steps': args.steps, 'seeds': args.seeds, 'diagnostic_limit': args.diagnostic_limit,
                'model': str(args.model), 'model_provenance': json.loads(provenance.read_text()) if provenance.exists() else None,
                'source_hashes': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('intentlab').glob('*.py'))},
                'pilot_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'warning': 'Pilot on synthetic data. One seed does not establish significance; no generalization or new LR algorithm claim.'}
    save_json(args.out / 'manifest.json', manifest)
    results = []
    diagnostic_results = {}
    def invoke(command, log):
        print('START', ' '.join(str(x) for x in command), flush=True)
        with log.open('w', encoding='utf-8') as handle:
            subprocess.run([str(x) for x in command], check=True, stdout=handle, stderr=subprocess.STDOUT,
                           env={**os.environ, 'PYTHONUNBUFFERED': '1', 'TOKENIZERS_PARALLELISM': 'false'})
    for seed in args.seeds:
        for schedule in ('cosine', 'plateau'):
            run = args.out / f'{schedule}-seed-{seed}'
            run.mkdir(parents=True, exist_ok=True)
            config = {'data': 'data/sft', 'model': str(args.model), 'revision': None, 'mode': 'qlora',
                      'device': 'cuda', 'schedule': schedule, 'steps': args.steps, 'eval_every': max(1, args.steps // 3),
                      'batch_size': 1, 'accumulation': 2, 'max_length': 4096, 'lr': 5e-5,
                      'minimum_lr': 5e-6, 'rank': 16, 'alpha': 32, 'seed': seed, 'limit': 0, 'threads': 4}
            config_path = run / 'requested-config.json'
            save_json(config_path, config)
            command = [sys.executable, '-m', 'intentlab.neural', '--config', config_path, '--out', run]
            invocation_seconds = []
            started = time.perf_counter()
            # Exercise real CUDA checkpoint recovery within the original training horizon.
            if schedule == 'cosine':
                invoke(command + ['--stop-after', args.steps // 2], run / 'interrupted.log')
                invocation_seconds.append(json.loads((run / 'result.json').read_text())['seconds_this_invocation'])
                invoke(command + ['--resume', run / 'latest.pt'], run / 'resumed.log')
            else:
                invoke(command, run / 'training.log')
            result = json.loads((run / 'result.json').read_text())
            invocation_seconds.append(result['seconds_this_invocation'])
            results.append({'name': run.name, 'training': result,
                            'training_loop_seconds_all_invocations': sum(invocation_seconds),
                            'wall_seconds_including_loads': time.perf_counter() - started})
            save_json(args.out / 'summary.json', {'runs': results})
    for model_path, output in [(args.model, args.out / 'base')] + [(args.out / r['name'] / 'model', args.out / r['name']) for r in results]:
        output.mkdir(parents=True, exist_ok=True)
        scores = diagnostic(model_path, output, args.diagnostic_limit)
        diagnostic_results[output.name] = scores
        comparison = {name: {'status_accuracy_change': score['status_accuracy'] - diagnostic_results['base']['status_accuracy'],
                             'valid_output_rate_change': score['valid_output_rate'] - diagnostic_results['base']['valid_output_rate'],
                             'same_precision_validation_loss_change': score['inference_losses']['validation']['loss'] - diagnostic_results['base']['inference_losses']['validation']['loss']}
                      for name, score in diagnostic_results.items() if name != 'base'}
        save_json(args.out / 'summary.json', {'runs': results, 'diagnostics': diagnostic_results, 'changes_from_base': comparison})
        print('DIAGNOSTIC_RESULT', output.name, json.dumps(scores), flush=True)
        if args.closed_loop_limit:
            invoke([sys.executable, '-m', 'intentlab', 'run', '--model-path', model_path,
                    '--model-role', 'analyzer', '--device', 'cuda', '--split', 'test',
                    '--limit', args.closed_loop_limit, '--repeats', 1, '--policies', 'fixed-full', 'dynamic',
                    '--max-new-tokens', 768, '--token-budget', 30000, '--out', output / 'closed-loop'], output / 'closed-loop.log')
    save_json(args.out / 'completed.json', {'completed': True, 'runs': [r['name'] for r in results]})
    print('GPU_PILOT_COMPLETE', flush=True)


if __name__ == '__main__':
    main()
