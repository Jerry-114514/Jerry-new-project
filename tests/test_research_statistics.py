"""Arithmetic fixtures are not model experiments or human-reviewed data."""

from copy import deepcopy
import unittest

from intentlab.research_statistics import (ANALYSIS_PLAN, analyze_records, comparison_registry, holm_adjust,
    paired_cluster_statistics, sign_flip_test, validate_analysis_plan)
from intentlab.controller_plan import condition_map
from test_execution_protocol import fixture
from pathlib import Path
import tempfile


def inputs():
    with tempfile.TemporaryDirectory() as name:
        spec = fixture(Path(name))
    spec["statistics"]["analysis_plan"] = deepcopy(ANALYSIS_PLAN)
    protocol = {"scope": "engineering", "lock_hash": "arithmetic-fixture-not-a-real-protocol",
        "spec": spec, "controller_binding": {"plan": {"risk_controls": ["remove_hard_weight", "remove_unknown_weight"]},
                                            "selection": {"selected_k": 2}}}
    scores = {condition: {} for condition in ("B", "D-seed-0", "D-seed-1", "D-seed-2")}
    for split in ("test", "ood"):
        for condition in scores:
            errors = {split + "-a": 0, split + "-b": 1} if condition == "B" else {
                split + "-a": int(condition == "D-seed-0"), split + "-b": 0}
            scores[condition][split] = {"per_task_error_rate": errors}
    losses = {}
    for name in ("D", "E"):
        for seed in (0, 1, 2):
            losses[f"{name}-seed-{seed}"] = [{"case_id": split + "-" + source,
                "source_task_id": split + "-" + source, "split": split, "target_tokens": tokens,
                "loss_sum": float(tokens + (seed + 1 if name == "E" and source == "a" else 0))}
                for split in ("test", "ood") for source, tokens in (("a", 1), ("b", 9))]
    execution, ablation = [], []
    for rows, conditions in ((execution, ("P1", "P2", "P3", "P4")),
                             (ablation, condition_map(protocol["controller_binding"], spec["execution"]["settings"]))):
        for condition in conditions:
            for split in ("test", "ood"):
                for source, variants in (("a", 9), ("b", 1)):
                    if condition in {"P3", "fixed-k-1", "dynamic-k-remove_unknown_weight"}:
                        success = source == "a"
                    elif condition in {"P4", "fixed-k-2", "dynamic-k-remove_hard_weight"}:
                        success = source == "b"
                    else:
                        success = condition == "dynamic-k"
                    for index in range(variants):
                        rows.append({"task_id": f"{split}-{source}-{index}", "source_task_id": split + "-" + source,
                            "family": "arithmetic", "split": split, "condition": condition,
                            "metrics": {"compliant_success": success}, "feasible_at_repair_start": True,
                            "repair_introduced_hard_violations": ["R_INPUT"] if condition == "P1" and source == "a" else [],
                            "status": "finished", "history": [{"phase": "repair"}]})
    return protocol, scores, losses, execution, ablation


