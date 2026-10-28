"""Verify private endpoint archives and export only scalar training aggregates.

This reporting tool never loads checkpoints, reads held-out data, or calls a model.
"""
import argparse
import json
import math
from pathlib import Path
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.core import digest
from intentlab.model_backup import verify_model_backup
from render_limited_training_curves import RUNS, public_histories, validate


def require(condition, message):
    if not condition:
        raise ValueError(message)


def summarize(results, protocol):
    require(bool(results) and set(results) <= set(RUNS), 'Unexpected or empty endpoint set')
    require(set(protocol['jobs']) == set(RUNS), 'Expected six registered endpoints')
    histories = {name: r['history'] for name, r in results.items()}
    selection = validate(histories)['selected_by_validation']
    examples = protocol['selected_view_counts']['train']
    reference_exposures = None
    training, events, pairs, initial = {}, {}, [], {}
    for name in RUNS:
        if name not in results:
            continue
        r = results[name]
        require(r['completed'] is True and r['test_deferred'] is True, 'Completed deferred-test run required')
        require(r['config'] == protocol['jobs'][name]['config'], 'Frozen endpoint configuration differs')
        require(r['base_identity'] == protocol['base_identity'] and r['data_hash'] == protocol['training_data_hash'],
                'Base or training data binding differs')
        require(r['step'] == protocol['training']['steps'] == 1250, 'Incomplete update budget')
        require(r['examples_seen'] == examples == 2500 and r['supervised_tokens'] == protocol['training_supervised_tokens'],
                'Training exposure or target-token budget differs')
        exposures = r['sample_exposures']
        require(len(exposures) == examples and all(type(x['count']) is int and x['count'] == 1 for x in exposures),
                'Each registered example must be exposed once')
        require({x['index'] for x in exposures} == set(range(examples)) and len({x['case_id'] for x in exposures}) == examples,
                'Duplicate or missing training exposure identities')
        if reference_exposures is None:
            reference_exposures = exposures
        require(exposures == reference_exposures, 'Endpoint training exposure inventories differ')
        selected = selection[name]
        require(r['selection']['rule'] == 'minimum_validation_loss_first_tie'
                and r['selection']['step'] == selected['step']
                and r['selection']['validation_loss'] == selected['validation_loss']
                and r['selection']['validation_target_tokens'] == protocol['validation_supervised_tokens'],
                'Selection is not the first minimum of the recorded validations')
        require(all(h['validation']['target_tokens'] == protocol['validation_supervised_tokens'] for h in r['history']),
                'Validation target-token binding differs')
        events[name] = []
        for h in r['history']:
            event = h['scheduler']
            if name.startswith('D-'):
                require(event is None, 'Unexpected feedback event for cosine')
                continue
            require(isinstance(event, dict) and type(event.get('reduced')) is bool, 'Missing Plateau event record')
            require(event['old_lr'] == h['lr_used'] and event['new_lr'] == event['lr'], 'Plateau event timing differs')
            require(type(event['new_lr']) in (int, float) and math.isfinite(event['new_lr'])
                    and protocol['training'].get('minimum_lr', 5e-6) <= event['new_lr'] <= event['old_lr'],
                    'Plateau learning rate increased or crossed the registered lower bound')
            require(event['reduced'] == (event['new_lr'] < event['old_lr']), 'Inconsistent Plateau reduction flag')
            if event['reduced']:
                require(math.isfinite(event['new_lr']) and 0 < event['new_lr'] < event['old_lr'], 'Invalid reduction')
                events[name].append({'step': h['step'], 'old_lr': event['old_lr'], 'new_lr': event['new_lr']})
        training[name] = {'steps': r['step'], 'examples_seen': r['examples_seen'], 'supervised_tokens': r['supervised_tokens'],
                          'validation_points': len(r['history']), 'selected_step': selected['step'],
                          'selected_validation_loss': selected['validation_loss'],
                          'final_validation_loss': r['history'][-1]['validation']['loss']}
        for field in ('seconds_this_invocation', 'peak_allocated_bytes', 'peak_reserved_bytes'):
            value = r[field]
            require(type(value) in (int, float) and math.isfinite(value) and value >= 0, 'Invalid resource measurement')
            training[name][field] = value
        seed = int(name[-1])
        if seed in initial:
            require(initial[seed] == r['initial_trainable_sha256'], 'Paired model initialization differs')
        initial[seed] = r['initial_trainable_sha256']
    for seed in range(3):
        left, right = f'D-seed-{seed}', f'E-seed-{seed}'
        if left not in results or right not in results:
            continue
        a, b = results[left]['config'].copy(), results[right]['config'].copy()
        a.pop('schedule'); b.pop('schedule')
        require(a == b, 'Paired configurations differ beyond scheduling')
        pairs.append(seed)
    summary = {'scope': 'completed_limited_training_endpoints_only', 'completed_runs': len(results), 'planned_runs': 6,
               'completed_paired_seeds': pairs, 'unprovided_runs': [n for n in RUNS if n not in results],
               'frozen_config_base_and_data_bindings_verified': True, 'sample_exposure_inventories_equal': True,
               'paired_initializations_and_non_schedule_configurations_verified': True,
               'observed_training_seed_initializations_distinct': len(set(initial.values())) == len(initial) if len(initial)>1 else None,
               'training': training, 'scheduler_reduction_events': events,
               'scheduler_event_timing': 'after validation at the event step; lr_used precedes that event',
               'test_deferred_for_all_provided_runs': True, 'new_hypothesis_tests_performed': False,
               'model_or_pickle_loaded': False, 'full_goal_complete': False}
    return summary, public_histories(histories)


