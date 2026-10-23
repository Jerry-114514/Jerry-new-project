"""Byte-verified model/checkpoint bundles; no pickle loading or model execution."""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shutil
import tarfile

from .core import digest


def file_sha(path):
    with Path(path).open("rb") as stream:
        return stream_sha(stream)


def stream_sha(stream):
    value = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        value.update(chunk)
    return value.hexdigest()


def safe_name(name):
    path = PurePosixPath(name)
    if not name or not path.parts or path.is_absolute() or ".." in path.parts or str(path) != name or "\\" in name or ":" in name:
        raise ValueError("Unsafe model bundle member name")


def inventory(root):
    root = Path(root).resolve()
    if (root / "model").is_symlink():
        raise ValueError("Model exports must be regular local files")
    paths = [root / "latest.pt", root / "result.json", *sorted((root / "model").rglob("*"))]
    paths += [root / name for name in ("run_config.json", "config.json") if (root / name).exists()]
    result = {}
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Model bundle contains a symlink or outside path")
        if path.is_dir():
            continue
        name = path.relative_to(root).as_posix(); safe_name(name)
        result[name] = {"bytes": path.stat().st_size, "sha256": file_sha(path)}
    required = {"latest.pt", "result.json", "model/selection.json"}
    if not required <= set(result) or not any(name.endswith(".safetensors") for name in result) \
            or not ({"model/tokenizer.json", "model/tokenizer.model"} & set(result)):
        raise ValueError("Completed checkpoint, selected export and tokenizer required")
    return result


def verify_model_backup(archive, expected_sha=None, expected_index=None):
    archive = Path(archive)
    actual_sha = file_sha(archive)
    if expected_sha is not None and actual_sha != expected_sha:
        raise ValueError("Transferred archive SHA256 differs from its recorded source")
    with tarfile.open(archive, "r:") as handle:
        members = handle.getmembers()
        names = [item.name for item in members]
        if len(names) != len(set(names)) or any(not item.isfile() for item in members):
            raise ValueError("Duplicate or nonregular model archive member")
        for name in names:
            safe_name(name)
        index_member = handle.getmember("backup-index.json")
        if index_member.size > 1024 * 1024:
            raise ValueError("Model backup index too large")
        index = json.load(handle.extractfile(index_member))
        if index.get("kind") != "model_checkpoint_bundle_index" or index.get("schema_version") != 1 \
                or not isinstance(index.get("files"), dict) or not index["files"]:
            raise ValueError("Invalid model backup index")
        if expected_index is not None and index != expected_index:
            raise ValueError("Archive index differs from the captured source inventory")
        if set(names) != set(index["files"]) | {"backup-index.json"}:
            raise ValueError("Archive does not contain exactly the indexed source files")
        for name, record in index["files"].items():
            member = handle.getmember(name)
            if member.size != record["bytes"] or stream_sha(handle.extractfile(member)) != record["sha256"]:
                raise ValueError("Archived model/checkpoint bytes differ: " + name)
    return {"kind": "model_backup_byte_verification", "archive_sha256": actual_sha,
        "files": len(index["files"]), "source_bytes": sum(r["bytes"] for r in index["files"].values()),
        "index_hash": digest(index), "external_archive_hash_checked": expected_sha is not None,
        "model_or_pickle_loaded": False, "off_host_durability_claim": False}


def create_model_backup(root, out, matrix_job=None, lock_hash=None, engineering=False):
    root, out = Path(root).resolve(), Path(out).resolve()
    if out.is_relative_to(root):
        raise ValueError("Backup destination must be outside the training job")
    if not engineering and (matrix_job is None or not isinstance(lock_hash, str) or len(lock_hash) != 64
                            or any(c not in "0123456789abcdef" for c in lock_hash)):
        raise ValueError("Completed matrix job and protocol hash required, or explicit engineering mode")
    result = json.loads((root / "result.json").read_text(encoding="utf-8"))
    if result.get("completed") is not True:
        raise ValueError("Do not label a running/partial training job as a completed model bundle")
    files = inventory(root)
    if matrix_job is not None:
        expected = matrix_job["artifacts_sha256"]
        actual = {name: row["sha256"] for name, row in files.items() if name == "latest.pt" or name.startswith("model/")}
        if matrix_job.get("status") != "completed" or result["config"] != matrix_job["config"] \
                or files["result.json"]["sha256"] != matrix_job["result_sha256"] or actual != expected:
            raise ValueError("Training artifacts differ from the completed matrix job")
    index = {"kind": "model_checkpoint_bundle_index", "schema_version": 1,
        "scope": "engineering" if engineering else "completed_matrix_job_binding", "files": files,
        "protocol_hash": lock_hash, "matrix_job_hash": digest(matrix_job) if matrix_job is not None else None,
        "warning": "Content copy only; no endpoint efficacy, full-experiment completion or durable-storage certification."}
    out.mkdir(parents=True, exist_ok=False)
    manifest = {"status": "creating", "scope": index["scope"], "source_root": str(root), "index_hash": digest(index)}
    def save():
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    save()
    try:
        total = sum(row["bytes"] for row in files.values())
        if shutil.disk_usage(out).free < total + 10 * 1024 * 1024:
            raise ValueError("Insufficient space for the uncompressed model bundle")
        temporary = out / "model.partial.tar"
        with tarfile.open(temporary, "x:") as handle:
            payload = json.dumps(index, sort_keys=True).encode("utf-8")
            header = tarfile.TarInfo("backup-index.json"); header.size = len(payload)
            handle.addfile(header, io.BytesIO(payload))
            for name in sorted(files):
                handle.add(root / name, arcname=name, recursive=False)
        if inventory(root) != files:
            raise ValueError("Training files changed while creating the backup")
        receipt = verify_model_backup(temporary, expected_index=index)
        temporary.rename(out / "model.tar")
        manifest.update(status="completed", archive="model.tar", verification=receipt)
    except Exception as exc:
        manifest.update(status="failed", error_type=type(exc).__name__, error=str(exc)); save(); raise
    save()
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create")
    create.add_argument("--root", type=Path)
    create.add_argument("--matrix", type=Path)
    create.add_argument("--job")
    create.add_argument("--engineering", action="store_true")
    create.add_argument("--out", type=Path, required=True)
    verify = sub.add_parser("verify")
    verify.add_argument("--archive", type=Path, required=True)
    verify.add_argument("--expected-sha256", required=True)
    args = parser.parse_args()
    if args.command == "verify":
        answer = verify_model_backup(args.archive, args.expected_sha256)
    elif args.matrix is not None:
        if args.root is not None or not args.job:
            parser.error("--matrix requires --job and derives its root; do not also pass --root")
        matrix = json.loads(args.matrix.read_text(encoding="utf-8"))
        job = next(row for row in matrix["jobs"] if row["name"] == args.job)
        safe_name(job["name"])
        answer = create_model_backup(args.matrix.parent / job["name"], args.out, job, matrix["lock_hash"], args.engineering)
    else:
        if args.root is None or not args.engineering:
            parser.error("Standalone --root requires explicit --engineering")
        answer = create_model_backup(args.root, args.out, engineering=True)
    print(json.dumps(answer, indent=2))


if __name__ == "__main__":
    main()
