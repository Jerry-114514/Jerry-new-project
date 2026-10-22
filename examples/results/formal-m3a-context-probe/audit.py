"""Verify public resource evidence; optional real-tokenizer reproduction."""

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from intentlab.core import canonical, digest
from intentlab.formal_data import formal_prompt, read_jsonl


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def audit(root, tokenizer=None):
    root = Path(root)
    identity, lengths = read(root / "runtime-identity.json"), read(root / "lengths.json")
    cases = read_jsonl(root.parent / "formal-m2a-natural-training/annotation-intake/coordinator-cases.jsonl")
    if lengths["cases_hash"] != digest(cases) or len(lengths["rows"]) != len(cases):
        raise ValueError("Length report population changed")
    for case, row in zip(cases, lengths["rows"]):
        n = row["prompt_tokens"]
        allowance = max(0, min(lengths["max_new_tokens"], lengths["context_limit"] - n, lengths["token_budget"] - n))
        if case["split"] != "train" or row["case_id"] != case["case_id"] or row["source_task_id"] != case["source_task_id"] \
                or row["prompt_hash"] != digest(formal_prompt(case["public"])) or type(n) is not int or n < 1 \
                or row["generation_allowance"] != allowance or row["full_generation_reservation_fits"] != (allowance == lengths["max_new_tokens"]):
            raise ValueError("Prompt population, hash or token allowance changed")
    if lengths["min_prompt_tokens"] != min(r["prompt_tokens"] for r in lengths["rows"]) \
            or lengths["max_prompt_tokens"] != max(r["prompt_tokens"] for r in lengths["rows"]) \
            or lengths["cannot_generate"] != sum(r["generation_allowance"] == 0 for r in lengths["rows"]) \
            or lengths["cannot_reserve_full_generation"] != sum(not r["full_generation_reservation_fits"] for r in lengths["rows"]):
        raise ValueError("Length summary changed")
    for name, field in (("context_probe.py", "probe_script_sha256"), ("run_stress.py", "runner_script_sha256")):
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != identity[field]:
            raise ValueError("Actual probe script changed")
    if identity["formal_training_started"] or identity["formal_budget_approved"] \
            or lengths["fewshot_audited"] or lengths["reviewed_training_target_lengths_audited"] \
            or lengths["formal_length_compute_review_complete"]:
        raise ValueError("Engineering scope changed into a formal completion claim")
    attempts = read(root / "attempts.json")["attempts"]
    if [a["length"] for a in attempts] != [1024, 2048] or any(a["status"] != "completed" or a["exit_code"] != 0 for a in attempts):
        raise ValueError("Both recorded stress attempts required")
    results = []
    base = set()
    for attempt in attempts:
        n = attempt["length"]
        data = root / f"data-{n}"
        manifest = read(data / "manifest.json")
        for name, expected in manifest["files_sha256"].items():
            if hashlib.sha256((data / name).read_bytes()).hexdigest() != expected:
                raise ValueError("Synthetic probe data changed")
        result, config = read(root / f"train-{n}/result.json"), read(root / f"train-{n}/run_config.json")
        if result["config"] != config or not result["completed"] or result["step"] != 2 or result.get("test_deferred") is not True \
                or "test" in result or result["train_tokens"] != 4 * n or result["supervised_tokens"] != 4 * manifest["target_tokens_per_example"] \
                or result["examples_seen"] != 4 or sum(row["count"] for row in result["sample_exposures"]) != 4 \
                or any(config[key] != value for key, value in {"mode": "qlora", "device": "cuda", "steps": 2,
                    "batch_size": 1, "accumulation": 2, "rank": 16, "alpha": 32, "max_length": n, "defer_test": True}.items()):
            raise ValueError("Stress configuration, actual exposure or test isolation changed")
        if len(result["history"]) != 2 or any(not math.isfinite(row[key]) for row in result["history"] for key in ("train_loss", "gradient_norm")) \
                or any(not math.isfinite(row["validation"]["loss"]) for row in result["history"]):
            raise ValueError("Two finite training/validation steps required")
        if not 0 < result["peak_allocated_bytes"] <= result["peak_reserved_bytes"] or result["seconds_this_invocation"] <= 0:
            raise ValueError("Invalid observed timing or memory")
        base.add(result["base_identity"])
        results.append({"sequence_tokens": n, "updates": result["step"],
            "allocated_gib": result["peak_allocated_bytes"] / 2**30, "reserved_gib": result["peak_reserved_bytes"] / 2**30,
            "training_loop_seconds": result["seconds_this_invocation"], "whole_invocation_wall_seconds": attempt["wall_seconds"]})
    if len(base) != 1:
        raise ValueError("Different base tensors across stress lengths")
    if tokenizer is not None:
        spec = importlib.util.spec_from_file_location("context_probe", root / "context_probe.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        if canonical(module.lengths(tokenizer, cases)) != canonical(lengths):
            raise ValueError("Actual tokenization differs from the archived length report")
        with tempfile.TemporaryDirectory() as d:
            for n in (1024, 2048):
                out = Path(d) / str(n)
                module.stress_data(tokenizer, n, out)
                for p in out.iterdir():
                    if p.read_bytes() != (root / f"data-{n}" / p.name).read_bytes():
                        raise ValueError("Actual stress sequence tokenization/data differs")
    return {"scope": "synthetic_hardware_stress_only", "length_views_checked": len(cases), "results": results,
        "actual_tokenizer_reproduction": tokenizer is not None, "human_reviews_completed": 0,
        "formal_training_started": False, "formal_budget_approved": False,
        "warning": "Short unrelated-target probes, not formal quality, a universal VRAM bound, 4096-token feasibility, RAM profiling or a six-run time estimate. PyTorch peaks exclude earlier model-loading peaks and external CUDA allocations."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Optional local original tokenizer for actual byte-for-byte regeneration")
    args = parser.parse_args()
    tokenizer = None
    if args.model:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=False, local_files_only=True)
    root = Path(__file__).resolve().parent
    report = audit(root, tokenizer)
    name = "tokenizer-verification.json" if tokenizer is not None else "verification.json"
    (root / name).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    sums = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and p.name != "checksums.json" and "__pycache__" not in p.parts}
    (root / "checksums.json").write_text(json.dumps(sums, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
