"""Explicit condition-boundary recovery of interrupted frozen interactions.

The coordinator must archive the old attempt, verify original process exit,
validate the complete ordered prefix, and preserve the interrupted condition.
Only whole completed conditions are reused. No outcome-based row selection.
The scientific loop is taken verbatim from the frozen function; narrowly
enumerated changes reopen the verified prefix and skip complete conditions.
"""
from copy import deepcopy
import hashlib
import math


def build_resume_interact(source, namespace, recovery):
    if hashlib.sha256(source.encode()).hexdigest() != recovery['source_sha256']:
        raise ValueError('Frozen interaction function identity mismatch')
    manifest = recovery['manifest']
    conditions = list(manifest['conditions'])
    completed = recovery['completed_conditions']
    if manifest['status'] != 'running' or manifest.get('model_residency') != 'shared-condition-v1' \
            or not completed or len(completed) >= len(conditions) or completed != conditions[:len(completed)] \
            or set(manifest['condition_timings']) != set(completed):
        raise ValueError('Only a nonempty whole-condition prefix may be retained')
    seconds = sum(manifest['condition_timings'][c]['seconds_including_loading_and_release'] for c in completed)
    if not math.isfinite(seconds) or seconds < 0 or recovery['completed_seconds'] != seconds:
        raise ValueError('Completed-condition timing mismatch')
    if '_recovery_state' in source:
        raise ValueError('Unexpected recovery variable in frozen source')
    replacements = [
        ('    if out.exists():\n        raise ValueError("Choose a fresh frozen execution directory")\n',
         '    if not out.is_dir():\n        raise ValueError("Recovery requires the original execution directory")\n'
         '    if file_hash(out / "interactions.jsonl") != _recovery_state["prefix_sha256"]:\n'
         '        raise ValueError("Retained complete-condition prefix changed")\n'),
        ('    attempt = claim(protocol, prefix + "-interactions", out)\n',
         '    attempt = _recovery_state["manifest"]["claim"]\n'),
        ('    out.mkdir(parents=True, exist_ok=False)\n', ''),
        ('    save_json(out / "manifest.json", manifest)\n    pool, started = None, time.perf_counter()\n',
         '    manifest.update(deepcopy(_recovery_state["manifest"]))\n'
         '    manifest.update(status="running", recovery={\n'
         '        "completed_conditions_retained": list(_recovery_state["completed_conditions"]),\n'
         '        "interrupted_attempt_archive_sha256": _recovery_state["archive_sha256"],\n'
         '        "retained_prefix_sha256": _recovery_state["prefix_sha256"],\n'
         '        "partial_condition_records_preserved_separately": _recovery_state["ignored_partial_records"],\n'
         '        "incomplete_condition_restarted_in_full": True,\n'
         '        "frozen_interact_source_sha256": _recovery_state["source_sha256"]})\n'
         '    save_json(out / "manifest.json", manifest)\n'
         '    pool, started = None, time.perf_counter() - _recovery_state["completed_seconds"]\n'),
        ('        with (out / "interactions.jsonl").open("x", encoding="utf-8", newline="\\n") as stream:\n',
         '        with (out / "interactions.jsonl").open("a", encoding="utf-8", newline="\\n") as stream:\n'),
        ('            for condition, config in conditions.items():\n',
         '            for condition, config in conditions.items():\n'
         '                if condition in _recovery_state["completed_conditions"]:\n'
         '                    continue\n'),
    ]
    changed = source
    for before, after in replacements:
        if changed.count(before) != 1:
            raise ValueError('Frozen source shape differs; do not guess a recovery patch')
        changed = changed.replace(before, after, 1)
    scope = dict(namespace, _recovery_state=deepcopy(recovery))
    exec(compile(changed, '<explicit-condition-boundary-recovery>', 'exec'), scope)
    return scope['interact'], {'original_function_sha256': recovery['source_sha256'],
                               'recovery_function_sha256': hashlib.sha256(changed.encode()).hexdigest(),
                               'enumerated_replacements': len(replacements)}
