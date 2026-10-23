"""Task-cluster inference, fixed-seed summaries and declared Holm families.

Resampling never treats task variants or training seeds as extra independent
tasks. Sign-flip p-values require paired cluster exchangeability; declaring that
assumption does not establish it for a dataset.
"""

from copy import deepcopy
import itertools
import math
import random
from statistics import mean, stdev

from .core import digest


ANALYSIS_PLAN = {
    "schema_version": 1,
    "primary_split": "test",
    "ood_role": "secondary",
    "seed_aggregation": "mean_of_three_paired_seed_effects",
    "seed_uncertainty": "descriptive_sample_sd_only",
    "bootstrap_unit": "source_task_id",
    "bootstrap_interval": "percentile_floor_indices",
    "loss_estimand": "target_token_weighted_ratio",
    "hypothesis_test": "two_sided_cluster_sign_flip",
    "null_assumption": "independent_source_clusters_with_paired_exchangeability",
    "permutation_samples": 10000,
    "max_exact_nonzero_clusters": 16,
    "minimum_inference_clusters": 2,
    "secondary_family": "rq2_rq3_rq4_both_splits_plus_rq1_ood_plus_all_m7_controls",
    "undefined_p_values": "retain_family_size_and_return_null",
}

STRATIFIED_ANALYSIS_PLAN = dict(deepcopy(ANALYSIS_PLAN), schema_version=2,
    bootstrap_stratification='operation_family_fixed_source_counts',
    minimum_inference_stratum_clusters=2,
    other_generator_quotas='not_conditioned_on_by_resampling')


def validate_analysis_plan(statistics, formal=False):
    plan = statistics.get("analysis_plan")
    if plan is None and not formal:
        return deepcopy(ANALYSIS_PLAN)
    if plan not in (ANALYSIS_PLAN, STRATIFIED_ANALYSIS_PLAN) or type(plan.get("schema_version")) is not int:
        raise ValueError("Freeze the complete registered cluster/seed/test/multiplicity analysis plan")
    return deepcopy(plan)


def finite_number(value):
    return type(value) in {int, float} and math.isfinite(value)


def sign_flip_test(contributions, seed=0, samples=10000, exact_limit=16, minimum_clusters=2):
    if not contributions or any(not finite_number(value) for value in contributions) \
            or type(samples) is not int or samples < 100 or type(exact_limit) is not int or not 0 <= exact_limit <= 20 \
            or type(minimum_clusters) is not int or minimum_clusters < 2:
        raise ValueError("Finite cluster contributions and explicit resampling limits required")
    nonzero = [value for value in contributions if value != 0]
    result = {"method": "two_sided_cluster_sign_flip", "task_groups": len(contributions),
        "nonzero_clusters": len(nonzero), "p_value": None,
        "assumption": "Independent source clusters; paired effects jointly exchangeable under sign reversal. Not a generic test of equal means without that assumption."}
    if len(contributions) < minimum_clusters:
        return dict(result, mode="insufficient_clusters", permutations=0)
    observed = abs(math.fsum(nonzero))
    tolerance = 1e-12 * max(1.0, observed, math.fsum(abs(value) for value in nonzero))
    if len(nonzero) <= exact_limit:
        extreme, total = 0, 2 ** len(nonzero)
        for signs in itertools.product((-1, 1), repeat=len(nonzero)):
            statistic = abs(math.fsum(sign * value for sign, value in zip(signs, nonzero)))
            extreme += statistic >= observed - tolerance
        return dict(result, mode="exact_sign_assignments", permutations=total, p_value=extreme / total)
    rng = random.Random(seed)
    extreme = 0
    for _ in range(samples):
        statistic = abs(math.fsum((1 if rng.getrandbits(1) else -1) * value for value in nonzero))
        extreme += statistic >= observed - tolerance
    return dict(result, mode="monte_carlo_conservative_plus_one", permutations=samples, seed=seed,
                p_value=(extreme + 1) / (samples + 1))


