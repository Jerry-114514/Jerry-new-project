"""Plot recorded validations for completed limited-run endpoints, without test data."""
import argparse
import hashlib
import json
import math
from pathlib import Path

STEPS = [209, 418, 627, 836, 1045, 1250]
RUNS = [f'{kind}-seed-{seed}' for seed in range(3) for kind in ('D', 'E')]


def validate(history):
    if not isinstance(history, dict) or not history or not set(history) <= set(RUNS):
        raise ValueError('Provide one to six completed registered training histories')
    selected = {}
    for name, rows in history.items():
        if [r['step'] for r in rows] != STEPS:
            raise ValueError('Every completed endpoint must retain all six recorded validations')
        for row in rows:
            loss, lr = row['validation']['loss'], row['lr_used']
            if not all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)
                       for x in (loss, lr)) or loss < 0 or not 0 < lr <= 5e-5 * (1+1e-10):
                raise ValueError('Invalid recorded loss or learning rate')
            if row['validation']['target_tokens'] != 215880:
                raise ValueError('Validation target-token count differs from the limited protocol')
        best = min(rows, key=lambda r: r['validation']['loss'])
        selected[name] = {'step': best['step'], 'validation_loss': best['validation']['loss']}
    return {'completed_histories': len(history), 'planned_histories': 6,
            'histories_not_provided': [name for name in RUNS if name not in history],
            'selected_by_validation': selected, 'heldout_efficacy_inferred': False,
            'smoothing': False, 'missing_histories_imputed': False}


def public_histories(history):
    """Restrict serialized histories to scalar measurements, dropping any other metadata."""
    return {name: [{'step':r['step'], 'validation':{'loss':r['validation']['loss'],
                    'target_tokens':r['validation']['target_tokens']}, 'lr_used':r['lr_used']} for r in rows]
            for name, rows in history.items()}


def render(history, out):
    summary = validate(history)
    history = public_histories(history)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    matplotlib.rcParams['svg.hashsalt'] = 'intentlab-limited-30h-curves'
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    colors = {'D': '#2563eb', 'E': '#d97706'}
    labels = {'D': 'Cosine', 'E': 'Plateau'}
    for metric in ('validation-loss', 'learning-rate'):
        fig, axes = plt.subplots(1, 3, figsize=(14, 4.3), sharey=True, layout='constrained')
        for seed, ax in enumerate(axes):
            provided = []
            for kind in ('D', 'E'):
                name = f'{kind}-seed-{seed}'
                if name not in history:
                    continue
                rows = history[name]; provided.append(labels[kind])
                value = (lambda r: r['validation']['loss']) if metric == 'validation-loss' else (lambda r: r['lr_used'])
                ax.plot([r['step'] for r in rows], [value(r) for r in rows], '.-',
                        color=colors[kind], label=labels[kind], markersize=7)
                if metric == 'validation-loss':
                    best = summary['selected_by_validation'][name]
                    ax.plot(best['step'], best['validation_loss'], marker='*', markersize=14,
                            color=colors[kind], markeredgecolor='#111827')
            ax.set_title(f'Seed {seed}')
            ax.set_xlim(0, 1250); ax.set_ylim(bottom=0)
            ax.set_xticks([0, 209, 627, 1045, 1250]); ax.tick_params(axis='x', labelrotation=25)
            ax.set_xlabel('Optimizer update'); ax.grid(alpha=.2)
            if provided:
                ax.legend(fontsize=9)
            absent = [labels[k] for k in ('D', 'E') if f'{k}-seed-{seed}' not in history]
            if absent:
                annotation_y = .95 if metric == 'validation-loss' else .07
                ax.text(.04, annotation_y, 'Not provided: '+', '.join(absent), transform=ax.transAxes,
                        va='top' if metric == 'validation-loss' else 'bottom', fontsize=9,
                        bbox={'facecolor':'white', 'alpha':.8, 'edgecolor':'none'})
        axes[0].set_ylabel('Target-token-weighted validation CE' if metric == 'validation-loss' else 'Recorded learning rate')
        note = 'Stars: validation-selected. ' if metric == 'validation-loss' else ''
        fig.suptitle(f'Limited 30-hour follow-up: {summary["completed_histories"]}/6 completed histories\n'
                     +note+'Recorded points; lines guide the eye; held-out efficacy untested', fontsize=12)
        for suffix in ('svg', 'png'):
            metadata = {'Date': None} if suffix == 'svg' else {'Software':'IntentLab'}
            target = out/(metric+'.'+suffix)
            fig.savefig(target, dpi=150, metadata=metadata)
            if suffix == 'svg':
                # Keep Matplotlib's geometry and line breaks, without trailing path whitespace.
                target.write_text('\n'.join(line.rstrip() for line in target.read_text(encoding='utf-8').splitlines())+'\n',
                                  encoding='utf-8', newline='\n')
        plt.close(fig)
    (out/'training-history.json').write_text(json.dumps(history, indent=2)+'\n', encoding='utf-8')
    (out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n', encoding='utf-8')
    hashes = {}
    for path in sorted(out.iterdir()):
        with path.open('rb') as f:
            hashes[path.name] = hashlib.file_digest(f, 'sha256').hexdigest()
    (out/'SHA256SUMS.txt').write_text(''.join(f'{sha}  {name}\n' for name, sha in hashes.items()), encoding='ascii')
    return summary


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--history', type=Path, required=True, help='Only scalar histories from completed endpoints')
    p.add_argument('--out', type=Path, required=True, help='New output directory')
    a = p.parse_args()
    print(json.dumps(render(json.loads(a.history.read_text(encoding='utf-8')), a.out)))
