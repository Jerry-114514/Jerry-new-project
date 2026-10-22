"""Public development source/template risk triage, never human dedup approval."""

import argparse
from collections import Counter
from copy import deepcopy
from itertools import combinations
import json
from pathlib import Path
import re

from .core import canonical, digest
from .formal_data import normalized_request, read_jsonl, validate_cases, write_jsonl


def operation_text(public):
    rules = public.get("execution_spec", {}).get("requirement_rules", {})
    selected = [req["quote"] for req in public["requirements"] if rules.get(req["id"]) == "exact_outputs"]
    if not selected:
        selected = [req["quote"] for req in public["requirements"] if not req["hard"]]
    return " ".join(selected) or public["request"]


def words(text):
    return set(re.findall(r"\w+", normalized_request(text)))


def triage(batches, threshold=0.8, private=False):
    if not isinstance(batches, dict) or not batches or any(not isinstance(name, str) or not name for name in batches):
        raise ValueError("Named nonempty case batches required")
    if type(threshold) not in {float, int} or not 0 < threshold <= 1:
        raise ValueError("Lexical triage threshold must be in (0, 1]")
    inventory, seen_cases = {}, {}
    memberships = 0
    for batch in sorted(batches):
        cases = batches[batch]
        validate_cases(cases)
        if not private and any(case["split"] not in {"train", "validation"} for case in cases):
            raise ValueError("Public development triage cannot expose test/OOD")
        for case in cases:
            cid = case["case_id"]
            if cid in seen_cases and canonical(seen_cases[cid]) != canonical(case):
                raise ValueError("Same case ID has conflicting metadata or observations across batches")
            seen_cases[cid] = case
            public = {key: deepcopy(value) for key, value in case["public"].items() if key != "observation"}
            metadata = {key: case[key] for key in ("source_task_id", "template_id", "family", "split")}
            contract = digest({"metadata": metadata, "public_task": public})
            item = inventory.setdefault(contract, {"contract_id": contract, **metadata, "public_task": public,
                "case_ids": set(), "batches": set(), "source_declarations": {}})
            item["case_ids"].add(cid)
            item["batches"].add(batch)
            item["source_declarations"][digest(case["source"])] = deepcopy(case["source"])
            memberships += 1
    items = []
    for key in sorted(inventory):
        item = inventory[key]
        item["case_ids"] = sorted(item["case_ids"])
        item["batches"] = sorted(item["batches"])
        item["source_declarations"] = [item["source_declarations"][key] for key in sorted(item["source_declarations"])]
        items.append(item)
    queue, reason_counts = [], Counter()
    within_group_pairs = 0
    features = {item["contract_id"]: {"words": words(operation_text(item["public_task"])),
        "request": normalized_request(item["public_task"]["request"]), "public_hash": digest(item["public_task"]),
        "operation": item["public_task"].get("execution_spec", {}).get("operation", {}).get("name")} for item in items}
    for left, right in combinations(items, 2):
        if left["source_task_id"] == right["source_task_id"] and left["split"] == right["split"]:
            within_group_pairs += 1
            continue
        a, b = features[left["contract_id"]], features[right["contract_id"]]
        cross_split = left["split"] != right["split"]
        wa, wb = a["words"], b["words"]
        similarity = len(wa & wb) / len(wa | wb) if wa | wb else 0.0
        reasons = []
        if a["public_hash"] == b["public_hash"]:
            reasons.append("identical_public_contract")
        if a["request"] == b["request"]:
            reasons.append("identical_normalized_request")
        if left["source_task_id"] == right["source_task_id"]:
            reasons.append("declared_source_cross_split")
        if left["template_id"] == right["template_id"]:
            reasons.append("shared_declared_template")
        opa, opb = a["operation"], b["operation"]
        if opa is not None and opa == opb:
            reasons.append("shared_coded_operation_risk_only")
        if similarity >= threshold:
            reasons.append("operation_text_lexical_overlap")
        if reasons:
            pair = {"pair_id": digest([left["contract_id"], right["contract_id"]]),
                "left_contract": left["contract_id"], "right_contract": right["contract_id"],
                "left_source_task_id": left["source_task_id"], "right_source_task_id": right["source_task_id"],
                "left_split": left["split"], "right_split": right["split"], "cross_split": cross_split,
                "reasons": reasons, "operation_text_word_jaccard": similarity}
            queue.append(pair)
            reason_counts.update(reasons)
    summary = {"kind": "unreviewed_public_source_triage", "schema_version": 1, "scope": "private_coordinator" if private else "development",
        "policy": {"name": "public_contract_and_lexical_risk_triage_v1", "word_jaccard_threshold": threshold},
        "batch_case_hashes": {name: digest(sorted(rows, key=lambda row: row["case_id"])) for name, rows in sorted(batches.items())},
        "input_memberships": memberships, "unique_case_ids": len(seen_cases), "unique_public_contracts": len(items),
        "declared_source_ids": len({item["source_task_id"] for item in items}),
        "within_declared_source_variant_pairs_skipped": within_group_pairs,
        "flagged_contract_pairs": len(queue), "flagged_cross_split_pairs": sum(pair["cross_split"] for pair in queue),
        "reason_counts": dict(sorted(reason_counts.items())), "inventory_hash": digest(items), "queue_hash": digest(queue),
        "human_reviews_completed": 0, "semantic_dedup_review_complete": False, "formal_readiness_evidence": False,
        "warning": "Candidate triage only. Shared operation or lexical overlap is not proof of duplication; different operations or low overlap is not proof of independence. Declared source IDs and view counts are not certified sample size. Human source/template and semantic review, including unflagged cases, is required. No labels or model scores are read."}
    return summary, items, queue