def paired_cluster_statistics(left, right, weights=None, seed=0, bootstrap_samples=2000,
                              permutation_samples=10000, exact_limit=16, minimum_clusters=2, strata=None):
    if not left or set(left) != set(right) or any(not isinstance(key, str) or not key for key in left):
        raise ValueError("Identical nonempty named source-task sets required")
    if type(bootstrap_samples) is not int or bootstrap_samples < 100:
        raise ValueError("At least 100 bootstrap replicates required")
    ids = sorted(left)
    pools = {'all': ids}
    if strata is not None:
        if not isinstance(strata, dict) or set(strata) != set(ids) \
                or any(not isinstance(value, str) or not value for value in strata.values()):
            raise ValueError('Exactly one nonempty design stratum per source required')
        pools = {label: [key for key in ids if strata[key] == label] for label in sorted(set(strata.values()))}
    strata_sufficient = all(len(pool) >= minimum_clusters for pool in pools.values())
    sizes = set()
    for key in ids:
        for vector in (left[key], right[key]):
            if not isinstance(vector, (list, tuple)) or not vector or any(not finite_number(value) for value in vector):
                raise ValueError("Finite nonempty fixed-seed vectors required")
            sizes.add(len(vector))
    if len(sizes) != 1:
        raise ValueError("Paired clusters must retain exactly the same fixed training seeds")
    seeds = sizes.pop()
    if weights is not None and not isinstance(weights, dict):
        raise ValueError("Cluster denominators must be a named mapping")
    denominator = {key: 1.0 for key in ids} if weights is None else weights
    if set(denominator) != set(ids) or any(not finite_number(value) or value <= 0 for value in denominator.values()):
        raise ValueError("Identical positive cluster denominators required")
    total_weight = math.fsum(denominator.values())
    per_seed = []
    for index in range(seeds):
        a = math.fsum(left[key][index] for key in ids) / total_weight
        b = math.fsum(right[key][index] for key in ids) / total_weight
        per_seed.append({"seed_index": index, "left": a, "right": b, "right_minus_left": b - a})
    # Aggregate seeds within each sampled source; all paired seed outcomes move
    # together. Loss inputs are cluster loss sums with target-token denominators.
    contributions = {key: math.fsum(right[key][index] - left[key][index] for index in range(seeds)) / seeds for key in ids}
    estimate = math.fsum(contributions.values()) / total_weight
    interval = None
    if len(ids) >= minimum_clusters and strata_sufficient:
        rng, replicates = random.Random(seed), []
        for _ in range(bootstrap_samples):
            sampled = [rng.choice(pool) for pool in pools.values() for _ in pool]
            replicates.append(math.fsum(contributions[key] for key in sampled) / math.fsum(denominator[key] for key in sampled))
        replicates.sort()
        interval = [replicates[int(0.025 * (bootstrap_samples - 1))], replicates[int(0.975 * (bootstrap_samples - 1))]]
    result = {"right_minus_left": estimate, "left": mean(row["left"] for row in per_seed),
        "right": mean(row["right"] for row in per_seed), "per_seed": per_seed,
        "seed_effect_sample_sd": stdev(row["right_minus_left"] for row in per_seed) if seeds > 1 else None,
        "fixed_training_seeds": seeds, "source_task_groups": len(ids),
        "estimand": "target_token_weighted_ratio_difference" if weights is not None else "mean_source_task_difference",
        "percentile_95_interval": interval, "bootstrap_samples": bootstrap_samples, "bootstrap_seed": seed,
        "hypothesis_test": sign_flip_test(list(contributions.values()), seed, permutation_samples, exact_limit, minimum_clusters),
        "warning": "Task-conditional inference for these fixed trained models; no training-seed population CI. Fewer than two source clusters yields no CI/p-value. Degenerate bootstrap intervals do not establish absence of rare failures."}
    if strata is not None:
        result['bootstrap_stratification'] = {'unit':'source_task_id',
            'source_groups_per_stratum':{key:len(pool) for key,pool in pools.items()},
            'minimum_clusters_per_stratum':minimum_clusters,
            'within_stratum_inference_defined':strata_sufficient,
            'warning':'Fixed operation-family counts only. Missing-field and fault-cadence quotas are not conditioned on. This does not prove sampling independence or sign-flip exchangeability.'}
        if not strata_sufficient:
            result['hypothesis_test'].update(mode='insufficient_stratum_clusters',p_value=None,permutations=0)
    return result


