"""Separate reference computation for the finite, encoded operation set.

No imports of the online solver/analyzer. Standard-library numerical/Unicode
primitives remain shared dependencies, not independent formal proofs.
"""
from copy import deepcopy
from contextlib import closing
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
        with closing(sqlite3.connect(':memory:')) as db:
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
    elif name == 'date_format':
        formats = {'%Y-%m-%d': ('-', (0, 1, 2)), '%d/%m/%Y': ('/', (2, 1, 0)), '%Y%m%d': (None, None)}
        separator, order = formats[op['input_format']]
        for row in rows:
            text = row[field]
            if not isinstance(text, str):
                raise ValueError('Calendar date string required')
            parts = text.split(separator) if separator else [text[:4], text[4:6], text[6:]]
            if order:
                parts = [parts[i] for i in order]
            if len(parts) != 3 or list(map(len, parts)) != [4, 2, 2] or any(not p.isascii() or not p.isdigit() for p in parts):
                raise ValueError('Exact-width calendar date required')
            year, month, day = map(int, parts)
            date(year, month, day)
            if op['output_format'] == '%Y%m%d':
                row[field] = f'{year:04d}{month:02d}{day:02d}'
            elif op['output_format'] == '%d.%m.%Y':
                row[field] = f'{day:02d}.{month:02d}.{year:04d}'
            elif op['output_format'] == '%Y-%m-%d':
                row[field] = f'{year:04d}-{month:02d}-{day:02d}'
            else:
                raise ValueError('Unsupported output date format')
    elif name == 'stable_unique':
        def equal(a, b):
            if type(a) is not type(b): return False
            if isinstance(a, list): return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
            if isinstance(a, dict): return set(a) == set(b) and all(equal(a[k], b[k]) for k in a)
            if isinstance(a, float): return repr(a) == repr(b)
            return a == b
        chosen = []
        for row in rows:
            if not any(equal(row[field], prior[field]) for prior in chosen):
                chosen.append(row)
        rows = chosen
    elif name == 'conditional_group_sum':
        group, value = op['group_field'], op['value_field']
        if len(rows) > 10000 or any(not isinstance(r[group], str) or type(r[value]) is not int or not -(2**31) <= r[value] < 2**31 for r in rows):
            raise ValueError('Bounded integer grouped-sum domain required')
        with closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE amounts (position INTEGER, group_name TEXT, amount INTEGER)')
            db.executemany('INSERT INTO amounts VALUES (?, ?, ?)', [(i, r[group], r[value]) for i, r in enumerate(rows)])
            found = db.execute('SELECT group_name, SUM(amount) FROM amounts WHERE amount >= ? GROUP BY group_name ORDER BY MIN(position)', (op['minimum'],)).fetchall()
        rows = [{'group': group_name, 'total': amount} for group_name, amount in found]
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
