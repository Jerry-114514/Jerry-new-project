"""Enforce explicit repair constraints from public rules and trusted tool events.

This is not a learned judge and never reads fixture answers. Initial deliberately
flawed actor traces remain part of the research fixtures; this guards repairs.
"""

from .core import canonical


def repair_hard_guard(task, before, candidate):
    count = len(before.events)
    if canonical(candidate.events[:count]) != canonical(before.events):
        return False, 'hard_guard_history_changed'
    protected = set(task['inputs'])
    last_check = next((e['ok'] for e in reversed(before.events) if e['op'] == 'validate'), None)
    for event in candidate.events[count:]:
        if event['op'] == 'validate':
            last_check = event['ok']
        elif event['op'] in {'write', 'delete'}:
            if event['path'] in protected:
                return False, 'hard_guard_input_mutation'
            failure_report = (last_check is False and event['op'] == 'write'
                              and event['path'] == task['report_path'])
            if last_check is not True and not failure_report:
                return False, 'hard_guard_validation_order'
    for path in protected:
        if (path in before.files) != (path in candidate.files) or canonical(before.files.get(path)) != canonical(candidate.files.get(path)):
            return False, 'hard_guard_input_snapshot_changed'
    return True, 'hard_guard_passed'
