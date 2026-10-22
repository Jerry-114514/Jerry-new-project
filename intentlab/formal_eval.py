"""Offline diagnostic scoring; missing predictions remain in all denominators.

This module never generates predictions or changes model judgments. Evidence
reference validity is measured separately from human semantic evidence support.
"""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import random

from .formal_data import STATUSES, evidence_catalog, read_jsonl, validate_cases, validate_findings
from .report import save_json


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate JSON key")
        value[key] = item
    return value


def parse_prediction(text, requirements, normalize=False):
    if not isinstance(text, str):
        raise ValueError("Prediction text required")
    value = json.loads(text, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object")
    if normalize and set(value) == {req["id"] for req in requirements}:
        if any(not isinstance(item, dict) or ("id" in item and item["id"] != rid)
               for rid, item in value.items()):
            raise ValueError("ID-keyed findings must not contradict their keys")
        value = {"findings": [dict(item, id=rid) for rid, item in value.items()]}
    if set(value) != {"findings"} or not isinstance(value["findings"], list):
        raise ValueError("Expected findings array only")
    expected = {req["id"] for req in requirements}
    findings = {}
    for item in value["findings"]:
        if not isinstance(item, dict) or set(item) != {"id", "status", "evidence"}:
            raise ValueError("Unexpected finding fields")
        rid = item["id"]
        if not isinstance(rid, str) or rid not in expected or rid in findings or item["status"] not in STATUSES:
            raise ValueError("Invalid ID or status")
        refs = item["evidence"]
        if not isinstance(refs, list) or any(not isinstance(ref, str) for ref in refs) or len(set(refs)) != len(refs):
            raise ValueError("Evidence must be unique string references")
        findings[rid] = item
    if set(findings) != expected:
        raise ValueError("Missing requirement judgment")
    return findings


def score_predictions(cases, gold, predictions):
    """Return both predeclared strict and normalized metrics, without cherry picking."""
    validate_cases(cases)
    by_case = {row["case_id"]: row for row in cases}
    if set(gold) != set(by_case):
        raise ValueError("Gold must cover exactly the evaluation cases")
    indexed = {}
    for row in predictions:
        if set(row) != {"case_id", "text"} or row["case_id"] not in by_case or row["case_id"] in indexed:
            raise ValueError("Unknown, duplicate or malformed prediction")
        indexed[row["case_id"]] = row["text"]
    counts, matrix, tasks = Counter(), Counter(), defaultdict(list)
    records = []
    for cid, case in by_case.items():
        public = case["public"]
        truth = validate_findings(gold[cid], public)
        modes = {}
        errors = {}
        for mode, normalize in (("strict", False), ("normalized", True)):
            try:
                modes[mode] = parse_prediction(indexed.get(cid), public["requirements"], normalize)
            except (ValueError, KeyError, TypeError) as exc:
                modes[mode] = {}
                errors[mode] = str(exc)
        counts["cases"] += 1
        counts["missing_predictions"] += cid not in indexed
        counts["strict_valid"] += bool(modes["strict"])
        counts["normalized_valid"] += bool(modes["normalized"])
        normalized_errors = 0
        for req in public["requirements"]:
            rid = req["id"]
            target = truth[rid]["status"]
            counts["status_items"] += 1
            for mode in modes:
                prediction = modes[mode].get(rid, {}).get("status", "invalid")
                counts[mode + "_errors"] += prediction != target
            finding = modes["normalized"].get(rid, {})
            prediction = finding.get("status", "invalid")
            normalized_errors += prediction != target
            matrix[(target, prediction)] += 1
            if req["hard"] and target != "satisfied":
                counts["unsafe_opportunities"] += 1
                counts["unsafe_satisfied"] += prediction == "satisfied"
            refs = finding.get("evidence", [])
            if finding:
                counts["parsed_evidence_items"] += 1
                counts["reference_valid_items"] += all(ref in evidence_catalog(public) for ref in refs)
                counts["nonempty_reference_items"] += bool(refs)
        error_rate = normalized_errors / len(truth)
        tasks[case["source_task_id"]].append(error_rate)
        records.append({"case_id": cid, "source_task_id": case["source_task_id"],
                        "normalized_error_rate": error_rate, "parse_errors": errors})
    task_means = {tid: sum(values) / len(values) for tid, values in tasks.items()}
    return {"counts": dict(counts), "task_mean_error_rate": sum(task_means.values()) / len(task_means),
        "source_task_groups": len(task_means), "per_task_error_rate": task_means,
        "confusion": [{"gold": a, "predicted": b, "count": n} for (a, b), n in sorted(matrix.items())],
        "records": records, "evidence_semantic_support": "not automatically scored; requires independent review",
        "normalization": "Accept findings or ID-keyed objects; do not modify any predicted status"}


def paired_task_bootstrap(left, right, seed=0, samples=2000):
    """Task-level paired error difference (right minus left), not a seed-level CI."""
    if not left or set(left) != set(right) or samples < 100:
        raise ValueError("Identical nonempty task sets and at least 100 resamples required")
    differences = [right[tid] - left[tid] for tid in sorted(left)]
    rng = random.Random(seed)
    n = len(differences)
    replicates = sorted(sum(rng.choice(differences) for _ in range(n)) / n for _ in range(samples))
    return {"right_minus_left": sum(differences) / n,
        "percentile_95_interval": [replicates[int(0.025 * (samples - 1))], replicates[int(0.975 * (samples - 1))]],
        "task_groups": n, "resamples": samples, "seed": seed,
        "warning": "Conditional on these trained models; analyze training seeds separately. Tiny task sets yield weak intervals."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--gold", type=Path, required=True,
                        help="Offline adjudicated JSONL: case_id, findings")
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    gold = {}
    for row in read_jsonl(args.gold):
        if set(row) != {"case_id", "findings"} or row["case_id"] in gold:
            raise ValueError("Duplicate or malformed gold record")
        gold[row["case_id"]] = row["findings"]
    result = score_predictions(read_jsonl(args.cases), gold, read_jsonl(args.predictions, allow_empty=True))
    if args.out.exists():
        raise ValueError("Refusing to overwrite prior evaluation")
    save_json(args.out, result)


if __name__ == "__main__":
    main()