class ResearchStatisticsTests(unittest.TestCase):
    def test_fixed_seeds_stay_inside_clusters_and_insufficient_groups_are_explicit(self):
        result = paired_cluster_statistics({"one": [0, 0, 0]}, {"one": [0, 1, 2]}, bootstrap_samples=100)
        self.assertEqual(result["source_task_groups"], 1)
        self.assertEqual(result["fixed_training_seeds"], 3)
        self.assertEqual(result["right_minus_left"], 1)
        self.assertEqual(result["seed_effect_sample_sd"], 1)
        self.assertIsNone(result["percentile_95_interval"])
        self.assertIsNone(result["hypothesis_test"]["p_value"])

    def test_ratio_resamples_loss_sums_and_denominators_together(self):
        result = paired_cluster_statistics({"a": [1], "b": [9]}, {"a": [2], "b": [9]},
            weights={"a": 1, "b": 9}, seed=9, bootstrap_samples=2000)
        self.assertAlmostEqual(result["right_minus_left"], 0.1)
        self.assertEqual(result["percentile_95_interval"], [0, 1])
        self.assertAlmostEqual(result["per_seed"][0]["right"], 1.1)

    def test_exact_sign_flip_matches_hand_enumeration_and_counts_zero_clusters(self):
        self.assertEqual(sign_flip_test([1, 1, 1])["p_value"], 0.25)
        self.assertEqual(sign_flip_test([1, 2])["p_value"], 0.5)
        self.assertEqual(sign_flip_test([1, -1])["p_value"], 1)
        zero = sign_flip_test([0, 0, 0])
        self.assertEqual(zero["p_value"], 1)
        self.assertEqual(zero["permutations"], 1)
        self.assertEqual(zero["task_groups"], 3)

    def test_monte_carlo_is_deterministic_and_never_zero(self):
        one = sign_flip_test([1] * 20, seed=17, samples=100, exact_limit=1)
        self.assertEqual(one, sign_flip_test([1] * 20, seed=17, samples=100, exact_limit=1))
        self.assertEqual(one["mode"], "monte_carlo_conservative_plus_one")
        self.assertGreaterEqual(one["p_value"], 1 / 101)

    def test_holm_monotonic_adjustment_preserves_missing_comparisons(self):
        self.assertEqual(holm_adjust({"a": 0.01, "b": 0.04, "c": 0.03}), {"a": 0.03, "b": 0.06, "c": 0.06})
        self.assertEqual(holm_adjust({"a": 0.01, "missing": None}), {"a": 0.02, "missing": None})
        self.assertEqual(holm_adjust({"missing": None}), {"missing": None})
        with self.assertRaises(ValueError):
            holm_adjust({"a": float("nan")})

    def test_registry_has_one_primary_and_seventeen_secondary_without_seed_inflation(self):
        protocol, *_ = inputs()
        registry = comparison_registry(protocol["spec"]["execution"]["settings"])
        self.assertEqual(sum(row["family"] == "primary" for row in registry), 1)
        self.assertEqual(sum(row["family"] == "secondary" for row in registry), 17)
        self.assertEqual(validate_analysis_plan({}, formal=False), ANALYSIS_PLAN)
        with self.assertRaises(ValueError):
            validate_analysis_plan({}, formal=True)

    def test_complete_arithmetic_uses_task_means_paired_seeds_and_token_weighted_loss(self):
        report = analyze_records(*inputs())
        comparisons = report["comparisons"]
        self.assertAlmostEqual(comparisons["RQ1/test"]["right_minus_left"], -1 / 3)
        self.assertAlmostEqual(comparisons["RQ1/test"]["seed_effect_sample_sd"], (1 / 12) ** 0.5)
        self.assertEqual(comparisons["RQ2/test"]["right_minus_left"], -0.5)
        self.assertEqual(comparisons["RQ3/test"]["right_minus_left"], 0)
        self.assertAlmostEqual(comparisons["RQ4/test"]["right_minus_left"], 0.2)
        self.assertAlmostEqual(comparisons["RQ4/test"]["seed_effect_sample_sd"], 0.1)
        self.assertEqual(comparisons["M7/dynamic-vs-fixed-k-3/test"]["right_minus_left"], 1)
        self.assertEqual(report["secondary_family_size"], 17)
        self.assertFalse(report["m8_complete"])

    def test_invalid_pairing_coverage_and_population_are_rejected(self):
        for change in ("duplicate_execution", "missing_condition", "different_tokens", "negative_error", "different_seed_groups"):
            args = list(inputs())
            if change == "duplicate_execution":
                args[3].append(deepcopy(args[3][0]))
            elif change == "missing_condition":
                args[4] = [row for row in args[4] if row["condition"] != "fixed-k-3"]
            elif change == "different_tokens":
                args[2]["E-seed-2"][0]["target_tokens"] += 1
            elif change == "negative_error":
                args[1]["B"]["test"]["per_task_error_rate"]["test-a"] = -1
            else:
                del args[1]["D-seed-1"]["test"]["per_task_error_rate"]["test-a"]
            with self.subTest(change=change), self.assertRaises(ValueError):
                analyze_records(*args)
