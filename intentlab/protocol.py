"""Content locks for an experiment protocol, not a claim of scientific validity.

Freezing binds evidence files; people still have to review their substance.
Training verification deliberately does not open held-out gold or annotations.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess

from .core import canonical, digest
from .formal_data import formal_prompt, read_jsonl, resolve_reviews, validate_cases
from .report import save_json


EVIDENCE = ("power_analysis", "length_and_compute_budget", "semantic_dedup_review",
            "provenance_and_release_review", "test_sealing", "model_weight_verification",
            "execution_and_oracle_audit", "controller_ablation_audit")
TRAIN_KEYS = {"revision", "mode", "device", "steps", "eval_every", "batch_size", "accumulation",
              "max_length", "lr", "minimum_lr", "rank", "alpha", "limit", "threads", "defer_test"}


def file_hash(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def source_snapshot(root):
    root = Path(root).resolve()
    paths = set()
    for directory in ("intentlab", "scripts", "tests"):
        paths.update((root / directory).rglob("*.py"))
    paths.update((root / "configs").glob("*.json"))
    paths.update(root.glob("requirements*.txt"))
    paths.update(p for p in (root / "pyproject.toml", root / "idea.md") if p.exists())
    if not (root / "intentlab/neural.py").is_file():
        raise ValueError("Source root lacks the actual training implementation")
    # Normalize source text line endings, allowing Windows/Linux checkouts of
    # the same Git content. Dataset and model assets use exact byte hashes.
    return {path.relative_to(root).as_posix(): hashlib.sha256(
        path.read_text(encoding="utf-8").encode("utf-8")).hexdigest() for path in sorted(paths)}


def source_git(root):
    try:
        commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], stderr=subprocess.DEVNULL).decode().strip()
        changed = subprocess.check_output(["git", "-C", str(root), "status", "--porcelain"], stderr=subprocess.DEVNULL).decode().strip()
        return {"commit": commit, "clean": not changed}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "clean": False}


def model_snapshot(path):
    root = Path(path).resolve()
    if not root.is_dir() or not (root / "config.json").is_file():
        raise ValueError("Formal roles must use a local original base model with config.json")
    if (root / "adapter_config.json").exists():
        raise ValueError("Initial training/execution roles must be original bases, not old adapters")
    paths = [p for p in root.iterdir() if p.is_file() and p.suffix in {".json", ".txt", ".jinja", ".model", ".tiktoken", ".safetensors", ".bin"}]
    if not any(p.suffix in {".safetensors", ".bin"} for p in paths):
        raise ValueError("No base weight files")
    if not any(p.name in {"tokenizer.json", "tokenizer.model", "vocab.json"} for p in paths):
        raise ValueError("Tokenizer assets must be frozen with weights")
    return {"path": str(root), "files_sha256": {p.name: file_hash(p) for p in sorted(paths)}}


def verify_official_assets(snapshot, source_root):
    official = read_json(Path(source_root) / "configs/qwen35-official-assets.json")
    if official["model"] != "Qwen/Qwen3.5-9B" or official["revision"] != "c202236235762e1c871ad0ccb60c8ee5ba337b9a":
        raise ValueError("Official source identity differs from the approved original 9B revision")
    root = Path(snapshot["path"])
    checked = []
    for asset in official["assets"]:
        name = asset["path"]
        if Path(name).name != name or name not in snapshot["files_sha256"]:
            raise ValueError("Missing official model/tokenizer asset: " + name)
        if "sha256" in asset:
            actual = snapshot["files_sha256"][name]
            expected = asset["sha256"]
        else:
            raw = (root / name).read_bytes()
            actual = hashlib.sha1(b"blob " + str(len(raw)).encode("ascii") + b"\0" + raw).hexdigest()
            expected = asset["git_blob_sha1"]
        if actual != expected:
            raise ValueError("Official asset hash mismatch: " + name)
        checked.append(name)
    if len([asset for asset in official["assets"] if asset["path"].endswith(".safetensors") and "sha256" in asset]) != 4:
        raise ValueError("Expected all four official base weight shards")
    return {"model": official["model"], "revision": official["revision"], "verified_assets": checked}


def check_spec(spec):
    """Collect actionable blockers. No GPU calls or automatic readiness declarations."""
    blockers = []
    required = {"schema_version", "scope", "source_root", "dataset", "models", "training", "seeds",
                "schedules", "minimum_tasks", "conditions", "statistics", "budgets", "evidence", "dependencies",
                "few_shot_case_ids"}
    if not isinstance(spec, dict) or set(spec) != required or spec.get("schema_version") != 1:
        return {"ready": False, "blockers": ["Protocol fields do not match schema_version=1"]}
    if spec["scope"] not in {"formal", "engineering"}:
        blockers.append("scope must be formal or engineering")
    if spec["schedules"] != ["cosine", "plateau"] or spec["seeds"] != [0, 1, 2]:
        blockers.append("Main matrix must contain cosine/plateau and seeds 0,1,2")
    training = spec["training"]
    if not isinstance(training, dict) or set(training) != TRAIN_KEYS:
        blockers.append("Training fields must be explicit; data/model/schedule/seed are set by the matrix")
    else:
        if training["defer_test"] is not True or training["limit"] != 0:
            blockers.append("Training must defer test and use all reviewed training rows")
        if spec["scope"] == "formal" and (training["mode"] != "qlora" or training["device"] != "cuda"):
            blockers.append("Formal target requires CUDA QLoRA")
        for key in ("steps", "eval_every", "batch_size", "accumulation", "max_length", "rank", "alpha", "threads"):
            if type(training[key]) is not int or training[key] < 1:
                blockers.append(f"Positive integer training.{key} required")
        if type(training["steps"]) is int and training["steps"] < 2:
            blockers.append("At least two optimizer updates required")
        try:
            if not 0 < training["minimum_lr"] <= training["lr"] < float("inf"):
                blockers.append("Finite positive learning rate bounds required")
        except TypeError:
            blockers.append("Numeric learning rate bounds required")
    statistics = spec["statistics"]
    if not isinstance(statistics, dict) or statistics.get("unit") != "source_task_id" or statistics.get("primary") != "RQ1" \
            or statistics.get("secondary_correction") != "holm" or statistics.get("seed_reporting") != "separate" \
            or statistics.get("primary_scoring") != "normalized" or statistics.get("confidence_level") != 0.95 \
            or type(statistics.get("bootstrap_seed")) is not int:
        blockers.append("Lock task-level primary RQ1, Holm secondary correction and separate seed results")
    if not isinstance(statistics, dict) or type(statistics.get("bootstrap_samples")) is not int or statistics["bootstrap_samples"] < 2000:
        blockers.append("Predeclare at least 2000 bootstrap samples")
    if spec["conditions"] != ["A", "B", "C", "D", "E", "P1", "P2", "P3", "P4"]:
        blockers.append("All declared diagnostic and closed-loop conditions must be present")
    examples = spec["few_shot_case_ids"]
    if not isinstance(examples, list) or not examples or any(not isinstance(cid, str) for cid in examples) \
            or (isinstance(examples, list) and all(isinstance(cid, str) for cid in examples) and len(set(examples)) != len(examples)):
        blockers.append("Freeze an explicit nonempty list of reviewed development example IDs")
    budgets = spec["budgets"]
    if not isinstance(budgets, dict) or set(budgets) != {"token_budget", "max_new_tokens", "max_repairs", "context_limit"} \
            or any(type(v) is not int or v < 1 for v in budgets.values()):
        blockers.append("Explicit positive token, output, repair and context budgets required")
    for field in EVIDENCE:
        value = spec["evidence"].get(field) if isinstance(spec["evidence"], dict) else None
        if not isinstance(value, str) or not Path(value).is_file():
            blockers.append(f"Missing reviewed evidence file: {field}")
    models = spec["models"]
    if not isinstance(models, dict) or set(models) != {"analyzer_base", "actor"}:
        blockers.append("Fixed actor and original analyzer_base paths required")
    else:
        for role, path in models.items():
            if not isinstance(path, str) or not Path(path).is_dir():
                blockers.append(f"Missing local model directory: {role}")
            elif not (Path(path) / "config.json").is_file() or not any(
                    p.suffix in {".safetensors", ".bin"} for p in Path(path).iterdir() if p.is_file()):
                blockers.append(f"Missing model config/weights: {role}")
    if not isinstance(spec["source_root"], str) or not (Path(spec["source_root"]) / "intentlab/neural.py").is_file():
        blockers.append("Missing source_root with training implementation")
    elif spec["scope"] == "formal":
        git_state = source_git(spec["source_root"])
        if git_state["commit"] is None or not git_state["clean"]:
            blockers.append("Formal source must be a clean Git checkout with a recorded commit")
    dependencies = spec["dependencies"]
    if not isinstance(dependencies, list) or any(not isinstance(name, str) for name in dependencies):
        blockers.append("dependencies must list package names")
    else:
        if spec["scope"] == "formal" and not {"torch", "transformers", "peft", "accelerate", "bitsandbytes"} <= set(dependencies):
            blockers.append("Formal GPU dependency versions must be captured")
        for name in dependencies:
            try:
                importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                blockers.append(f"Dependency not installed: {name}")
    data = spec["dataset"]
    if not isinstance(data, dict) or set(data) != {"cases", "reviews", "adjudications", "export"}:
        blockers.append("Dataset requires cases/reviews/adjudications/export paths")
    else:
        for key in ("cases", "reviews"):
            if not isinstance(data[key], str) or not Path(data[key]).is_file():
                blockers.append(f"Missing annotation input: {key}")
        if data["adjudications"] is not None and (not isinstance(data["adjudications"], str) or not Path(data["adjudications"]).is_file()):
            blockers.append("Missing adjudications file")
        if not isinstance(data["export"], str) or not (Path(data["export"]) / "manifest.json").is_file():
            blockers.append("Missing reviewed data export")
    if blockers:
        return {"ready": False, "blockers": blockers, "scope": spec["scope"]}
    try:
        cases = read_jsonl(data["cases"])
        audit = validate_cases(cases)
        selected, _ = resolve_reviews(cases, read_jsonl(data["reviews"]),
            read_jsonl(data["adjudications"]) if data["adjudications"] else [])
        by_id = {case["case_id"]: case for case in cases}
        if any(cid not in by_id or by_id[cid]["split"] not in {"train", "validation"} for cid in examples):
            raise ValueError("Few-shot selection includes missing or held-out cases")
        minimum = spec["minimum_tasks"]
        if not isinstance(minimum, dict) or set(minimum) != {"train", "validation", "test", "ood"} \
                or any(type(v) is not int or v < 1 for v in minimum.values()):
            raise ValueError("Predeclare positive source-task counts for all four splits")
        for split, count in minimum.items():
            if audit["source_task_groups"].get(split, 0) < count:
                blockers.append(f"Insufficient reviewed source-task groups: {split}")
        manifest = read_json(Path(data["export"]) / "manifest.json")
        expected_hashes = {"cases_hash": digest(cases), "reviews_hash": digest(read_jsonl(data["reviews"])),
            "adjudications_hash": digest(read_jsonl(data["adjudications"]) if data["adjudications"] else [])}
        if manifest.get("kind") != "human_reviewed_diagnostics" or any(manifest.get(k) != v for k, v in expected_hashes.items()):
            raise ValueError("Reviewed export does not match annotation inputs")
        # Validate actual exported content against the reviewed cases; a forged
        # manifest must not silently replace labels, public prompts or task IDs.
        for split in ("train", "validation"):
            exported = read_jsonl(Path(data["export"]) / f"{split}.jsonl")
            original = {case["case_id"]: case for case in cases if case["split"] == split}
            if len(exported) != len(original) or {row.get("case_id") for row in exported} != set(original):
                raise ValueError("Reviewed SFT case coverage mismatch")
            for row in exported:
                case = original[row["case_id"]]
                expected_row = {"task_id": case["source_task_id"], "case_id": case["case_id"],
                    "family": case["family"], "template_id": case["template_id"], "source": case["source"],
                    "prompt": formal_prompt(case["public"]), "completion": canonical({"findings": [
                        selected[case["case_id"]][req["id"]] for req in case["public"]["requirements"]]})}
                if row != expected_row:
                    raise ValueError("Reviewed SFT content mismatch")
        for split in ("test", "ood"):
            sealed = Path(data["export"]) / "heldout" / split
            original = [case for case in cases if case["split"] == split]
            if read_jsonl(sealed / "cases.jsonl") != original:
                raise ValueError("Held-out public case mismatch")
            if read_jsonl(sealed / "gold.jsonl") != [{"case_id": case["case_id"], "findings": [
                    selected[case["case_id"]][req["id"]] for req in case["public"]["requirements"]]} for case in original]:
                raise ValueError("Held-out gold mismatch")
        if training["steps"] * training["batch_size"] * training["accumulation"] < audit["cases"]["train"]:
            blockers.append("Training budget does not cover one pass through the training views")
    except (ValueError, KeyError, TypeError, OSError) as exc:
        blockers.append(str(exc))
    return {"ready": not blockers, "blockers": blockers, "scope": spec["scope"],
            "warning": "Readiness binds supplied reviews/evidence; it does not authenticate people or assess scientific adequacy."}


def freeze(spec, out):
    audit = check_spec(spec)
    if not audit["ready"]:
        raise ValueError("Protocol not ready: " + "; ".join(audit["blockers"]))
    spec = deepcopy(spec)
    spec["source_root"] = str(Path(spec["source_root"]).resolve())
    for key, path in spec["dataset"].items():
        if path is not None:
            spec["dataset"][key] = str(Path(path).resolve())
    spec["models"] = {role: str(Path(path).resolve()) for role, path in spec["models"].items()}
    spec["evidence"] = {name: str(Path(path).resolve()) for name, path in spec["evidence"].items()}
    out = Path(out)
    if out.exists():
        raise ValueError("Frozen protocol must not overwrite prior records")
    data = spec["dataset"]
    export = Path(data["export"]).resolve()
    dataset_files = {path.relative_to(export).as_posix(): file_hash(path)
                     for path in sorted([*export.rglob("*.jsonl"), export / "manifest.json"])}
    cache, models, official_checks = {}, {}, {}
    for role, path in spec["models"].items():
        key = str(Path(path).resolve())
        if key not in cache:
            cache[key] = model_snapshot(path)
        models[role] = cache[key]
        if spec["scope"] == "formal":
            if key not in official_checks:
                official_checks[key] = verify_official_assets(cache[key], spec["source_root"])
    bundle = {"kind": "experiment_protocol_lock", "schema_version": 1, "spec": spec,
        "created_utc": datetime.now(timezone.utc).isoformat(), "scope": spec["scope"],
        "source": source_snapshot(spec["source_root"]), "models": models,
        "source_git": source_git(spec["source_root"]),
        "official_asset_checks": official_checks,
        "dataset_export": {"root": str(export), "files_sha256": dataset_files},
        "evidence": {name: {"path": str(Path(path).resolve()), "sha256": file_hash(path)}
                     for name, path in spec["evidence"].items()},
        "annotation_inputs": {name: {"path": str(Path(path).resolve()), "sha256": file_hash(path)}
                              for name, path in data.items() if name != "export" and path is not None},
        "environment": {"python": platform.python_version(), "packages": {
            name: importlib.metadata.version(name) for name in spec["dependencies"]}},
        "readiness": audit,
        "warning": "Content freeze is not an external preregistration timestamp, identity proof or scientific quality guarantee."}
    bundle["lock_hash"] = digest(bundle)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents a concurrent invocation replacing a freeze.
    with out.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(bundle, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return bundle


def verify(lock, phase="training"):
    if phase not in {"training", "all"}:
        raise ValueError("Unsupported verification phase")
    payload = {key: value for key, value in lock.items() if key != "lock_hash"}
    if lock.get("kind") != "experiment_protocol_lock" or digest(payload) != lock.get("lock_hash"):
        raise ValueError("Protocol lock content changed")
    spec = lock["spec"]
    if source_snapshot(spec["source_root"]) != lock["source"]:
        raise ValueError("Implementation/configuration changed after freeze")
    if lock["scope"] == "formal":
        current_git = source_git(spec["source_root"])
        if current_git != lock["source_git"] or not current_git["clean"]:
            raise ValueError("Frozen formal Git commit/worktree changed")
    if platform.python_version() != lock["environment"]["python"] or any(
            importlib.metadata.version(name) != version for name, version in lock["environment"]["packages"].items()):
        raise ValueError("Runtime versions changed after freeze")
    checked = set()
    for model in lock["models"].values():
        if model["path"] not in checked:
            if model_snapshot(model["path"]) != model:
                raise ValueError("Model weights/config/tokenizer changed after freeze")
            checked.add(model["path"])
    root = Path(lock["dataset_export"]["root"])
    dataset_files = lock["dataset_export"]["files_sha256"]
    needed = ("train.jsonl", "validation.jsonl") if phase == "training" else tuple(dataset_files)
    for name in needed:
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or name not in dataset_files:
            raise ValueError("Invalid frozen dataset path")
        if file_hash(root / name) != dataset_files[name]:
            raise ValueError("Dataset content changed after freeze: " + name)
    if phase == "all":
        actual_files = {path.relative_to(root).as_posix() for path in root.rglob("*.jsonl")} | {"manifest.json"}
        if actual_files != set(dataset_files):
            raise ValueError("Frozen dataset file coverage changed")
        for record in list(lock["evidence"].values()) + list(lock["annotation_inputs"].values()):
            if file_hash(record["path"]) != record["sha256"]:
                raise ValueError("Evidence or annotation input changed after freeze")
    return {"verified": True, "phase": phase, "lock_hash": lock["lock_hash"],
            "heldout_gold_opened": phase == "all"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "freeze", "verify", "model-check"])
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--lock", type=Path)
    parser.add_argument("--phase", choices=["training", "all"], default="training")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--source-root", type=Path, default=Path("."))
    args = parser.parse_args()
    if args.command == "model-check":
        if args.model is None:
            parser.error("--model required")
        snapshot = model_snapshot(args.model)
        result = {"kind": "official_model_asset_verification", "snapshot": snapshot,
                  "official": verify_official_assets(snapshot, args.source_root)}
        if args.out:
            if args.out.exists():
                parser.error("Choose a fresh model verification path")
            save_json(args.out, result)
    elif args.command == "verify":
        if args.lock is None:
            parser.error("--lock required")
        result = verify(read_json(args.lock), args.phase)
    else:
        if args.spec is None:
            parser.error("--spec required")
        spec = read_json(args.spec)
        result = check_spec(spec) if args.command == "check" else freeze(spec, args.out) if args.out else None
        if result is None:
            parser.error("--out required for freeze")
        if args.command == "check" and args.out:
            if args.out.exists():
                parser.error("Choose a fresh readiness report path")
            save_json(args.out, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "check" and not result["ready"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
