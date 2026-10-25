"""Render the six published formal training histories with only the standard library.

This is a reporting tool. It never opens test labels or changes a frozen run.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
from xml.sax.saxutils import escape


def render(history):
    expected = {f'{schedule}-seed-{seed}' for schedule in ('cosine', 'plateau') for seed in range(3)}
    if set(history) != expected:
        raise ValueError('Expected all six formal histories')
    for name, rows in history.items():
        if [row['step'] for row in rows] != list(range(200, 2401, 200)) + [2464]:
            raise ValueError('Expected every recorded full validation, including the final update')
        for row in rows:
            loss, lr = row['validation']['loss'], row['lr_used']
            if not all(math.isfinite(value) for value in (loss, lr)) or not 0 <= loss <= .085 or not 0 < lr <= .000055:
                raise ValueError('A recorded value is invalid or outside the published plot range')
            if row['validation']['target_tokens'] != 133026:
                raise ValueError('Validation target count changed')
    for schedule in ('cosine', 'plateau'):
        reference = [row['lr_used'] for row in history[f'{schedule}-seed-0']]
        if any([row['lr_used'] for row in history[f'{schedule}-seed-{seed}']] != reference for seed in (1, 2)):
            raise ValueError('The shared learning-rate panel requires matching seed trajectories')
    parts = ['<svg xmlns="http://www.w3.org/2000/svg" width="1100" height="760" viewBox="0 0 1100 760">', '<rect width="1100" height="760" fill="white"/>', '<g font-family="sans-serif" font-size="13" fill="#1f2937">', '<text x="550" y="28" text-anchor="middle" font-size="21">Qwen3.5-9B: validation loss and learning rate</text>', '<text x="550" y="51" text-anchor="middle">6 runs / 2464 updates each / 13 full validations; stars = selected checkpoints</text>']
    colors = {'cosine': '#2563eb', 'plateau': '#ea580c'}
    for panel in range(4):
        left = 75 + (panel % 2) * 550
        top = 95 + (panel // 2) * 320
        width, height = 420, 225
        maximum = .085 if panel < 3 else .000055
        x = lambda step: left + (step - 200) / (2464 - 200) * width
        y = lambda loss: top + height - loss / maximum * height
        title = f'Seed {panel}: validation CE' if panel < 3 else 'Recorded learning rate (all seeds identical)'
        parts.append(f'<text x="{left}" y="{top-16}" font-size="16">{escape(title)}</text>')
        for index in range(5):
            val = maximum * index / 4
            py = y(val)
            label = f'{val:.3f}' if panel < 3 else f'{val:.1e}'
            parts.append(f'<path d="M {left} {py:.2f} h {width}" stroke="#e5e7eb"/><text x="{left-8}" y="{py+4:.2f}" text-anchor="end">{label}</text>')
        for step in (200, 800, 1400, 2000, 2464):
            parts.append(f'<text x="{x(step):.2f}" y="{top+height+21}" text-anchor="middle">{step}</text>')
        parts.append(f'<text x="{left+width/2}" y="{top+height+43}" text-anchor="middle">Optimizer update</text>')
        for schedule, color in colors.items():
            rows = history[f'{schedule}-seed-{panel if panel < 3 else 0}']
            value = lambda r: r['validation']['loss'] if panel < 3 else r['lr_used']
            points = ' '.join(f"{x(r['step']):.2f},{y(value(r)):.2f}" for r in rows)
            parts.append(f'<polyline points="{points}" fill="none" stroke="{color}" stroke-width="2"/>')
            for row in rows:
                parts.append(f'<circle cx="{x(row["step"]):.2f}" cy="{y(value(row)):.2f}" r="3" fill="{color}"/>')
            if panel < 3:
                best = min(rows, key=value)
                px, py = x(best['step']), y(value(best))
                parts.append(f'<text x="{px}" y="{py+7}" text-anchor="middle" font-size="24" fill="{color}" stroke="#111827" stroke-width=".5">★</text>')
        parts.append(f'<text x="{left+12}" y="{top+19}" fill="{colors["cosine"]}">Cosine</text><text x="{left+90}" y="{top+19}" fill="{colors["plateau"]}">Plateau</text>')
    parts += ['<text x="550" y="741" text-anchor="middle">Raw recorded points, no smoothing. Validation results do not establish held-out efficacy.</text>', '</g></svg>']
    return '\n'.join(parts) + '\n'


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--history', type=Path, default=root / 'examples/results/formal-m4e-training-complete/training-history.json')
    parser.add_argument('--out', type=Path, required=True, help='New SVG path; existing files are never overwritten')
    args = parser.parse_args()
    rendered = render(json.loads(args.history.read_text(encoding='utf-8'))).encode('utf-8')
    with args.out.open('xb') as output:
        output.write(rendered)
    print(json.dumps({'svg': str(args.out), 'sha256': hashlib.sha256(rendered).hexdigest(), 'smoothing': False}))


if __name__ == '__main__':
    main()
