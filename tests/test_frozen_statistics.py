"""Statistics stage receipts with synthetic fixtures; no formal acceptance."""

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from intentlab.core import digest
from intentlab.frozen_ablation import interact, reveal
from intentlab.frozen_statistics import run, verify
from test_frozen_ablation import prepare, arguments
from test_frozen_execution import FakePool


def setup(root):
    spec, lock, binding = prepare(root)
    common = arguments(root, lock, binding)
    interact(*common, root / "m7-interactions", True, FakePool)
    reveal(*common, root / "m7-interactions", root / "m7-reveal", True)
    for path in (Path(spec["execution"]["references"]), Path(spec["dataset"]["reviews"]),
                 *Path(spec["dataset"]["export"]).glob("heldout/*/gold.jsonl")):
        path.unlink()
    for record in lock["controller_binding"]["files"].values():
        Path(record["path"]).unlink()
    return (*common, root / "m7-interactions", root / "m7-reveal")


@patch("intentlab.diagnostic_protocol.verify_execution_models", return_value={"verified": True})
class FrozenStatisticsTests(unittest.TestCase):
    def test_no_gold_or_reference_access_and_identical_report_reproduction(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            common = setup(root)
            first = run(*common, root / "statistics", True)
            self.assertEqual(first["status"], "completed")
            self.assertFalse(first["gold_or_references_reopened"])
            self.assertFalse(first["m8_complete"])
            report = json.loads((root / "statistics/report.json").read_text())
            self.assertIn("auxiliary", report)
            self.assertNotIn("verified statistics entry/receipt", report["remaining"])
            self.assertFalse(verify(*common, root / "statistics", True)["m8_complete"])
            run(*common, root / "reproduction", True)
            self.assertEqual((root / "statistics/report.json").read_bytes(), (root / "reproduction/report.json").read_bytes())
            with self.assertRaises(FileExistsError):
                run(*common, root / "statistics", True)

    def test_missing_upstream_receipt_prevents_output_creation(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            common = setup(root)
            (root / "m7-reveal/manifest.json").unlink()
            with self.assertRaises(OSError):
                run(*common, root / "statistics", True)
            self.assertFalse((root / "statistics").exists())

    def test_rehashed_report_cannot_override_registered_family(self, unused):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name)
            common = setup(root)
            run(*common, root / "statistics", True)
            path = root / "statistics/report.json"
            report = json.loads(path.read_text())
            report["secondary_family_size"] = 1
            path.write_text(json.dumps(report))
            meta_path = root / "statistics/manifest.json"
            meta = json.loads(meta_path.read_text())
            meta["files_sha256"]["report.json"] = hashlib.sha256(path.read_bytes()).hexdigest()
            meta["receipt_hash"] = digest({key: value for key, value in meta.items() if key != "receipt_hash"})
            meta_path.write_text(json.dumps(meta))
            with self.assertRaisesRegex(ValueError, "arithmetic recomputation"):
                verify(*common, root / "statistics", True)
