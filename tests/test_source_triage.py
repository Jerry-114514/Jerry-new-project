"""Synthetic metadata tests are not real independent-source or human reviews."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from intentlab.formal_data import write_jsonl
from intentlab.protocol import (check_spec, file_hash, semantic_review_binding, validate_semantic_lock_binding)
from intentlab.source_triage import review_template, triage, validate_semantic_review, write_triage
from scripts.build_training_candidates import training_tasks


def cases():
    tasks, _ = training_tasks()
    result = []
    for index, task in enumerate(tasks[:2]):
        row = {key: deepcopy(task[key]) for key in ("source_task_id", "template_id", "family", "split", "source")}
        row.update(case_id=f"UNIT-CASE-{index}", public={"request": task["request"], "inputs": deepcopy(task["inputs"]),
            "requirements": deepcopy(task["requirements"]), "execution_spec": deepcopy(task["spec"]),
            "observation": {"files": deepcopy(task["inputs"]), "events": []}})
        result.append(row)
    return result


def synthetic_review(rows):
    result = review_template(rows)
    result.update(reviewer="SYNTHETIC-UNIT-DECLARATION-NOT-A-PERSON", human_verified=True,
        provenance_reviewed=True, semantic_reviewed=True, split_isolation_reviewed=True,
        prior_public_inventory_reviewed=True, prior_public_inventory_reference="SYNTHETIC UNIT INVENTORY ONLY",
        limitations="Unit declarations only; no real source or reviewer authenticity claim.")
    for row in result["source_groups"]:
        row.update(independence_rationale="Synthetic grouping rationale for test coverage only.",
                   provenance_evidence="Unit test fixture, not an actual independent source.")
    for row in result["pair_reviews"]:
        row.update(decision="independent_sources", rationale="Synthetic pair review for enforcement tests, not scientific independence.")
    return result


class SourceTriageTests(unittest.TestCase):
    def test_observation_views_and_copied_batches_do_not_inflate_contracts(self):
        rows = cases()
        view = deepcopy(rows[0]); view["case_id"] += "-snapshot"; view["public"]["observation"]["events"] = None
        rows.append(view)
        summary, _, queue = triage({"a": rows, "copied": deepcopy(rows)})
        self.assertEqual(summary["input_memberships"], 6)
        self.assertEqual(summary["unique_case_ids"], 3)
        self.assertEqual(summary["unique_public_contracts"], 2)
        self.assertEqual(summary["declared_source_ids"], 1)
        self.assertEqual(queue, [])
        self.assertFalse(summary["formal_readiness_evidence"])

    def test_different_field_and_domain_same_operation_is_risk_not_duplicate_proof(self):
        rows = cases()
        rows[1].update(source_task_id="different-declared-source", template_id="different-declared-template", split="validation")
        summary, _, queue = triage({"candidate": rows})
        self.assertEqual(summary["flagged_cross_split_pairs"], 1)
        self.assertIn("shared_coded_operation_risk_only", queue[0]["reasons"])
        self.assertNotIn("identical_public_contract", queue[0]["reasons"])

    def test_ordering_is_deterministic_and_conflicting_ids_are_rejected(self):
        rows = cases()
        rows[1]["source_task_id"] = "second"
        self.assertEqual(triage({"a": rows}), triage({"a": list(reversed(rows))}))
        bad = deepcopy(rows[0]); bad["split"] = "validation"
        with self.assertRaisesRegex(ValueError, "conflicting"):
            triage({"a": [rows[0]], "b": [bad]})

    def test_public_holdout_rejected_and_private_cross_split_duplicate_flagged(self):
        a = cases()[0]; b = deepcopy(a); b.update(case_id="UNIT-HOLDOUT", split="test")
        with self.assertRaisesRegex(ValueError, "test/OOD"):
            triage({"a": [a], "b": [b]})
        _, _, queue = triage({"a": [a], "b": [b]}, private=True)
        self.assertIn("declared_source_cross_split", queue[0]["reasons"])
        self.assertIn("identical_public_contract", queue[0]["reasons"])

    def test_blank_or_stale_review_and_missing_group_rationale_rejected(self):
        rows = cases()
        with self.assertRaisesRegex(ValueError, "human"):
            validate_semantic_review(rows, review_template(rows))
        with self.assertRaisesRegex(ValueError, "exact cases"):
            validate_semantic_review(rows, triage({"a": rows})[0])
        for change in ("cases_hash", "triage_summary_hash", "rationale", "coverage", "schema_type"):
            review = synthetic_review(rows)
            if change in {"cases_hash", "triage_summary_hash"}: review[change] = "0" * 64
            elif change == "rationale": review["source_groups"][0]["independence_rationale"] = ""
            elif change == "schema_type": review["schema_version"] = True
            else: review["source_groups"] = []
            with self.assertRaises(ValueError): validate_semantic_review(rows, review)

    def test_binding_training_check_does_not_open_deleted_coordinator_material(self):
        rows = cases()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            write_jsonl(root / "cases.jsonl", rows)
            (root / "review.json").write_text(json.dumps(synthetic_review(rows)))
            spec = {"dataset": {"cases": str(root / "cases.jsonl")}, "evidence": {"semantic_dedup_review": str(root / "review.json")}}
            lock = {"annotation_inputs": {"cases": {"sha256": file_hash(root / "cases.jsonl")}},
                    "evidence": {"semantic_dedup_review": {"sha256": file_hash(root / "review.json")}}}
            lock["semantic_review_binding"] = semantic_review_binding(spec, lock)
            (root / "cases.jsonl").unlink(); (root / "review.json").unlink()
            self.assertTrue(validate_semantic_lock_binding(lock))
            lock["semantic_review_binding"]["summary"]["human_verified"] = False
            with self.assertRaises(ValueError): validate_semantic_lock_binding(lock)

    def test_flagged_pairs_need_decisions_and_exact_duplicates_cannot_be_overridden(self):
        rows = cases()
        rows[1]["source_task_id"] = "unit-second-source"
        review = synthetic_review(rows)
        self.assertEqual(validate_semantic_review(rows, review)["flagged_pairs_reviewed"], 1)
        for change in ("missing", "unresolved", "rationale"):
            bad = deepcopy(review)
            if change == "missing": bad["pair_reviews"] = []
            elif change == "unresolved": bad["pair_reviews"][0]["decision"] = "insufficient_evidence"
            else: bad["pair_reviews"][0]["rationale"] = ""
            with self.assertRaises(ValueError): validate_semantic_review(rows, bad)
        rows[1]["public"] = deepcopy(rows[0]["public"])
        with self.assertRaisesRegex(ValueError, "Identical public contracts"):
            validate_semantic_review(rows, synthetic_review(rows))

    def test_formal_readiness_rejects_unreviewed_semantic_file_content(self):
        from test_execution_protocol import fixture
        with tempfile.TemporaryDirectory() as d:
            spec = fixture(Path(d), source=Path(__file__).resolve().parents[1])
            spec.update(scope="formal", dependencies=["torch", "transformers", "peft", "accelerate", "bitsandbytes"])
            spec["training"].update(mode="qlora", device="cuda")
            rows = [json.loads(line) for line in Path(spec["dataset"]["cases"]).read_text(encoding="utf-8").splitlines()]
            Path(spec["evidence"]["semantic_dedup_review"]).write_text(json.dumps(review_template(rows)))
            with patch("intentlab.protocol.source_git", return_value={"commit": "SYNTHETIC", "clean": True}), \
                    patch("intentlab.protocol.importlib.metadata.version", return_value="SYNTHETIC"):
                report = check_spec(spec)
            self.assertFalse(report["ready"])
            self.assertTrue(any("Actual human source" in blocker for blocker in report["blockers"]), report)

    def test_exclusive_output_has_blank_review_metadata_and_no_autoapproval(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "triage"
            write_triage({"a": cases()}, out)
            template = json.loads((out / "semantic-review-template.json").read_text())
            self.assertFalse(template["human_verified"])
            self.assertTrue(all(not row["independence_rationale"] for row in template["source_groups"]))
            with self.assertRaises(FileExistsError): write_triage({"a": cases()}, out)


if __name__ == "__main__":
    unittest.main()