def verify_archives(protocol, receipts, folder):
    require(protocol['scope'] == 'approved_compute_limited_30h_followup', 'Wrong protocol scope')
    require(protocol['lock_hash'] == digest({k:v for k,v in protocol.items() if k!='lock_hash'}), 'Protocol lock changed')
    require(receipts['protocol_hash'] == protocol['lock_hash'], 'Receipt protocol binding differs')
    names = set(receipts['models'])
    require(bool(names) and names <= set(RUNS), 'Unexpected endpoint receipt set')
    results, members = {}, 0
    for name in RUNS:
        if name not in names:
            continue
        path = Path(folder)/(name+'-model.tar')
        checked = verify_model_backup(path, receipts['models'][name]['sha256'])
        with tarfile.open(path) as a:
            require(a.getmember('result.json').size < 4*1024**2, 'Unexpectedly large result metadata')
            r = json.load(a.extractfile('result.json'))
            index = json.load(a.extractfile('backup-index.json'))
            require(r['selection'] == json.load(a.extractfile('model/selection.json')), 'Export selection metadata differs')
        require(index['protocol_hash'] == protocol['lock_hash'], 'Archive protocol binding differs')
        results[name] = r; members += checked['files']
    summary, histories = summarize(results, protocol)
    summary.update(all_archive_member_hashes_verified=True, verified_archive_members=members)
    return summary, histories


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--protocol', type=Path, required=True, help='Private frozen protocol lock')
    p.add_argument('--receipts', type=Path, required=True, help='Private mirror status with protocol_hash and models SHA256')
    p.add_argument('--archives', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True, help='New directory containing only scalar aggregate exports')
    a = p.parse_args()
    require(not a.out.exists(), 'Output directory already exists')
    summary, histories = verify_archives(json.loads(a.protocol.read_text(encoding='utf-8')),
                                       json.loads(a.receipts.read_text(encoding='utf-8')), a.archives)
    a.out.mkdir(parents=True, exist_ok=False)
    for name, value in [('aggregate-training.json', summary), ('training-history.json', histories)]:
        (a.out/name).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    print(json.dumps({'completed_runs':summary['completed_runs'], 'completed_paired_seeds':summary['completed_paired_seeds'],
                      'all_archive_member_hashes_verified':True, 'test_deferred':True, 'model_or_pickle_loaded':False}))


if __name__ == '__main__':
    main()
