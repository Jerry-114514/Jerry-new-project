"""Replay archived engineering diagnostic scores/loss totals without ML weights."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.core import canonical, digest
from intentlab.diagnostic_protocol import CONDITIONS, rule_predictions
from intentlab.execution_protocol import contract_identity
from intentlab.formal_data import read_jsonl
from intentlab.formal_eval import paired_task_bootstrap, score_predictions


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def audit(root):
    root = Path(root)
    matrix = root / "matrix"
    protocol = read(matrix / "protocol.engineering.lock.json")
    binding = read(matrix / "execution-model-lock.json")
    if protocol["scope"] != "engineering" or binding["scope"] != "engineering":
        raise ValueError("This replay is only for public synthetic engineering evidence")
    pred, result = matrix / "diagnostic-predictions", matrix / "diagnostic-reveal"
    sealed, receipt = read(pred / "manifest.json"), read(result / "manifest.json")
    for directory, record, field, status in ((pred, sealed, "seal_hash", "sealed"), (result, receipt, "receipt_hash", "completed")):
        actual = {p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in directory.rglob("*") if p.is_file() and p != directory / "manifest.json"}
        if record["scope"] != "engineering" or record["status"] != status \
                or record["protocol_hash"] != protocol["lock_hash"] or record["model_binding_hash"] != binding["binding_hash"] \
                or record[field] != digest({k: v for k, v in record.items() if k != field}) \
                or record["files_sha256"] != actual:
            raise ValueError("Diagnostic seal, receipt or archived output changed")
    if sealed["conditions"] != CONDITIONS or sealed["test_backend_injected"] or receipt["test_loss_injected"] \
            or sealed["gold_loaded"] or receipt["prediction_seal_hash"] != sealed["seal_hash"]:
        raise ValueError("Not the claimed real tiny-model diagnostic flow")
    cases = read_jsonl(matrix / "diagnostic-inputs/cases.jsonl")
    examples = read(matrix / "diagnostic-inputs/examples.json")
    if digest(cases) != sealed["cases_hash"] or digest(examples) != sealed["examples_hash"]:
        raise ValueError("Archived engineering public inputs differ")
    raw_gold = read_jsonl(matrix / "diagnostic-inputs/gold.jsonl")
    gold = {row["case_id"]: row["findings"] for row in raw_gold}
    if len(gold) != len(raw_gold) or set(gold) != {row["case_id"] for row in cases}:
        raise ValueError("Engineering gold coverage differs")
    for split in ("test", "ood"):
        # Original export order follows case order, not arbitrary archive order.
        ordered = [{"case_id": case["case_id"], "findings": gold[case["case_id"]]} for case in cases if case["split"] == split]
        raw = "".join(canonical(row) + "\n" for row in ordered).encode("utf-8")
        if hashlib.sha256(raw).hexdigest() != protocol["dataset_export"]["files_sha256"][f"heldout/{split}/gold.jsonl"]:
            raise ValueError("Archived gold differs from frozen synthetic export")
    scores = {}
    for condition in CONDITIONS:
        predictions = read_jsonl(pred / condition / "predictions.jsonl")
        if len(predictions) != len(cases) or {row["case_id"] for row in predictions} != set(gold):
            raise ValueError("Missing or duplicate diagnostic prediction")
        scores[condition] = {}
        for split in ("test", "ood"):
            subset = [row for row in cases if row["split"] == split]
            ids = {row["case_id"] for row in subset}
            scores[condition][split] = score_predictions(subset, {cid: gold[cid] for cid in ids},
                [row for row in predictions if row["case_id"] in ids])
    if canonical(scores) != canonical(read(result / "scores.json")):
        raise ValueError("Diagnostic score replay differs")
    tasks = read_jsonl(matrix / "diagnostic-inputs/tasks.jsonl")
    indexed = {contract_identity(task, dict(request=task["request"], inputs=task["inputs"],
        requirements=task["requirements"], execution_spec=task["spec"])): task for task in tasks}
    with tempfile.TemporaryDirectory() as name:
        rule_predictions(cases, indexed, Path(name) / "rule")
        if read_jsonl(Path(name) / "rule/predictions.jsonl") != read_jsonl(pred / "C/predictions.jsonl"):
            raise ValueError("Public-rule prediction replay differs")
    losses, populations = {}, None
    for condition in CONDITIONS[3:]:
        rows = read_jsonl(result / (condition + "-loss.jsonl"))
        indexed = {row["case_id"]: row for row in rows}
        if len(rows) != len(indexed) or set(indexed) != set(gold):
            raise ValueError("Incomplete archived losses")
        for case in cases:
            row = indexed[case["case_id"]]
            if row["split"] != case["split"] or row["source_task_id"] != case["source_task_id"] \
                    or type(row["target_tokens"]) is not int or row["target_tokens"] < 1 \
                    or not math.isfinite(row["loss_sum"]) or row["loss_sum"] < 0:
                raise ValueError("Invalid archived per-case loss")
        counts = {cid: row["target_tokens"] for cid, row in indexed.items()}
        if populations is not None and counts != populations:
            raise ValueError("Different D/E target populations")
        populations = counts
        losses[condition] = {}
        for split in ("test", "ood"):
            group = [row for row in rows if row["split"] == split]
            total, count = sum(row["loss_sum"] for row in group), sum(row["target_tokens"] for row in group)
            losses[condition][split] = {"loss_sum": total, "target_tokens": count, "loss": total / count}
    if canonical(losses) != canonical(read(result / "losses.json")):
        raise ValueError("Recomputed token-weighted totals differ")
    stats = protocol["spec"]["statistics"]
    comparisons = {condition: {split: paired_task_bootstrap(scores["B"][split]["per_task_error_rate"],
        scores[condition][split]["per_task_error_rate"], seed=stats["bootstrap_seed"], samples=stats["bootstrap_samples"])
        for split in ("test", "ood")} for condition in CONDITIONS[3:6]}
    if canonical(comparisons) != canonical(read(result / "rq1-per-seed.json")):
        raise ValueError("Task bootstrap replay differs")
    return {"scope": "engineering", "diagnostic_conditions": len(CONDITIONS), "public_cases": len(cases),
        "prediction_records": len(CONDITIONS) * len(cases), "loss_records": 6 * len(cases),
        "scores_rule_predictions_loss_totals_and_bootstrap_replayed": True, "model_forward_recomputed": False,
        "human_reviews_completed": 0, "formal_9b_training": False,
        "warning": "Original tiny CPU forward losses were recorded live; weights are not archived. Summed loss replay is not recomputation of model logits, durable backup, formal data or efficacy evidence."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path("examples/results/formal-m1j-diagnostic-protocol"))
    args = parser.parse_args()
    subprocess.run([sys.executable, str(Path(__file__).with_name("audit_execution_binding_evidence.py")),
                    "--root", str(args.root)], check=True)
    report = audit(args.root)
    (args.root / "diagnostic-verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    sums = {p.relative_to(args.root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(args.root.rglob("*")) if p.is_file() and p.name != "checksums.json"}
    (args.root / "checksums.json").write_text(json.dumps(sums, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
