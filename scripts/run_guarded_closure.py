"""Post-hoc engineering check of the independent repair hard guard."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from intentlab.report import save_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pilot', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    assert (args.pilot / 'completed.json').exists()
    original = json.loads((args.pilot / 'manifest.json').read_text(encoding='utf-8'))
    models = {'base': Path(original['model']),
              'cosine-seed-0': args.pilot / 'cosine-seed-0/model',
              'plateau-seed-0': args.pilot / 'plateau-seed-0/model'}
    args.out.mkdir(parents=True, exist_ok=True)
    save_json(args.out / 'manifest.json', {
        'kind': 'posthoc_repair_hard_guard_engineering_check', 'initial_traces_guarded': False,
        'models': {name: str(path) for name, path in models.items()},
        'source_hashes': {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path('intentlab').glob('*.py'))},
        'warning': 'Same two synthetic tasks, one greedy run. This supplements the frozen original pilot; it does not establish statistical or algorithmic superiority.'})
    summary = {}
    for name, path in models.items():
        started = time.perf_counter()
        with (args.out / f'{name}.log').open('w', encoding='utf-8') as log:
            subprocess.run([sys.executable, '-m', 'intentlab', 'run', '--model-path', str(path),
                '--model-role', 'analyzer', '--device', 'cuda', '--split', 'test', '--limit', '2',
                '--repeats', '1', '--policies', 'fixed-full', 'dynamic', '--max-new-tokens', '768',
                '--token-budget', '30000', '--out', str(args.out / name)], check=True, stdout=log, stderr=subprocess.STDOUT)
        scores = json.loads((args.out / name / 'summary.json').read_text(encoding='utf-8'))
        records = [json.loads(line) for line in (args.out / name / 'runs.jsonl').read_text(encoding='utf-8').splitlines()]
        summary[name] = {'scores': scores, 'hard_rejections': sum(r['cost']['hard_rejections'] for r in records),
                         'wall_seconds': time.perf_counter() - started}
        save_json(args.out / 'summary.json', summary)
        print('GUARDED_RESULT', name, json.dumps(summary[name]), flush=True)
    save_json(args.out / 'completed.json', {'completed': True})


if __name__ == '__main__':
    main()
