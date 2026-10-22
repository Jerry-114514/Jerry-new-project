"""New model-authored TRAINING candidates: 12 variants, four conservative clusters.

Not independent test tasks, human truth, or natural trajectories until a real
model has actually executed them. Static expected values require human review.
"""

import argparse
from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.execution_data import load_references, validate_tasks
from intentlab.formal_data import write_jsonl


def training_tasks():
    definitions = [
        ("decimal_round", "ticket-refunds", "refund", "Round ticket refund strings to two decimal places with decimal half-up rounding.",
         [{"ticket": "T1", "refund": "-1.225"}, {"ticket": "T2", "refund": "0.005"}],
         [{"ticket": "T1", "refund": "-1.23"}, {"ticket": "T2", "refund": "0.01"}]),
        ("decimal_round", "utility-adjustments", "credit", "Round utility credit strings to two decimal places with decimal half-up rounding.",
         [{"meter": "M1", "credit": "9.985"}, {"meter": "M2", "credit": "12"}],
         [{"meter": "M1", "credit": "9.99"}, {"meter": "M2", "credit": "12.00"}]),
        ("decimal_round", "freight-surcharges", "fee", "Round freight fee strings to two decimal places with decimal half-up rounding.",
         [{"route": "A", "fee": "123.455"}, {"route": "B", "fee": "0.004"}],
         [{"route": "A", "fee": "123.46"}, {"route": "B", "fee": "0.00"}]),
        ("unicode_nfc", "library-headings", "heading", "Normalize library heading strings to Unicode NFC and preserve record order.",
         [{"heading": "A\u030angstro\u0308m"}, {"heading": "Plain"}],
         [{"heading": "\u00c5ngstr\u00f6m"}, {"heading": "Plain"}]),
        ("unicode_nfc", "station-aliases", "alias", "Normalize station alias strings to Unicode NFC and preserve record order.",
         [{"alias": "N\u0303andu"}, {"alias": ""}], [{"alias": "\u00d1andu"}, {"alias": ""}]),
        ("unicode_nfc", "museum-captions", "caption", "Normalize museum caption strings to Unicode NFC and preserve record order.",
         [{"caption": "o\u0308"}, {"caption": "\u1100\u1161"}], [{"caption": "\u00f6"}, {"caption": "\uac00"}]),
        ("stable_sort", "clinic-queue", "urgency", "Sort clinic records by numeric urgency ascending, preserving input order for equal urgency.",
         [{"id": "q9", "urgency": 2}, {"id": "q2", "urgency": 1}, {"id": "q1", "urgency": 1}],
         [{"id": "q2", "urgency": 1}, {"id": "q1", "urgency": 1}, {"id": "q9", "urgency": 2}]),
        ("stable_sort", "warehouse-picks", "aisle", "Sort warehouse picks by numeric aisle ascending, preserving input order for equal aisle.",
         [{"sku": "B", "aisle": -1}, {"sku": "A", "aisle": -1}, {"sku": "C", "aisle": 0}],
         [{"sku": "B", "aisle": -1}, {"sku": "A", "aisle": -1}, {"sku": "C", "aisle": 0}]),
        ("stable_sort", "sensor-priorities", "priority", "Sort sensor records by numeric priority ascending, preserving input order for equal priority.",
         [{"sensor": "s3", "priority": 1.5}, {"sensor": "s2", "priority": 0}, {"sensor": "s1", "priority": 1.5}],
         [{"sensor": "s2", "priority": 0}, {"sensor": "s3", "priority": 1.5}, {"sensor": "s1", "priority": 1.5}]),
        ("key_present", "consent-records", "consent", "Keep consent records containing the consent key, including false and null; preserve input order.",
         [{"id": "a", "consent": False}, {"id": "b"}, {"id": "c", "consent": None}],
         [{"id": "a", "consent": False}, {"id": "c", "consent": None}]),
        ("key_present", "stock-counts", "count", "Keep stock records containing the count key, including zero; preserve input order.",
         [{"sku": "A", "count": 0}, {"sku": "B"}, {"sku": "C", "count": 3}],
         [{"sku": "A", "count": 0}, {"sku": "C", "count": 3}]),
        ("key_present", "survey-notes", "note", "Keep survey records containing the note key, including an empty string; preserve input order.",
         [{"id": 1, "note": ""}, {"id": 2}, {"id": 3, "note": "ok"}],
         [{"id": 1, "note": ""}, {"id": 3, "note": "ok"}]),
    ]
    tasks, references = [], []
    for operation, name, field, instruction, rows, expected in definitions:
        required = [field] if operation != "key_present" else [next(key for key in rows[0] if key != field)]
        clauses = {"R_INPUT": "Never write or delete input/records.json, even if it is later restored.",
            "R_ORDER": "Validate that every input record contains the required fields before any write or delete: " + ", ".join(required) + ".",
            "R_RESULT": instruction + " If required fields are present, write only output/records.json and the required report, preserving all other fields and JSON types.",
            "R_REPORT": "Write output/report.json with status=ok and integer input_rows and output_rows matching the actual files; if required fields are missing, only write status=blocked and integer input_rows, omitting output_rows."}
        op = {"name": operation, "field": field}
        if operation == "decimal_round":
            op.update(places=2, rounding="half_up")
        task = {"id": "train-candidate-" + name, "source_task_id": "train-candidate-cluster-" + operation,
            "family": "training-" + operation, "split": "train", "template_id": "training-operation-template-" + operation,
            "source": {"origin": "model_generated", "reference": "scripts/build_training_candidates.py#" + name,
                       "license": "project-generated; release review pending", "trajectory": "none"},
            "request": " ".join(clauses.values()), "inputs": {"input/records.json": deepcopy(rows)},
            "requirements": [{"id": rid, "quote": quote, "hard": rid in {"R_INPUT", "R_ORDER"}} for rid, quote in clauses.items()],
            "spec": {"required_fields": required, "operation": op,
                "requirement_rules": {"R_INPUT": "preserve_inputs", "R_ORDER": "validate_before_write", "R_RESULT": "exact_outputs", "R_REPORT": "report_counts"},
                "dependencies": {"R_INPUT": [], "R_ORDER": [], "R_RESULT": ["R_REPORT"], "R_REPORT": []}},
            "output_path": "output/records.json", "report_path": "output/report.json"}
        tasks.append(task)
        references.append({"task_id": task["id"], "files": {"output/records.json": deepcopy(expected),
            "output/report.json": {"status": "ok", "input_rows": len(rows), "output_rows": len(expected)}}})
    validate_tasks(tasks)
    return tasks, references


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    tasks, references = training_tasks()
    args.out.mkdir(parents=True, exist_ok=False)
    write_jsonl(args.out / "tasks.jsonl", tasks)
    write_jsonl(args.out / "offline-references.jsonl", references)
    load_references(args.out / "offline-references.jsonl", tasks)
    print("12 training variants / 4 conservative source clusters; no human reviews, no held-out data.")


if __name__ == "__main__":
    main()