def source_groups(cases):
    groups = {}
    for row in cases:
        group = groups.setdefault(row["source_task_id"], {key: set() for key in ("template_ids", "families", "splits")})
        for key, field in (("template_ids", "template_id"), ("families", "family"), ("splits", "split")):
            group[key].add(row[field])
    return [{"source_task_id": key, **{field: sorted(values) for field, values in groups[key].items()}}
            for key in sorted(groups)]


def review_template(cases):
    summary, _, queue = triage({"current": cases}, private=True)
    return {"kind": "semantic_source_review", "schema_version": 1, "cases_hash": digest(cases),
        "triage_summary_hash": digest(summary), "reviewer": "", "human_verified": False,
        "provenance_reviewed": False, "semantic_reviewed": False, "split_isolation_reviewed": False,
        "prior_public_inventory_reviewed": False, "prior_public_inventory_reference": "", "limitations": "",
        "source_groups": [{**row, "independence_rationale": "", "provenance_evidence": ""} for row in source_groups(cases)],
        "pair_reviews": [{"pair_id": row["pair_id"], "decision": "", "rationale": ""} for row in queue]}


def validate_semantic_review(cases, review):
    """Coordinator-only validation. Human declarations are not identity proof."""
    expected = review_template(cases)
    if not isinstance(review, dict) or set(review) != set(expected) or type(review.get("schema_version")) is not int \
            or any(review[key] != expected[key] for key in ("kind", "schema_version", "cases_hash", "triage_summary_hash")):
        raise ValueError("Semantic source review must bind the exact cases and recomputed triage")
    for field in ("human_verified", "provenance_reviewed", "semantic_reviewed", "split_isolation_reviewed", "prior_public_inventory_reviewed"):
        if review[field] is not True:
            raise ValueError("Actual human source/semantic/split/prior-public review required")
    for field in ("reviewer", "prior_public_inventory_reference", "limitations"):
        if not isinstance(review[field], str) or not review[field].strip():
            raise ValueError("Reviewer, prior public inventory reference and limitations required")
    groups = review["source_groups"]
    expected_groups = source_groups(cases)
    if not isinstance(groups, list) or len(groups) != len(expected_groups):
        raise ValueError("Semantic review must cover every declared source group")
    by_id = {}
    for row in groups:
        if not isinstance(row, dict) or set(row) != {"source_task_id", "template_ids", "families", "splits", "independence_rationale", "provenance_evidence"} \
                or not isinstance(row["source_task_id"], str) or row["source_task_id"] in by_id:
            raise ValueError("Malformed or duplicate semantic source-group review")
        by_id[row["source_task_id"]] = row
    for expected_group in expected_groups:
        row = by_id.get(expected_group["source_task_id"])
        if row is None or any(row[key] != value for key, value in expected_group.items()) \
                or any(not isinstance(row[key], str) or not row[key].strip() for key in ("independence_rationale", "provenance_evidence")):
            raise ValueError("Source-group identity, template, family, split or human rationale incomplete")
    _, _, queue = triage({"current": cases}, private=True)
    pairs = review["pair_reviews"]
    if not isinstance(pairs, list) or len(pairs) != len(queue):
        raise ValueError("Every flagged semantic pair needs an explicit human decision")
    pair_map = {}
    for row in pairs:
        if not isinstance(row, dict) or set(row) != {"pair_id", "decision", "rationale"} \
                or not isinstance(row["pair_id"], str) or row["pair_id"] in pair_map:
            raise ValueError("Malformed or duplicate semantic pair review")
        pair_map[row["pair_id"]] = row
    for pair in queue:
        row = pair_map.get(pair["pair_id"])
        if row is None or row["decision"] != "independent_sources" \
                or not isinstance(row["rationale"], str) or not row["rationale"].strip():
            raise ValueError("Regroup/exclude duplicate or unresolved sources, then regenerate and review the changed dataset")
        if "identical_public_contract" in pair["reasons"]:
            raise ValueError("Identical public contracts cannot be approved as independent sources; regroup/exclude first")
    return {"kind": "validated_semantic_source_review", "schema_version": 1,
        "cases_hash": review["cases_hash"], "triage_summary_hash": review["triage_summary_hash"],
        "source_groups_reviewed": len(groups), "flagged_pairs_reviewed": len(queue), "case_count": len(cases), "reviewer": review["reviewer"], "human_verified": True,
        "warning": "Validated declarations and complete coverage, not proof of human identity, statistical independence or exhaustive semantic retrieval."}


