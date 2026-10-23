"""Separate reference computation for the finite, encoded operation set.

No imports of the online solver/analyzer. Standard-library numerical/Unicode
primitives remain shared dependencies, not independent formal proofs.
"""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from fractions import Fraction
import math
import sqlite3
import unicodedata

from .core import canonical, digest


def reference_files(task):
    rows = [deepcopy(row) for values in task['inputs'].values() for row in values]
    report = {'input_rows': len(rows)}
    if any(field not in row for row in rows for field in task['spec']['required_fields']):
        return {task['report_path']: dict(report, status='blocked')}
    op = task['spec']['operation']
    name, field = op['name'], op.get('field')
    def number(value):
        if type(value) is int:
            return value
        if type(value) is not float or not math.isfinite(value):
            raise ValueError('Finite nonboolean number required')
        return value
    if name == 'ascii_filter_project':
        if any(key not in row for row in rows for key in [op['where_field']] + op['fields']):
            raise ValueError('Predicate/projection fields missing')
        # SQLite NOCASE is ASCII-only. Restrict inputs explicitly to the same
        # printable domain; use independently parameterized SQL, not str.lower.
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE data (position INTEGER, value TEXT, payload TEXT)')
            for i, row in enumerate(rows):
                value = row[op['where_field']]
                if not isinstance(value, str) or any(not 32 <= ord(c) <= 126 for c in value):
                    raise ValueError('Printable ASCII predicate required')
                db.execute('INSERT INTO data VALUES (?, ?, ?)', (i, value, canonical(row)))
            import json
            selected = db.execute('SELECT payload FROM data WHERE value = ? COLLATE NOCASE ORDER BY position', (op['equals'],)).fetchall()
            rows = [{key: json.loads(payload)[key] for key in op['fields']} for (payload,) in selected]
    elif name == 'decimal_round':
        places = op['places']
        if type(places) is not int or not 0 <= places <= 8 or op['rounding'] != 'half_up':
            raise ValueError('Unsupported decimal reference specification')
        for row in rows:
            text = row[field]
            if not isinstance(text, str):
                raise ValueError('Decimal string required')
            value = Fraction(text)
            scaled = abs(value) * 10**places
            magnitude, remainder = divmod(scaled.numerator, scaled.denominator)
            magnitude += 2 * remainder >= scaled.denominator
            negative = value < 0 or (value == 0 and text.strip().startswith('-'))
            digits = str(magnitude).zfill(places + 1)
            row[field] = ('-' if negative else '') + (digits[:-places] + '.' + digits[-places:] if places else digits)
    elif name == 'local_date_filter':
        offset = op['offset_minutes']
        if type(offset) is not int or not -1439 <= offset <= 1439:
            raise ValueError('Invalid explicit offset')
        target_day = date.fromisoformat(op['day']).isoformat()
        chosen = []
        for row in rows:
            stamp = datetime.fromisoformat(row[field].replace('Z', '+00:00'))
            if stamp.utcoffset() is None:
                raise ValueError('Explicit timestamp offset required')
            local = stamp.astimezone(timezone.utc).replace(tzinfo=None) + timedelta(minutes=offset)
            if local.date().isoformat() == target_day:
                chosen.append(row)
        rows = chosen
    elif name == 'unicode_nfc':
        for row in rows:
            row[field] = unicodedata.normalize('NFC', row[field])
    elif name == 'stable_sort':
        # Stable insertion sort, distinct from the public solver's sorted().
        chosen = []
        for row in rows:
            key = number(row[field])
            index = 0
            while index < len(chosen) and number(chosen[index][field]) <= key:
                index += 1
            chosen.insert(index, row)
        rows = chosen
    elif name == 'key_present':
        rows = list(filter(lambda row: field in row.keys(), rows))
    elif name == 'half_open_interval':
        low, high = number(op['lower']), number(op['upper'])
        if low >= high:
            raise ValueError('Increasing interval required')
        rows = [row for row in rows if not (number(row[field]) < low or number(row[field]) >= high)]
    elif name == 'literal_copy':
        if any(not isinstance(row[field], str) for row in rows):
            raise ValueError('Literal strings required')
    elif name != 'copy':
        raise ValueError('Independent reference operation not implemented')
    return {task['output_path']: rows, task['report_path']: dict(report, status='ok', output_rows=len(rows))}


def verify_references(tasks, references):
    if set(references) != {t['id'] for t in tasks}:
        raise ValueError('Independent reference task coverage mismatch')
    for task in tasks:
        if canonical(reference_files(task)) != canonical(references[task['id']]['files']):
            raise ValueError('Independent reference disagreement: ' + task['id'])
    return {'kind': 'independent_encoded_spec_reference_check', 'tasks': len(tasks),
        'tasks_hash': digest(tasks), 'references_hash': digest(references),
        'operations': sorted({t['spec']['operation']['name'] for t in tasks}),
        'formal_proof': False}
