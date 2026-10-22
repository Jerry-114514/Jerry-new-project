"""Recompute diagnostic interface/reference lookup metrics without semantic gold."""

from collections import Counter, defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from intentlab.core import digest
from intentlab.execution_audit import audit_ledger
from intentlab.formal_data import formal_prompt, read_jsonl, validate_cases, validate_findings
from intentlab.formal_eval import parse_prediction
from intentlab.diagnostic_protocol import rule_predictions
from intentlab.execution_data import load_execution_tasks
from intentlab.execution_protocol import contract_identity


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def rule_inputs(root, cases):
    validate_cases(cases)
    if any(case["split"] != "train" for case in cases):
        raise ValueError("Public rule collection here is restricted to this train-only batch")
    tasks = load_execution_tasks(root / "tasks.jsonl")
    indexed = {contract_identity(task, {"request": task["request"], "inputs": task["inputs"],
        "requirements": task["requirements"], "execution_spec": task["spec"]}): task for task in tasks}
    if len(indexed) != len(tasks) or set(indexed) != {contract_identity(case, case["public"]) for case in cases}:
        raise ValueError("Public rule contracts differ from actual diagnostic inputs")
    return indexed


def new_group():
    return {"parsed_views": 0, "reference_lookup_valid_views": 0,
            "status_counts": Counter(), "by_requirement": defaultdict(Counter)}


