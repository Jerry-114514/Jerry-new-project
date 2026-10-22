from copy import deepcopy
import json
import unittest

from intentlab.formal_eval import paired_task_bootstrap, parse_prediction, score_predictions
from test_formal_data import case, review


class FormalEvaluationTests(unittest.TestCase):
    def test_task_weighting_does_not_treat_views_as_independent_tasks(self):
        cases = [case(), case("view-2"), case("view-3", source="source-2")]
        gold = {row["case_id"]: review()["findings"] for row in cases}
        correct = json.dumps({"findings": review()["findings"]})
        result = score_predictions(cases, gold, [{"case_id": "view-1", "text": correct},
                                                {"case_id": "view-2", "text": correct}])
        self.assertEqual(result["source_task_groups"], 2)
        self.assertEqual(result["task_mean_error_rate"], 0.5)
        self.assertEqual(result["counts"]["missing_predictions"], 1)
        self.assertEqual(result["counts"]["normalized_errors"], 1)

    def test_normalization_separates_interface_and_state_without_changing_status(self):
        row = case()
        finding = deepcopy(review()["findings"][0])
        finding.pop("id")
        finding["status"] = "satisfied"
        result = score_predictions([row], {"view-1": review()["findings"]},
            [{"case_id": "view-1", "text": json.dumps({"preserve": finding})}])
        self.assertEqual(result["counts"]["strict_valid"], 0)
        self.assertEqual(result["counts"]["normalized_valid"], 1)
        self.assertEqual(result["counts"]["unsafe_satisfied"], 1)
        self.assertEqual(result["task_mean_error_rate"], 1)

    def test_duplicate_predictions_and_duplicate_json_keys_are_rejected(self):
        prediction = {"case_id": "view-1", "text": "{}"}
        with self.assertRaises(ValueError):
            score_predictions([case()], {"view-1": review()["findings"]}, [prediction, prediction])
        with self.assertRaises(ValueError):
            parse_prediction('{"findings":[],"findings":[]}', case()["public"]["requirements"])

    def test_bad_evidence_does_not_silently_change_correct_state(self):
        finding = deepcopy(review()["findings"])
        finding[0]["evidence"] = ["event:999"]
        result = score_predictions([case()], {"view-1": review()["findings"]},
            [{"case_id": "view-1", "text": json.dumps({"findings": finding})}])
        self.assertEqual(result["task_mean_error_rate"], 0)
        self.assertEqual(result["counts"]["reference_valid_items"], 0)

    def test_bootstrap_is_paired_and_rejects_mismatched_task_sets(self):
        result = paired_task_bootstrap({"a": 1, "b": 1}, {"a": 0, "b": 0})
        self.assertEqual(result["right_minus_left"], -1)
        self.assertEqual(result["percentile_95_interval"], [-1, -1])
        with self.assertRaises(ValueError):
            paired_task_bootstrap({"a": 1}, {"b": 1})