def holm_adjust(p_values):
    """Keep uncomputable preregistered tests in family size; return null for them."""
    if any(value is not None and (not finite_number(value) or not 0 <= value <= 1) for value in p_values.values()):
        raise ValueError("Holm inputs must be p-values or explicit null")
    ordered = sorted(p_values, key=lambda key: (1.0 if p_values[key] is None else p_values[key], key))
    previous, adjusted, count = 0.0, {}, len(ordered)
    for index, key in enumerate(ordered):
        value = 1.0 if p_values[key] is None else p_values[key]
        previous = max(previous, min(1.0, (count - index) * value))
        adjusted[key] = None if p_values[key] is None else previous
    return {key: adjusted[key] for key in p_values}


def comparison_registry(settings):
    """Source-code/frozen-plan defined family, never selected from p-values."""
    result = []
    for split in ("test", "ood"):
        for rq in ("RQ1", "RQ2", "RQ3", "RQ4"):
            result.append({"id": f"{rq}/{split}", "rq": rq, "split": split,
                           "family": "primary" if (rq, split) == ("RQ1", "test") else "secondary"})
        for k in settings["fixed_k_values"]:
            result.append({"id": f"M7/dynamic-vs-fixed-k-{k}/{split}", "rq": "M7", "split": split,
                           "family": "secondary", "left": f"fixed-k-{k}", "right": "dynamic-k"})
        for name in ("remove_hard_weight", "remove_unknown_weight"):
            result.append({"id": f"M7/{name}/{split}", "rq": "M7", "split": split,
                           "family": "secondary", "left": "dynamic-k", "right": "dynamic-k-" + name})
    return result


