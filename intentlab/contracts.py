"""Public executable specifications for development tasks; no private references."""

from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import math
import unicodedata


OPERATIONS = {"decimal_round", "local_date_filter", "unicode_nfc", "stable_sort",
              "key_present", "half_open_interval", "literal_copy", "copy", "ascii_filter_project"}
PARAMETERS = {"decimal_round": {"name", "field", "places", "rounding"},
              "local_date_filter": {"name", "field", "day", "offset_minutes"},
              "half_open_interval": {"name", "field", "lower", "upper"},
              "copy": {"name"}, "ascii_filter_project": {"name", "where_field", "equals", "fields"}, **{name: {"name", "field"} for name in
                  ("unicode_nfc", "stable_sort", "key_present", "literal_copy")}}
RULES = {"preserve_inputs", "validate_before_write", "exact_outputs", "report_counts"}


def validate_spec(spec, requirements):
    if not isinstance(spec, dict) or set(spec) != {"required_fields", "operation", "requirement_rules", "dependencies"}:
        raise ValueError("Explicit execution specification required")
    if not isinstance(spec["required_fields"], list) or any(not isinstance(key, str) or not key for key in spec["required_fields"]):
        raise ValueError("Required fields must be strings")
    validate_operation(spec["operation"])
    ids = {req["id"] for req in requirements}
    rules = spec["requirement_rules"]
    if not isinstance(rules, dict) or set(rules) != ids or any(not isinstance(rule, str) for rule in rules.values()) \
            or set(rules.values()) != RULES or len(rules) != len(RULES):
        raise ValueError("One explicit rule for each of the four requirements required")
    hard_ids = {req["id"] for req in requirements if req["hard"]}
    if hard_ids != {rid for rid, rule in rules.items() if rule in {"preserve_inputs", "validate_before_write"}}:
        raise ValueError("Historical protection and order must be hard requirements")
    dependencies = spec["dependencies"]
    if not isinstance(dependencies, dict) or set(dependencies) != ids or any(
            not isinstance(values, list) or any(rid not in ids for rid in values) for values in dependencies.values()):
        raise ValueError("Dependency graph must cover exactly the public requirement IDs")


def validate_operation(operation):
    if not isinstance(operation, dict) or operation.get("name") not in OPERATIONS:
        raise ValueError("Unsupported public operation")
    if set(operation) != PARAMETERS[operation["name"]]:
        raise ValueError("Unexpected or missing public operation parameters")
    if "field" in operation and (not isinstance(operation["field"], str) or not operation["field"]):
        raise ValueError("Nonempty operation field required")
    if operation["name"] == "ascii_filter_project":
        fields, value, where = operation["fields"], operation["equals"], operation["where_field"]
        if not isinstance(where, str) or not where or not isinstance(value, str) or any(not 32 <= ord(c) <= 126 for c in value) \
                or not isinstance(fields, list) or not fields or any(not isinstance(field, str) or not field for field in fields) \
                or len(set(fields)) != len(fields):
            raise ValueError("Printable ASCII equality and unique nonempty projection fields required")


def numeric(value):
    if type(value) is int:
        return value
    if type(value) is not float or not math.isfinite(value):
        raise ValueError("Expected a finite JSON number, not a boolean")
    return value


def transform(rows, operation):
    """Rule baseline computation, deliberately separate from static offline gold."""
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Expected JSON record rows")
    validate_operation(operation)
    rows = deepcopy(rows)
    name = operation["name"]
    if name not in OPERATIONS:
        raise ValueError("Unsupported public operation")
    if name == "copy":
        return rows
    if name == "ascii_filter_project":
        where, fields = operation["where_field"], operation["fields"]
        if any(where not in row or any(field not in row for field in fields) or not isinstance(row[where], str)
               or any(not 32 <= ord(c) <= 126 for c in row[where]) for row in rows):
            raise ValueError("Projection fields and printable ASCII predicate values required")
        return [{field: row[field] for field in fields} for row in rows if row[where].lower() == operation["equals"].lower()]
    field = operation["field"]
    if name == "key_present":
        return [row for row in rows if field in row]
    if any(field not in row for row in rows):
        raise ValueError("Operation field missing")
    if name == "decimal_round":
        places = operation["places"]
        if type(places) is not int or not 0 <= places <= 8 or operation["rounding"] != "half_up":
            raise ValueError("Unsupported rounding specification")
        for row in rows:
            if not isinstance(row[field], str):
                raise ValueError("Decimal inputs must be strings")
            try:
                amount = Decimal(row[field])
                if not amount.is_finite():
                    raise ValueError("Nonfinite decimal")
                row[field] = format(amount.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP), f".{places}f")
            except InvalidOperation as exc:
                raise ValueError("Invalid decimal") from exc
        return rows
    if name == "local_date_filter":
        offset = operation["offset_minutes"]
        if type(offset) is not int or not -1439 <= offset <= 1439:
            raise ValueError("Invalid explicit UTC offset")
        target = date.fromisoformat(operation["day"])
        zone = timezone(timedelta(minutes=offset))
        selected = []
        for row in rows:
            if not isinstance(row[field], str):
                raise ValueError("Timestamp must be a string with explicit timezone")
            stamp = datetime.fromisoformat(row[field].replace("Z", "+00:00"))
            if stamp.utcoffset() is None:
                raise ValueError("Timestamp needs explicit timezone")
            if stamp.astimezone(zone).date() == target:
                selected.append(row)
        return selected
    if name == "unicode_nfc":
        for row in rows:
            if not isinstance(row[field], str):
                raise ValueError("Unicode normalization requires strings")
            row[field] = unicodedata.normalize("NFC", row[field])
        return rows
    if name == "stable_sort":
        return sorted(rows, key=lambda row: numeric(row[field]))
    if name == "half_open_interval":
        low, high = numeric(operation["lower"]), numeric(operation["upper"])
        if low >= high:
            raise ValueError("Interval must be increasing")
        return [row for row in rows if low <= numeric(row[field]) < high]
    if name == "literal_copy":
        if any(not isinstance(row[field], str) for row in rows):
            raise ValueError("Literal identifiers must remain strings")
        return rows
    raise ValueError("Unsupported operation")


def public_solution(task):
    """Engineering rule actor. Never used to build the offline reference files."""
    rows = [row for values in task["inputs"].values() for row in values]
    valid = all(all(key in row for key in task["spec"]["required_fields"]) for row in rows)
    actions = [{"op": "validate", "ok": valid}]
    if not valid:
        return actions + [{"op": "write", "path": task["report_path"],
                           "value": {"status": "blocked", "input_rows": len(rows)}}]
    output = transform(rows, task["spec"]["operation"])
    return actions + [
        {"op": "write", "path": task["output_path"], "value": output},
        {"op": "write", "path": task["report_path"], "value": {
            "status": "ok", "input_rows": len(rows), "output_rows": len(output)}}]
