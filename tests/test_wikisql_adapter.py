"""Synthetic adaptation fixtures, never original task fidelity/human truth."""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from intentlab.contracts import public_solution, transform, validate_operation
from intentlab.core import digest, initial_state
from intentlab.execution_oracle import evaluate_execution
from intentlab.execution_analysis import analyze_execution
from intentlab.formal_data import read_jsonl, write_jsonl
from scripts.adapt_wikisql_equality import adapt, build, sqlite_candidate_reference


def fixture():
    table = {"id": "UNIT-TABLE", "page_id": "UNIT-PAGE", "header": ["key", "value"], "types": ["text", "real"],
             "rows": [["A", 0], ["a", False], [" A", None], ["O'NEIL", "001"]]}
    row = {"candidate_id": "UNIT-SOURCE", "upstream_line": 1, "upstream_revision": "f" * 40,
        "upstream_split": "train", "project_split": None, "human_reviewed": False, "allowed_project_roles": ["train", "validation"],
        "table": table, "upstream_sql": {"agg": 0, "sel": 1, "conds": [[0, 0, "a"]]},
        "question": "UNIT synthetic source question, not a real crowdsourced request", "upstream_record_sha256": "a" * 64,
        "table_record_sha256": "b" * 64}
    rows = [row]
    return rows, {"coordinator_pool_hash": digest(rows), "repository": "salesforce/WikiSQL", "revision": "f" * 40,
                  "upstream_heldout_json_parsed": False}


class WikiSQLAdapterTests(unittest.TestCase):
    def test_ascii_operation_preserves_types_duplicates_spaces_order_and_inputs(self):
        rows = [{"key": "A", "value": 0}, {"key": "a", "value": False}, {"key": " a", "value": None}]
        original = deepcopy(rows)
        result = transform(rows, {"name": "ascii_filter_project", "where_field": "key", "equals": "a", "fields": ["value"]})
        self.assertEqual(result, [{"value": 0}, {"value": False}])
        self.assertIs(type(result[0]["value"]), int); self.assertIs(type(result[1]["value"]), bool)
        self.assertEqual(rows, original)

    def test_nonascii_controls_missing_fields_and_bad_parameters_fail_explicitly(self):
        operation = {"name": "ascii_filter_project", "where_field": "k", "equals": "a", "fields": ["v"]}
        for value in ("é", "a\0", "a\n"):
            with self.assertRaises(ValueError): validate_operation(dict(operation, equals=value))
            with self.assertRaises(ValueError): transform([{"k": value, "v": 1}], operation)
        with self.assertRaises(ValueError): transform([{"k": "a"}], operation)
        with self.assertRaises(ValueError): validate_operation(dict(operation, fields=["v", "v"]))

    def test_sqlite_candidate_reference_handles_literal_quotes_and_order(self):
        rows, _ = fixture(); table = rows[0]["table"]
        table["rows"] += [["' OR 1=1 --", 7], ["o'neil", None]]
        for value in ("a", " A", "O'Neil", "' OR 1=1 --", ""):
            expected = sqlite_candidate_reference(table, 0, value, 1)
            records = [{"col_0": cells[0], "col_1": cells[1]} for cells in table["rows"]]
            self.assertEqual(expected, transform(records, {"name": "ascii_filter_project", "where_field": "col_0", "equals": value, "fields": ["col_1"]}))
        self.assertEqual(sqlite_candidate_reference(table, 0, "' OR 1=1 --", 1), [{"col_1": 7}])

    def test_adaptation_is_train_only_and_discloses_researcher_clarification(self):
        tasks, refs, cases, lineage = adapt(*fixture())
        self.assertEqual(tasks[0]["source"]["origin"], "adapted_public")
        self.assertEqual({task["split"] for task in tasks}, {"train"})
        self.assertIn("not an original WikiSQL", tasks[0]["request"])
        self.assertNotIn("upstream_sql", json.dumps(tasks))
        self.assertTrue(lineage[0]["public_clarification_derived_from_upstream_sql_annotation"])
        self.assertFalse(lineage[0]["original_question_fidelity_human_verified"])
        self.assertEqual(len(cases), 4)
        self.assertTrue(all(row["source"]["trajectory"] == "injected" for row in cases))
        state = initial_state(tasks[0]); state.apply(public_solution(tasks[0]))
        self.assertTrue(evaluate_execution(tasks[0], state, refs[0])["compliant_success"])

    def test_page_and_exact_payload_grouping_do_not_inflate_requested_limit(self):
        rows, manifest = fixture()
        same_page = deepcopy(rows[0]); same_page["candidate_id"] = "COPY-PAGE"; same_page["table"]["rows"][0][1] = 9
        same_data = deepcopy(rows[0]); same_data["candidate_id"] = "COPY-DATA"; same_data["table"]["page_id"] = "ANOTHER"
        rows += [same_page, same_data]; manifest["coordinator_pool_hash"] = digest(rows)
        self.assertEqual(len(adapt(rows, manifest, limit=12)[0]), 1)

    def test_builder_uses_separate_reference_path_and_blind_opaque_ids(self):
        rows, manifest = fixture()
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); write_jsonl(root / "pool.jsonl", rows)
            (root / "pool-manifest.json").write_text(json.dumps(manifest))
            with patch("intentlab.contracts.transform", side_effect=AssertionError("Reference construction must not use public solver")):
                result = build(root / "pool.jsonl", root / "pool-manifest.json", root / "adapted")
            self.assertEqual(result["human_labels_created"], 0)
            packet = root / "adapted/reviewer-packet"
            for row in read_jsonl(packet / "cases.jsonl"):
                self.assertEqual(set(row), {"case_id", "public"})
                self.assertTrue(row["case_id"].startswith("adapt-view-"))
                self.assertNotIn("restored", row["case_id"])
            self.assertTrue(all(not row["human_verified"] and not row["reviewer"] for row in read_jsonl(packet / "review-template.jsonl")))
            with self.assertRaises(FileExistsError): build(root / "pool.jsonl", root / "pool-manifest.json", root / "adapted")
        tasks, _, cases, lineage = adapt(rows, manifest)
        hidden = next(row for row in cases if row["public"]["observation"]["events"] is None)
        state = initial_state(tasks[0]); state.files = hidden["public"]["observation"]["files"]
        self.assertEqual(next(f for f in analyze_execution(tasks[0], state, events_visible=False) if f["id"] == "R_INPUT")["status"], "unknown")

    def test_changed_pool_or_heldout_provenance_cannot_be_adapted(self):
        rows, manifest = fixture(); rows[0]["question"] += " changed"
        with self.assertRaises(ValueError): adapt(rows, manifest)
        rows, manifest = fixture(); rows[0]["upstream_split"] = "test"; manifest["coordinator_pool_hash"] = digest(rows)
        with self.assertRaises(ValueError): adapt(rows, manifest)


if __name__ == "__main__": unittest.main()
