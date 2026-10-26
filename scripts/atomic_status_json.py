"""Atomically replace a single-writer JSON journal while allowing Windows readers."""
import json
import os
from pathlib import Path
import time


def atomic_json_dump(path, value, *, attempts=8, initial_delay=0.02, maximum_delay=0.5):
    """Return replacement attempts used; preserve old JSON and pending bytes on failure.

    Only Windows sharing/access conflicts from os.replace are retried. Data
    serialization, file writes and callers' model/transport operations are not.
    The caller must ensure a single writer owns this journal.
    """
    if type(attempts) is not int or attempts < 1 or initial_delay < 0 or maximum_delay < 0:
        raise ValueError('Positive attempt count and nonnegative delays required')
    target = Path(path)
    pending = target.with_name(target.name + '.' + str(os.getpid()) + '.pending')
    raw = (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8')
    with pending.open('wb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    for attempt in range(attempts):
        try:
            os.replace(pending, target)
            return attempt + 1
        except PermissionError as exc:
            if getattr(exc, 'winerror', None) not in {5, 32, 33} or attempt + 1 == attempts:
                raise
            time.sleep(min(initial_delay * (2 ** attempt), maximum_delay))
