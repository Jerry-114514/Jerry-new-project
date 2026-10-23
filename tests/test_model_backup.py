"""Byte fixtures, not model-quality or real-checkpoint validation."""
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from intentlab.model_backup import create_model_backup, file_sha, inventory, verify_model_backup


def fixture(root):
    (root / "model").mkdir(parents=True)
    (root / "latest.pt").write_bytes(b"CHECKPOINT BYTE FIXTURE, NEVER UNPICKLE")
    (root / "result.json").write_text(json.dumps({"completed": True, "config": {"seed": 0}}))
    (root / "model/adapter_model.safetensors").write_bytes(b"WEIGHT BYTE FIXTURE, NOT A MODEL")
    for name in ("selection.json", "adapter_config.json", "tokenizer.json"):
        (root / "model" / name).write_text("{}")


class ModelBackupTests(unittest.TestCase):
    def test_source_and_transferred_bundle_match_without_loading_model_or_pickle(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); fixture(root / "job")
            result = create_model_backup(root / "job", root / "backup", engineering=True)
            archive = root / "backup/model.tar"
            receipt = verify_model_backup(archive, result["verification"]["archive_sha256"])
            self.assertTrue(receipt["external_archive_hash_checked"])
            self.assertFalse(receipt["model_or_pickle_loaded"])
            self.assertFalse(receipt["off_host_durability_claim"])
            self.assertEqual(receipt["files"], len(inventory(root / "job")))
            with tarfile.open(archive) as handle:
                self.assertEqual(handle.extractfile("latest.pt").read(), (root / "job/latest.pt").read_bytes())
            with self.assertRaises(FileExistsError):
                create_model_backup(root / "job", root / "backup", engineering=True)
            with self.assertRaises(ValueError):
                verify_model_backup(archive, "0" * 64)

    def test_matrix_binding_and_partial_model_are_not_silently_promoted(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); fixture(root / "job")
            with self.assertRaises(ValueError):
                create_model_backup(root / "job", root / "no-binding")
            records = inventory(root / "job")
            job = {"status": "completed", "config": {"seed": 0}, "result_sha256": file_sha(root / "job/result.json"),
                   "artifacts_sha256": {p: r["sha256"] for p, r in records.items() if p != "result.json"}}
            answer = create_model_backup(root / "job", root / "bound", job, "a" * 64)
            self.assertEqual(answer["scope"], "completed_matrix_job_binding")
            (root / "job/model/tokenizer.json").write_text('{"changed":true}')
            with self.assertRaises(ValueError):
                create_model_backup(root / "job", root / "tampered", job, "a" * 64)
            (root / "job/result.json").write_text('{"completed":false}')
            with self.assertRaises(ValueError):
                create_model_backup(root / "job", root / "partial", engineering=True)

    def test_corrupt_bytes_or_unsafe_members_cannot_be_verified_from_internal_index(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); fixture(root / "job")
            create_model_backup(root / "job", root / "backup", engineering=True)
            for case in ("corrupt", "outside", "duplicate"):
                destination = root / (case + ".tar")
                with tarfile.open(root / "backup/model.tar") as source, tarfile.open(destination, "w:") as target:
                    for member in source.getmembers():
                        payload = source.extractfile(member).read()
                        if case == "corrupt" and member.name == "latest.pt":
                            payload = b"x" * len(payload)
                        member.size = len(payload); target.addfile(member, io.BytesIO(payload))
                    if case != "corrupt":
                        member = tarfile.TarInfo("../outside" if case == "outside" else "backup-index.json")
                        member.size = 2; target.addfile(member, io.BytesIO(b"{}"))
                with self.assertRaises(ValueError):
                    verify_model_backup(destination)

    def test_mid_copy_source_change_leaves_failure_and_no_completed_archive(self):
        with tempfile.TemporaryDirectory() as name:
            root = Path(name); fixture(root / "job")
            original = tarfile.TarFile.add
            def changed(handle, path, *args, **kwargs):
                if Path(path).name == "latest.pt":
                    Path(path).write_bytes(b"CHANGED DURING COPY")
                return original(handle, path, *args, **kwargs)
            with patch.object(tarfile.TarFile, "add", changed):
                with self.assertRaises(ValueError):
                    create_model_backup(root / "job", root / "backup", engineering=True)
            self.assertEqual(json.loads((root / "backup/manifest.json").read_text())["status"], "failed")
            self.assertFalse((root / "backup/model.tar").exists())
