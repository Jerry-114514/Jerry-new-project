from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

from intentlab.formal_data import (adjudication_packet, annotation_packet, export_reviewed, formal_prompt,
                                  resolve_reviews, validate_cases, validate_findings)


def case(cid="view-1", split="train", source="source-1", template="template-1", family="normalization"):
    return {"case_id": cid, "source_task_id": source, "split": split,
        "family": family, "template_id": template,
        "source": {"origin": "model_generated", "reference": "test fixture only",
                   "license": "CC0-1.0", "trajectory": "injected"},
        "public": {"request": "Preserve the input. Normalize names.",
            "inputs": {"input.json": [{"name": " Alice "}]},
            "requirements": [{"id": "preserve", "quote": "Preserve the input.", "hard": True}],
            "observation": {"files": {"input.json": []}, "events": None}}}


def review(cid="view-1", reviewer="alice", status="violated"):
    return {"case_id": cid, "reviewer": reviewer, "human_verified": True,
        "findings": [{"id": "preserve", "status": status,
                      "evidence": ["input:input.json", "file:input.json"]}]}


class FormalDataTests(unittest.TestCase):
    def test_derivatives_templates_and_normalized_requests_cannot_cross_splits(self):
        for source, template in (("source-1", "new"), ("new", "template-1"), ("new", "new")):
            with self.subTest(source=source, template=template), self.assertRaises(ValueError):
                validate_cases([case(), case("view-2", "test", source, template)])
        other = case("view-2", "ood", "new", "new")
        other["public"]["request"] += " New task."
        with self.assertRaisesRegex(ValueError, "OOD"):
            validate_cases([case(), other])

    def test_prompt_uses_only_allowlisted_public_input_and_snapshots(self):
        row = case()
        validate_cases([row])
        prompt = formal_prompt(row["public"])
        self.assertNotIn("human_verified", prompt)
        self.assertNotIn("test fixture", prompt)
        self.assertIn("input:input.json", prompt)
        self.assertIn("file:input.json", prompt)
        row["public"]["oracle"] = {"answer": "secret"}
        with self.assertRaises(ValueError):
            validate_cases([row])

    def test_unverified_duplicate_or_missing_humans_cannot_export(self):
        variants = [[review()], [review(), review()],
                    [review(), dict(review(reviewer="bob"), human_verified=False)]]
        for rows in variants:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                resolve_reviews([case()], rows)

    def test_disagreement_requires_independent_explicit_adjudication(self):
        reviews = [review(), review(reviewer="bob", status="unknown")]
        with self.assertRaisesRegex(ValueError, "Unresolved"):
            resolve_reviews([case()], reviews)
        decision = {"case_id": "view-1", "adjudicator": "carol", "human_verified": True,
            "reason": "The current snapshot differs from the original input.", "findings": review()["findings"]}
        chosen, stats = resolve_reviews([case()], reviews, [decision])
        self.assertEqual(chosen["view-1"]["preserve"]["status"], "violated")
        self.assertEqual(stats["status_agreement"], 0)
        with self.assertRaises(ValueError):
            resolve_reviews([case()], reviews, [dict(decision, adjudicator="alice")])

    def test_dispute_packet_does_not_auto_adjudicate_review_disagreement(self):
        with tempfile.TemporaryDirectory() as name:
            out = Path(name) / "disputes"
            result = adjudication_packet([case()], [review(), review(reviewer="bob", status="unknown")], out)
            self.assertEqual(result["unresolved_cases"], 1)
            decision = json.loads((out / "adjudication-template.jsonl").read_text())
            self.assertFalse(decision["human_verified"])
            self.assertEqual(decision["findings"][0]["status"], "")

    def test_evidence_must_exist_and_hidden_events_cannot_be_cited(self):
        public = case()["public"]
        for refs in (["event:0"], ["file:missing"], [], ["request", "request"]):
            findings = deepcopy(review()["findings"])
            findings[0]["evidence"] = refs
            with self.subTest(refs=refs), self.assertRaises(ValueError):
                validate_findings(findings, public)

    def test_packet_is_unlabeled_and_export_has_provenance(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            annotation_packet([case()], root / "packet")
            template = json.loads((root / "packet/review-template.jsonl").read_text())
            self.assertFalse(template["human_verified"])
            self.assertEqual(template["findings"][0]["status"], "")
            counts = export_reviewed([case()], [review(), review(reviewer="bob")], [], root / "out")
            self.assertEqual(counts["train"], 1)
            manifest = json.loads((root / "out/manifest.json").read_text())
            self.assertFalse(manifest["protocol_frozen"])
            self.assertEqual(manifest["audit"]["source_task_groups"], {"train": 1})
            with self.assertRaises(FileExistsError):
                export_reviewed([case()], [review(), review(reviewer="bob")], [], root / "out")

    def test_holdout_gold_is_separate_from_training_files_and_model_inputs(self):
        with tempfile.TemporaryDirectory() as name:
            out = Path(name) / "export"
            export_reviewed([case(split="test")], [review(), review(reviewer="bob")], [], out)
            self.assertFalse((out / "test.jsonl").exists())
            model_input = (out / "heldout/test/cases.jsonl").read_text()
            self.assertNotIn('"findings"', model_input)
            self.assertNotIn('"completion"', model_input)
            self.assertTrue((out / "heldout/test/gold.jsonl").exists())


if __name__ == "__main__":
    unittest.main()