def audit(root):
    root = Path(root)
    cases = read_jsonl(root / "cases.jsonl")
    validate_cases(cases)
    if any(case["split"] != "train" for case in cases):
        raise ValueError("This public baseline audit is only for the recorded train candidates")
    folder = root / "inference"
    manifest = read(folder / "manifest.json")
    if manifest.get("status") != "completed" or manifest.get("condition") != "schema_zero_shot" \
            or manifest.get("cases_hash") != digest(cases) or manifest.get("case_count") != len(cases) \
            or manifest.get("gold_loaded") is not False or manifest.get("example_count") != 0 \
            or manifest.get("examples_hash") != digest([]) or manifest.get("effective_context_limit") != 2048:
        raise ValueError("Not the complete, unscored zero-shot baseline on these public cases")
    identity = manifest["model_identity"]
    if any(identity[key] != value for key, value in {"device": "cuda", "max_new_tokens": 512, "token_budget": 8192, "context_limit": 2048}.items()):
        raise ValueError("Recorded baseline budgets changed")
    for name in ("predictions.jsonl", "calls.jsonl"):
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != manifest["file_sha256"][name]:
            raise ValueError("Baseline raw records changed")
    predictions, calls = read_jsonl(folder / "predictions.jsonl"), read_jsonl(folder / "calls.jsonl")
    expected = [case["case_id"] for case in cases]
    if [row["case_id"] for row in predictions] != expected or [row["case_id"] for row in calls] != expected:
        raise ValueError("Missing, duplicate, reordered or foreign baseline records")
    preflight = read(root / "preflight-lengths.json")
    lengths = {row["case_id"]: row["prompt_tokens"] for row in preflight["rows"]}
    if preflight["cases_hash"] != digest(cases) or set(lengths) != set(expected):
        raise ValueError("Preflight refers to different cases")
    counts = Counter(views=len(cases), requested_judgments=sum(len(case["public"]["requirements"]) for case in cases))
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "rule"
        rule_predictions(cases, rule_inputs(root, cases), out)
        for name in ("predictions.jsonl", "calls.jsonl"):
            if read_jsonl(out / name) != read_jsonl(root / "rule" / name):
                raise ValueError("Archived public-rule baseline does not reproduce")
        if read(out / "manifest.json") != read(root / "rule/manifest.json"):
            raise ValueError("Public-rule baseline metadata changed")
    rule_rows = read_jsonl(root / "rule/predictions.jsonl")
    if [row["case_id"] for row in rule_rows] != expected:
        raise ValueError("Public-rule baseline coverage changed")
    rule_by_case, rule_counts = {}, Counter()
    for case, prediction in zip(cases, rule_rows):
        findings = parse_prediction(prediction["text"], case["public"]["requirements"])
        validate_findings(list(findings.values()), case["public"])
        rule_by_case[case["case_id"]] = findings
        rule_counts.update(finding["status"] for finding in findings.values())
    modes = {mode: {**new_group(), "by_visibility": {"events": new_group(), "snapshot": new_group()},
                   "public_rule_comparison": {"comparable_judgments": 0, "disagreeing_judgments": 0, "by_requirement": defaultdict(Counter)}}
             for mode in ("strict", "normalized")}
    details = []
    for case, prediction, call in zip(cases, predictions, calls):
        prompt_hash = digest(formal_prompt(case["public"]))
        if call["prompt_hash"] != prompt_hash or call["budget"]["limit"] != 8192:
            raise ValueError("Prompt or shared task budget changed")
        charged = audit_ledger(call["budget"])
        events = call["budget"]["events"]
        if len(events) != 1 or events[0]["prompt_hash"] != prompt_hash \
                or events[0]["prompt_tokens"] != lengths[case["case_id"]] or events[0]["role"] != "analyzer" \
                or events[0].get("completion_allowance", 0) != min(512, 2048 - lengths[case["case_id"]], 8192 - lengths[case["case_id"]]):
            raise ValueError("Call prompt, role, allowance or actual tokenizer/preflight count changed")
        generated = call["status"] == "generated"
        if generated != (events[0]["status"] == "completed"):
            raise ValueError("Generation status conflicts with its ledger")
        if generated and (call["usage"]["prompt_tokens"] != events[0]["prompt_tokens"] \
                or call["usage"]["completion_tokens"] != events[0]["completion_tokens"]):
            raise ValueError("Generation usage differs from actual ledger charge")
        if not generated and prediction["text"]:
            raise ValueError("Failed generation must retain its empty prediction")
        counts["generated_views"] += generated
        counts["generation_error_views"] += not generated
        counts["charged_tokens"] += charged
        counts["known_prompt_tokens"] += call["budget"]["known_prompt_tokens"]
        counts["known_completion_tokens"] += call["budget"]["known_completion_tokens"]
        counts["at_generation_limit_views"] += generated and events[0]["completion_tokens"] == events[0]["completion_allowance"]
        row = {"case_id": case["case_id"], "source_task_id": case["source_task_id"],
            "events_visible": case["public"]["observation"]["events"] is not None, "generated": generated,
            "prompt_tokens": events[0]["prompt_tokens"], "charged_tokens": charged,
            "completion_tokens": events[0].get("completion_tokens")}
        for mode, result in modes.items():
            group = result["by_visibility"]["events" if row["events_visible"] else "snapshot"]
            try:
                findings = parse_prediction(prediction["text"], case["public"]["requirements"], normalize=mode == "normalized")
                result["parsed_views"] += 1
                group["parsed_views"] += 1
                row[mode + "_parsed"] = True
                for rid, finding in findings.items():
                    result["status_counts"][finding["status"]] += 1
                    result["by_requirement"][rid][finding["status"]] += 1
                    group["status_counts"][finding["status"]] += 1
                    group["by_requirement"][rid][finding["status"]] += 1
                    comparison = result["public_rule_comparison"]
                    disagree = finding["status"] != rule_by_case[case["case_id"]][rid]["status"]
                    comparison["comparable_judgments"] += 1
                    comparison["disagreeing_judgments"] += disagree
                    comparison["by_requirement"][rid]["comparable"] += 1
                    comparison["by_requirement"][rid]["disagreeing"] += disagree
                validate_findings(list(findings.values()), case["public"])
                result["reference_lookup_valid_views"] += 1
                group["reference_lookup_valid_views"] += 1
                row[mode + "_reference_lookup_valid"] = True
            except (ValueError, TypeError, KeyError) as exc:
                row.setdefault(mode + "_parsed", False)
                row[mode + "_reference_lookup_valid"] = False
                row[mode + "_error"] = str(exc)
        details.append(row)
    if manifest["errors"] != counts["generation_error_views"]:
        raise ValueError("Recorded generation failure count changed")
    for result in modes.values():
        result["parsed_rate_all_views"] = result["parsed_views"] / len(cases)
        result["reference_lookup_valid_rate_all_views"] = result["reference_lookup_valid_views"] / len(cases)
        result["status_counts"] = dict(result["status_counts"])
        result["by_requirement"] = {rid: dict(values) for rid, values in sorted(result["by_requirement"].items())}
        comparison = result["public_rule_comparison"]
        comparison["non_comparable_judgments"] = counts["requested_judgments"] - comparison["comparable_judgments"]
        comparison["disagreement_fraction_among_comparable"] = comparison["disagreeing_judgments"] / comparison["comparable_judgments"] if comparison["comparable_judgments"] else None
        comparison["warning"] = "Model/rule disagreement, not error rate, human truth, or evidence of rule semantic correctness. Missing predictions remain separately counted."
    return {"scope": "unreviewed_training_development", "condition": "A_schema_zero_shot", "counts": dict(counts),
        "declared_source_clusters": len({case["source_task_id"] for case in cases}), "modes": modes, "records": details,
        "generation_stage_seconds": manifest["seconds"],
        "public_rule_baseline": {"views": len(rule_rows), "model_calls": 0, "reference_lookup_valid_views": len(rule_rows),
                                 "predicted_status_counts": dict(rule_counts), "human_gold": False},
        "human_reviews_completed": 0, "semantic_accuracy_scored": False, "evidence_semantic_support_scored": False,
        "fewshot_baseline_run": False, "formal_M3_complete": False, "formal_M5_complete": False,
        "warning": "Interface and reference lookup only. Predicted states are model outputs, not correctness or human gold. Twenty-four views share twelve actor trajectories/four unverified source clusters. No formal diagnostic, fine-tuning benefit or generalization claim; generation-limit hits do not by themselves prove truncation."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-rule", action="store_true", help="Create public-rule C once at a new directory; reads no private reference")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if args.write_rule:
        cases = read_jsonl(root / "cases.jsonl")
        rule_predictions(cases, rule_inputs(root, cases), root / "rule")
    report = audit(root)
    (root / "interface-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    sums = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and p.name != "checksums.json" and "__pycache__" not in p.parts}
    (root / "checksums.json").write_text(json.dumps(sums, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({key: value for key, value in report.items() if key != "records"}, indent=2))
