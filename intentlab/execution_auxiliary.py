"""Descriptive candidate opportunity and common-initial-feasibility summaries."""

from collections import defaultdict
from statistics import mean


def candidate_summary(records):
    counts = {key: 0 for key in ("attempts", "complete_proposals", "incomplete_proposals", "decision_error_trials",
        "complete_compliant_candidates", "false_blocks", "independent_guard_false_blocks", "decision_error_false_blocks",
        "rejected_noncompliant_candidates", "rejected_new_hard_violation_candidates", "accepted_new_hard_violation_candidates")}
    by_source = defaultdict(lambda: {"eligible": 0, "false_blocks": 0})
    for row in records:
        audit = row.get("candidate_audit")
        if not isinstance(audit, dict) or audit.get("schema_version") != 1 or audit.get("accepted_candidates_replay_final") is not True:
            raise ValueError("Complete replayed candidate audit required; missing data cannot become zero trials")
        candidates = audit["candidates"]
        if len(candidates) != sum(step["phase"] == "repair" for step in row["history"]):
            raise ValueError("Every repair proposal must remain in candidate denominators")
        for candidate in candidates:
            counts["attempts"] += 1
            if candidate["complete_proposal"] is False:
                if any(candidate[key] is not None for key in ("offline_compliant", "offline_metrics", "false_block")):
                    raise ValueError("Incomplete proposal truth must stay null")
                counts["incomplete_proposals"] += 1
                continue
            if candidate["complete_proposal"] is not True or type(candidate["offline_compliant"]) is not bool \
                    or type(candidate["false_block"]) is not bool or type(candidate["independent_guard_false_block"]) is not bool \
                    or not isinstance(candidate["candidate_new_hard_violations"], list):
                raise ValueError("Explicit complete candidate truth required")
            compliant, accepted = candidate["offline_compliant"], candidate["accepted"]
            if type(accepted) is not bool or candidate["false_block"] != (compliant and not accepted) \
                    or candidate["independent_guard_false_block"] != (compliant and not accepted and candidate["hard_guard_passed"] is False):
                raise ValueError("Candidate false-block attribution differs from its declared truth/acceptance")
            counts["complete_proposals"] += 1
            counts["decision_error_trials"] += candidate["trial_status"] == "decision_error"
            counts["complete_compliant_candidates"] += compliant
            counts["false_blocks"] += candidate["false_block"]
            counts["independent_guard_false_blocks"] += candidate["independent_guard_false_block"]
            counts["decision_error_false_blocks"] += candidate["false_block"] and candidate["trial_status"] == "decision_error"
            counts["rejected_noncompliant_candidates"] += not compliant and not accepted
            counts["rejected_new_hard_violation_candidates"] += not accepted and bool(candidate["candidate_new_hard_violations"])
            counts["accepted_new_hard_violation_candidates"] += accepted and bool(candidate["candidate_new_hard_violations"])
            if compliant:
                by_source[row["source_task_id"]]["eligible"] += 1
                by_source[row["source_task_id"]]["false_blocks"] += not accepted
    eligible = counts["complete_compliant_candidates"]
    return {"counts": counts, "pooled_candidate_false_block_rate": counts["false_blocks"] / eligible if eligible else None,
        "eligible_source_task_groups": len(by_source),
        "source_task_mean_false_block_rate_among_eligible": mean(row["false_blocks"] / row["eligible"] for row in by_source.values()) if by_source else None,
        "per_source_eligible_counts": dict(by_source),
        "warning": "Descriptive complete-candidate opportunity rates, not an all-task causal effect. No eligible compliant proposals yields null, not zero. Decision failures after complete submission remain in the denominator."}


def common_feasibility(records, left_condition, right_condition, split, metric="success"):
    if metric not in {"success", "new_violation"}:
        raise ValueError("Unknown common-feasibility metric")
    sides = []
    for condition in (left_condition, right_condition):
        rows = [row for row in records if row["condition"] == condition and row["split"] == split]
        indexed = {row["task_id"]: row for row in rows}
        if len(indexed) != len(rows) or not rows:
            raise ValueError("Unique complete paired task records required for common-feasibility analysis")
        sides.append(indexed)
    left, right = sides
    if set(left) != set(right):
        raise ValueError("Common feasibility cannot compare different task populations")
    counts = {key: 0 for key in ("paired_variants", "common_feasible_variants", "left_only_feasible_variants", "right_only_feasible_variants", "neither_feasible_variants")}
    grouped = defaultdict(list)
    for tid in sorted(left):
        a, b = left[tid], right[tid]
        if a["source_task_id"] != b["source_task_id"] or any(type(row["feasible_at_repair_start"]) is not bool for row in (a, b)):
            raise ValueError("Paired source grouping or initial feasibility changed")
        fa, fb = a["feasible_at_repair_start"], b["feasible_at_repair_start"]
        counts["paired_variants"] += 1
        counts["common_feasible_variants"] += fa and fb
        counts["left_only_feasible_variants"] += fa and not fb
        counts["right_only_feasible_variants"] += fb and not fa
        counts["neither_feasible_variants"] += not fa and not fb
        if fa and fb:
            def value(row):
                if metric == "success":
                    return int(row["metrics"]["compliant_success"])
                if metric == "new_violation":
                    return int(bool(row["repair_introduced_hard_violations"]))
                raise ValueError("Unknown common-feasibility metric")
            grouped[a["source_task_id"]].append((value(a), value(b)))
    a = mean(mean(pair[0] for pair in rows) for rows in grouped.values()) if grouped else None
    b = mean(mean(pair[1] for pair in rows) for rows in grouped.values()) if grouped else None
    return {"left_condition": left_condition, "right_condition": right_condition, "split": split, "metric": metric,
        "counts": counts, "eligible_source_task_groups": len(grouped), "left": a, "right": b,
        "right_minus_left": b - a if grouped else None,
        "warning": "Descriptive intersection of both conditions' initial historical feasibility. This selected subset is not the primary all-task estimand and has no additional confirmatory p-value."}


def auxiliary_report(execution_records, ablation_records, registry):
    candidates = {}
    for stage, records in (("M6", execution_records), ("M7", ablation_records)):
        candidates[stage] = {condition: {split: candidate_summary([row for row in records if row["condition"] == condition and row["split"] == split])
            for split in ("test", "ood")} for condition in sorted({row["condition"] for row in records})}
    common = {}
    for comparison in registry:
        rq, split = comparison["rq"], comparison["split"]
        if rq == "RQ2":
            common[comparison["id"]] = common_feasibility(execution_records, "P1", "P3", split, "new_violation")
        elif rq == "RQ3":
            common[comparison["id"]] = common_feasibility(execution_records, "P3", "P4", split)
        elif rq == "M7":
            common[comparison["id"]] = common_feasibility(ablation_records, comparison["left"], comparison["right"], split)
    return {"candidate_opportunities": candidates, "common_initial_feasibility": common,
            "confirmatory_family_unchanged": True, "additional_hypothesis_tests": 0}