def analyze_records(protocol, diagnostic_scores, loss_records, execution_records, ablation_records, include_auxiliary=False):
    """Pure offline analysis; receipt/provenance verification belongs to the caller.

    No gold, models or training state are read here. This function alone is not
    an M8 completion receipt, preregistration or a durable asset backup.
    """
    statistics = protocol["spec"]["statistics"]
    plan = validate_analysis_plan(statistics, formal=protocol["scope"] == "formal")
    settings = protocol["spec"]["execution"]["settings"]
    from .controller_plan import condition_map
    ablation_conditions = condition_map(protocol["controller_binding"], settings)
    from collections import defaultdict
    for condition in ("B", "D-seed-0", "D-seed-1", "D-seed-2"):
        for split in ("test", "ood"):
            values = diagnostic_scores[condition][split]["per_task_error_rate"]
            if not values or any(not isinstance(key, str) or not key or not finite_number(value) or not 0 <= value <= 1
                                 for key, value in values.items()):
                raise ValueError("Diagnostic source-task error rates must be finite values in [0,1]")

    def aggregate_execution(records, conditions):
        expected_conditions = set(conditions)
        actual, identity, groups = set(), {}, defaultdict(lambda: defaultdict(list))
        for row in records:
            condition, tid = row["condition"], row["task_id"]
            if condition not in expected_conditions or row["split"] not in {"test", "ood"} or (condition, tid) in actual:
                raise ValueError("Unknown, duplicate or non-held-out execution record")
            actual.add((condition, tid))
            metadata = (row["source_task_id"], row["split"], row["family"])
            if tid in identity and identity[tid] != metadata:
                raise ValueError("Execution task grouping changed between conditions")
            identity[tid] = metadata
            if type(row["metrics"]["compliant_success"]) is not bool or type(row["feasible_at_repair_start"]) is not bool \
                    or not isinstance(row["repair_introduced_hard_violations"], list):
                raise ValueError("Explicit offline success and initial/repair attribution required")
            groups[(condition, row["split"])][row["source_task_id"]].append(row)
        if not identity or actual != {(condition, tid) for condition in expected_conditions for tid in identity}:
            raise ValueError("Exactly all execution tasks must occur in every condition")
        values, descriptive = {}, {}
        for condition in sorted(expected_conditions):
            descriptive[condition] = {}
            for split in ("test", "ood"):
                cluster_rows = groups[(condition, split)]
                expected_ids = set(diagnostic_scores["B"][split]["per_task_error_rate"])
                if set(cluster_rows) != expected_ids or not expected_ids:
                    raise ValueError("Execution source groups differ from diagnostic source groups")
                values[(condition, split)] = {}
                for source, rows in cluster_rows.items():
                    values[(condition, split)][source] = {
                        "success": mean(int(row["metrics"]["compliant_success"]) for row in rows),
                        "new_violation": mean(int(bool(row["repair_introduced_hard_violations"])) for row in rows)}
                descriptive[condition][split] = {
                    "runs": sum(len(rows) for rows in cluster_rows.values()), "source_task_groups": len(cluster_rows),
                    "source_task_mean_compliant_success": mean(row["success"] for row in values[(condition, split)].values()),
                    "source_task_mean_new_violation": mean(row["new_violation"] for row in values[(condition, split)].values()),
                    "errors": sum(row["status"] == "error" for rows in cluster_rows.values() for row in rows),
                    "repair_proposals": sum(step["phase"] == "repair" for rows in cluster_rows.values() for row in rows for step in row["history"]),
                    "initially_irreversible_runs": sum(not row["feasible_at_repair_start"] for rows in cluster_rows.values() for row in rows),
                    "candidate_audit_available": all("candidate_audit" in row for rows in cluster_rows.values() for row in rows)}
        return values, descriptive

    execution, execution_description = aggregate_execution(execution_records, ("P1", "P2", "P3", "P4"))
    ablation, ablation_description = aggregate_execution(ablation_records, ablation_conditions)
    family_strata = {}
    if plan['schema_version'] == 2:
        for row in itertools.chain(execution_records, ablation_records):
            key = (row['split'], row['source_task_id'])
            family = row['family']
            if not isinstance(family, str) or not family or (key in family_strata and family_strata[key] != family):
                raise ValueError('Source operation family changed between conditions or variants')
            family_strata[key] = family
    expected_loss_conditions = {f"{name}-seed-{seed}" for name in ("D", "E") for seed in (0, 1, 2)}
    if set(loss_records) != expected_loss_conditions:
        raise ValueError("All six selected-checkpoint loss populations required")
    population, loss_groups, denominators = None, {}, None
    for condition in sorted(expected_loss_conditions):
        indexed, sums, counts = {}, defaultdict(float), defaultdict(int)
        for row in loss_records[condition]:
            if row["case_id"] in indexed or row["split"] not in {"test", "ood"} \
                    or type(row["target_tokens"]) is not int or row["target_tokens"] < 1 \
                    or not finite_number(row["loss_sum"]) or row["loss_sum"] < 0:
                raise ValueError("Invalid or duplicate held-out target loss")
            indexed[row["case_id"]] = (row["source_task_id"], row["split"], row["target_tokens"])
            key = (row["split"], row["source_task_id"])
            sums[key] += row["loss_sum"]
            counts[key] += row["target_tokens"]
        if population is not None and indexed != population:
            raise ValueError("D/E seeds must use identical held-out cases and target tokens")
        population, denominators = indexed, counts
        loss_groups[condition] = sums
    comparisons = {}
    for comparison in comparison_registry(settings):
        split, rq = comparison["split"], comparison["rq"]
        ids = sorted(diagnostic_scores["B"][split]["per_task_error_rate"])
        weights = None
        if rq == "RQ1":
            left = {tid: [diagnostic_scores["B"][split]["per_task_error_rate"][tid]] * 3 for tid in ids}
            right = {}
            for tid in ids:
                right[tid] = []
                for seed in (0, 1, 2):
                    values = diagnostic_scores[f"D-seed-{seed}"][split]["per_task_error_rate"]
                    if set(values) != set(ids):
                        raise ValueError("Diagnostic seeds differ in source task coverage")
                    right[tid].append(values[tid])
            direction = "negative_favors_cosine"
        elif rq == "RQ4":
            if {tid for key_split, tid in denominators if key_split == split} != set(ids):
                raise ValueError("Loss clusters differ from diagnostic source groups")
            left = {tid: [loss_groups[f"D-seed-{seed}"][(split, tid)] for seed in (0, 1, 2)] for tid in ids}
            right = {tid: [loss_groups[f"E-seed-{seed}"][(split, tid)] for seed in (0, 1, 2)] for tid in ids}
            weights = {tid: denominators[(split, tid)] for tid in ids}
            direction = "negative_favors_plateau"
        else:
            if rq == "RQ2":
                table, a, b, metric = execution, "P1", "P3", "new_violation"
                direction = "negative_favors_guard"
            elif rq == "RQ3":
                table, a, b, metric = execution, "P3", "P4", "success"
                direction = "positive_favors_dynamic"
            else:
                table, a, b, metric = ablation, comparison["left"], comparison["right"], "success"
                direction = "positive_favors_right_condition"
            left = {tid: [table[(a, split)][tid][metric]] for tid in ids}
            right = {tid: [table[(b, split)][tid][metric]] for tid in ids}
        derived_seed = int(digest({"seed": statistics["bootstrap_seed"], "comparison": comparison["id"]})[:16], 16)
        estimate = paired_cluster_statistics(left, right, weights, derived_seed, statistics["bootstrap_samples"],
            plan["permutation_samples"], plan["max_exact_nonzero_clusters"], plan["minimum_inference_clusters"],
            strata={tid:family_strata[(split,tid)] for tid in ids} if plan['schema_version'] == 2 else None)
        comparisons[comparison["id"]] = dict(estimate, definition=comparison, interpretation=direction)
    secondary = {key: row["hypothesis_test"]["p_value"] for key, row in comparisons.items() if row["definition"]["family"] == "secondary"}
    adjusted = holm_adjust(secondary)
    for key, row in comparisons.items():
        row["holm_adjusted_p_value"] = adjusted.get(key)
        row["secondary_family_size"] = len(secondary) if key in secondary else None
    report = {"kind": "source_task_research_statistics", "schema_version": 3 if plan['schema_version'] == 2 else (2 if include_auxiliary else 1), "scope": protocol["scope"],
        "protocol_hash": protocol["lock_hash"], "analysis_plan": plan,
        "legacy_engineering_plan_inferred": "analysis_plan" not in statistics,
        "input_hashes": {"diagnostic_scores": digest(diagnostic_scores), "loss_records": digest(loss_records),
                         "execution_records": digest(execution_records), "ablation_records": digest(ablation_records)},
        "comparisons": comparisons, "secondary_family_size": len(secondary),
        "execution_descriptive": execution_description, "ablation_descriptive": ablation_description,
        "m8_complete": False,
        "remaining": ["verified statistics entry/receipt", "candidate false-block and common-feasibility analysis",
                      "formal data/experiments and scientific assumption review", "durable model backup and final report"],
        "warning": "Statistical arithmetic and source-cluster aggregation only; validity depends on actual independent sampling and paired exchangeability. Neither matching IDs nor Holm adjustment establishes those assumptions. No population training-seed CI or full M8 completion is claimed."}
    if include_auxiliary:
        from .execution_auxiliary import auxiliary_report
        report["auxiliary"] = auxiliary_report(execution_records, ablation_records, comparison_registry(settings))
        report["remaining"].remove("candidate false-block and common-feasibility analysis")
    return report
