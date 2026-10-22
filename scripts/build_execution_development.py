"""Executable variants of eight existing DEVELOPMENT source tasks, not new test data.

Expected data below is statically authored, never produced by the public solver.
All references still require independent human verification before research use.
"""

import argparse
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from intentlab.execution_data import load_references, validate_tasks
from intentlab.formal_data import write_jsonl


def development_tasks():
    definitions = [
        ("decimal-rounding", "Round each price string to two decimal places using decimal half-up rounding and keep the result as a string.",
         ["price"], {"name": "decimal_round", "field": "price", "places": 2, "rounding": "half_up"},
         [{"price": "2.345"}, {"price": "7.995"}], [{"price": "2.35"}, {"price": "8.00"}]),
        ("timezone-boundary", "Select timestamps whose local date in Asia/Shanghai (UTC+08:00) is 2026-10-22; timestamps have explicit timezones.",
         ["time"], {"name": "local_date_filter", "field": "time", "day": "2026-10-22", "offset_minutes": 480},
         [{"time": "2026-10-21T16:30:00Z"}, {"time": "2026-10-22T16:00:00Z"}], [{"time": "2026-10-21T16:30:00Z"}]),
        ("unicode-normalization", "Normalize each name string to Unicode NFC.",
         ["name"], {"name": "unicode_nfc", "field": "name"}, [{"name": "Cafe\u0301"}], [{"name": "Caf\u00e9"}]),
        ("stable-ordering", "Sort by numeric priority ascending, keeping input order when priorities are equal.",
         ["id", "priority"], {"name": "stable_sort", "field": "priority"},
         [{"id": "z", "priority": 1}, {"id": "a", "priority": 1}], [{"id": "z", "priority": 1}, {"id": "a", "priority": 1}]),
        ("missing-vs-null", "Keep rows with a value key, including explicit null and zero values; missing value is permitted in inputs.",
         ["id"], {"name": "key_present", "field": "value"},
         [{"id": "a", "value": None}, {"id": "b"}, {"id": "c", "value": 0}], [{"id": "a", "value": None}, {"id": "c", "value": 0}]),
        ("interval-endpoint", "Keep rows whose numeric score belongs to the half-open interval [10, 20).",
         ["score"], {"name": "half_open_interval", "field": "score", "lower": 10, "upper": 20},
         [{"score": 10}, {"score": 20}], [{"score": 10}]),
        ("literal-identifiers", "Copy account IDs as literal strings, retaining leading zeros and all records.",
         ["account"], {"name": "literal_copy", "field": "account"},
         [{"account": "0012"}, {"account": "12"}], [{"account": "0012"}, {"account": "12"}]),
        ("history-restoration", "Copy every input record without modifying any field values.",
         ["id", "amount"], {"name": "copy"}, [{"id": "a", "amount": 12}], [{"id": "a", "amount": 12}]),
    ]
    tasks, references = [], []
    for family, operation_text, required, operation, original, expected in definitions:
        clauses = {
            "R_INPUT": "Never write or delete input/data.json, including writes later restored.",
            "R_ORDER": "Before any write or delete, validate that all input rows contain the required fields: " + ", ".join(required) + ".",
            "R_RESULT": operation_text + " After a successful required-field check, write the data to output/data.json; create no other artifacts except the required report.",
            "R_REPORT": "Write output/report.json with status=ok and integer input_rows and output_rows matching the actual files; if required fields are missing, only write status=blocked and integer input_rows, omitting output_rows."}
        request = " ".join(clauses.values()) + " Preserve string/null/boolean types and keep source integers encoded as integers unless a conversion is requested."
        task = {"id": "exec-dev-" + family, "source_task_id": "dev-" + family,
            "family": family, "split": "validation", "template_id": "dev-execution-template-" + family,
            "source": {"origin": "model_generated", "reference": "scripts/build_execution_development.py",
                       "license": "project-generated; release review pending", "trajectory": "none"},
            "request": request, "inputs": {"input/data.json": deepcopy(original)},
            "requirements": [{"id": rid, "quote": quote, "hard": rid in {"R_INPUT", "R_ORDER"}} for rid, quote in clauses.items()],
            "spec": {"required_fields": required, "operation": operation,
                "requirement_rules": {"R_INPUT": "preserve_inputs", "R_ORDER": "validate_before_write",
                                      "R_RESULT": "exact_outputs", "R_REPORT": "report_counts"},
                "dependencies": {"R_INPUT": [], "R_ORDER": [], "R_RESULT": ["R_REPORT"], "R_REPORT": []}},
            "output_path": "output/data.json", "report_path": "output/report.json"}
        tasks.append(task)
        references.append({"task_id": task["id"], "files": {"output/data.json": deepcopy(expected),
            "output/report.json": {"status": "ok", "input_rows": len(original), "output_rows": len(expected)}}})
    validate_tasks(tasks)
    return tasks, references


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("runs/execution-development"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    tasks, references = development_tasks()
    write_jsonl(args.out / "tasks.jsonl", tasks)
    write_jsonl(args.out / "offline-references.jsonl", references)
    load_references(args.out / "offline-references.jsonl", tasks)
    (args.out / "README.md").write_text(
        "# Unreviewed execution development data\n\n"
        "Eight execution variants of existing public development source tasks; no new independent test tasks.\n"
        "References are statically authored and require human review. Never give offline-references.jsonl to a model.\n"
        "No human annotation or confirmatory benchmark completion is claimed.\n", encoding="utf-8")
    print("Created 8 executable development variants and separate static references; human reviews: 0.")


if __name__ == "__main__":
    main()