def write_triage(batches, out, threshold=0.8, private=False):
    summary, inventory, queue = triage(batches, threshold, private)
    merged = {row["case_id"]: row for rows in batches.values() for row in rows}
    cases = [merged[key] for key in sorted(merged)]
    try:
        template = review_template(cases)
        unavailable = None
    except ValueError as exc:
        template = None
        unavailable = {"human_reviews_completed": 0, "reason": str(exc),
                       "warning": "Correct global case grouping/isolation before preparing a source review."}
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    write_jsonl(out / "contracts.jsonl", inventory)
    write_jsonl(out / "candidate-pairs.jsonl", queue)
    write_jsonl(out / "coordinator-cases.jsonl", cases)
    write_jsonl(out / "pair-review-template.jsonl", [{"pair_id": row["pair_id"], "reviewer": "", "human_verified": False,
        "decision": "", "reason": ""} for row in queue])
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    filename, content = ("semantic-review-template.json", template) if template is not None else ("semantic-review-unavailable.json", unavailable)
    (out / filename).write_text(json.dumps(content, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, nargs="+", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--threshold", type=float, default=0.8)
    parser.add_argument("--private", action="store_true", help="Coordinator output under runs/formal-private; never publish held-out material")
    args = parser.parse_args()
    if args.private and not args.out.resolve().is_relative_to((Path.cwd() / "runs/formal-private").resolve()):
        parser.error("Private coordinator output must stay under runs/formal-private")
    batches = {path.as_posix(): read_jsonl(path) for path in args.cases}
    if len(batches) != len(args.cases):
        parser.error("Repeated input paths are not additional batches")
    print(json.dumps(write_triage(batches, args.out, args.threshold, args.private), indent=2))


if __name__ == "__main__":
    main()
