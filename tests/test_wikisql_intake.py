"""Synthetic tar fixtures test source intake, not actual human source approval."""

import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from intentlab.execution_data import validate_tasks
from intentlab.formal_data import read_jsonl, validate_cases
from intentlab.sft_data import read_pairs
from scripts.intake_wikisql import archive_identity, build_pool


def fixture(root, duplicate=False, symlink=False):
    root = Path(root)
    tables = [{"id": f"UNIT-TABLE-{i}", "header": ["city", "number"], "types": ["text", "real"],
               "rows": [["UNIT-CELL-NOT-A-REAL-SOURCE", i]]} for i in range(3)]
    queries = [{"table_id": table["id"], "question": f"UNIT-QUESTION-{i}: select the city", "phase": 1,
                "sql": {"sel": 0, "agg": 0, "conds": []}} for i, table in enumerate(tables)]
    queries += [dict(queries[0]), dict(queries[1], question=queries[0]["question"])]
    path = root / "source.tar.bz2"
    with tarfile.open(path, "w:bz2") as archive:
        def add(name, body):
            raw = body.encode(); info = tarfile.TarInfo(name); info.size = len(raw)
            archive.addfile(info, io.BytesIO(raw))
        if symlink:
            info = tarfile.TarInfo("data/train.tables.jsonl"); info.type = tarfile.SYMTYPE; info.linkname = "outside"
            archive.addfile(info)
        else:
            add("data/train.tables.jsonl", "".join(json.dumps(row) + "\n" for row in tables))
        add("data/train.jsonl", "".join(json.dumps(row) + "\n" for row in queries))
        if duplicate: add("data/train.jsonl", "{}\n")
        add("data/dev.jsonl", "INVALID JSON: MUST NOT BE PARSED")
        add("data/test.jsonl", "INVALID JSON: MUST NOT BE PARSED")
        add("../outside.json", "MUST NOT BE EXTRACTED")
    source = {"repository": "salesforce/WikiSQL", "revision": "f" * 40,
              "usage": "train_development_sources_only", "archive": archive_identity(path)}
    return path, source


class WikiSQLIntakeTests(unittest.TestCase):
    def test_only_train_members_read_and_no_archive_paths_extracted(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); archive, source = fixture(root)
            report = build_pool(archive, source, root / "pool")
            self.assertEqual(set(report["parsed_members"]), {"data/train.jsonl", "data/train.tables.jsonl"})
            self.assertFalse(report["upstream_heldout_json_parsed"])
            self.assertEqual(report["upstream_train_records"], 5)
            self.assertFalse((root / "outside.json").exists())
            self.assertFalse((root / "data").exists())

    def test_archive_tamper_or_selected_member_ambiguity_creates_no_pool(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            for name, kwargs in (("duplicate", {"duplicate": True}), ("symlink", {"symlink": True}), ("hash", {})):
                sub = root / name; sub.mkdir(); archive, source = fixture(sub, **kwargs)
                if name == "hash": archive.write_bytes(b"changed")
                with self.assertRaises(ValueError): build_pool(archive, source, sub / "pool")
                self.assertFalse((sub / "pool").exists())

    def test_deterministic_table_and_question_grouping_does_not_fill_quota_with_copies(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); archive, source = fixture(root)
            a = build_pool(archive, source, root / "a", limit=600)
            b = build_pool(archive, source, root / "b", limit=600)
            self.assertEqual(a, b)
            self.assertEqual((root / "a/public-index.jsonl").read_bytes(), (root / "b/public-index.jsonl").read_bytes())
            rows = read_jsonl(root / "a/coordinator-pool.jsonl")
            self.assertEqual(len(rows), len({row["table_id"] for row in rows}))
            self.assertEqual(len(rows), len({row["question"] for row in rows}))
            self.assertLess(a["selected_source_candidates"], a["requested_candidates"])

    def test_public_index_excludes_questions_cells_and_upstream_sql(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); archive, source = fixture(root)
            build_pool(archive, source, root / "pool")
            index = (root / "pool/public-index.jsonl").read_text(encoding="utf-8")
            self.assertNotIn("UNIT-QUESTION", index)
            self.assertNotIn("UNIT-CELL", index)
            for row in read_jsonl(root / "pool/public-index.jsonl"):
                self.assertFalse({"question", "table", "upstream_sql", "sql", "completion"} & set(row))

    def test_source_pool_cannot_be_used_as_project_cases_execution_tasks_or_sft(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); archive, source = fixture(root)
            report = build_pool(archive, source, root / "pool")
            path = root / "pool/coordinator-pool.jsonl"; rows = read_jsonl(path)
            self.assertEqual(report["project_cases_created"], 0)
            self.assertFalse(report["formal_minimum_tasks_satisfied"])
            self.assertTrue(all(row["project_split"] is None and not row["human_reviewed"] and not row["annotation_ready"] for row in rows))
            for validator in (validate_cases, validate_tasks):
                with self.assertRaises(ValueError): validator(rows)
            with self.assertRaises(ValueError): read_pairs(path)

    def test_existing_output_and_invalid_selection_parameters_are_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); archive, source = fixture(root)
            build_pool(archive, source, root / "pool")
            with self.assertRaises(FileExistsError): build_pool(archive, source, root / "pool")
            with self.assertRaises(ValueError): build_pool(archive, source, root / "invalid", limit=0)
            self.assertFalse((root / "invalid").exists())


if __name__ == "__main__":
    unittest.main()
