"""Audit development context lengths and create synthetic hardware stress data."""

import argparse
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from intentlab.core import canonical, digest
from intentlab.formal_data import formal_prompt, read_jsonl, validate_cases, write_jsonl
from intentlab.prompts import prompt_ids


def lengths(tokenizer, cases, context=2048, maximum=512, budget=8192):
    validate_cases(cases)
    if any(case["split"] not in {"train", "validation"} for case in cases):
        raise ValueError("Public development audit must not expose test/OOD")
    if any(type(n) is not int or n < 1 for n in (context, maximum, budget)):
        raise ValueError("Positive token budgets required")
    rows = []
    for case in cases:
        prompt = formal_prompt(case["public"])
        n = len(prompt_ids(tokenizer, prompt))
        allowance = max(0, min(maximum, context - n, budget - n))
        rows.append({"case_id": case["case_id"], "source_task_id": case["source_task_id"],
            "prompt_hash": digest(prompt), "prompt_tokens": n, "generation_allowance": allowance,
            "full_generation_reservation_fits": allowance == maximum})
    return {"scope": "development", "prompt_only": True, "cases_hash": digest(cases),
        "rows": rows, "min_prompt_tokens": min(r["prompt_tokens"] for r in rows),
        "max_prompt_tokens": max(r["prompt_tokens"] for r in rows), "context_limit": context,
        "max_new_tokens": maximum, "token_budget": budget,
        "cannot_generate": sum(r["generation_allowance"] == 0 for r in rows),
        "cannot_reserve_full_generation": sum(not r["full_generation_reservation_fits"] for r in rows),
        "fewshot_audited": False, "reviewed_training_target_lengths_audited": False,
        "formal_length_compute_review_complete": False,
        "warning": "Zero-shot public prompt lengths only. No gold, human labels, few-shot targets, training memory or formal budget approval are inferred."}


def stress_data(tokenizer, length, out):
    if type(length) is not int or not 512 <= length <= 4096:
        raise ValueError("Stress length must be in [512, 4096]")
    out = Path(out)
    completion = canonical({"hardware_probe": "synthetic-no-task-label"})
    target_length = len(tokenizer.encode(completion, add_special_tokens=False)) + int(tokenizer.eos_token_id is not None)
    examples = []
    for name in ("train-a", "train-b", "validation"):
        prefix = "Synthetic hardware stress input " + name + "; no user task or requirement label.\n"
        n = length - target_length - len(prompt_ids(tokenizer, prefix))
        for _ in range(8):
            prompt = prefix + " x" * n
            actual = len(prompt_ids(tokenizer, prompt)) + target_length
            if actual == length:
                break
            n += length - actual
        if actual != length:
            raise ValueError(f"Stress filler did not produce exact length: {actual} != {length}")
        examples.append({"task_id": "hardware-probe-" + name, "prompt": prompt, "completion": completion})
    out.mkdir(parents=True, exist_ok=False)
    write_jsonl(out / "train.jsonl", examples[:2])
    write_jsonl(out / "validation.jsonl", examples[2:])
    # Any accidental test access must fail rather than silently evaluating.
    (out / "test.jsonl").write_text("DO NOT READ: NO TEST DATA EXISTS FOR THIS HARDWARE PROBE\n", encoding="utf-8", newline="\n")
    report = {"scope": "synthetic_hardware_stress_only", "actual_sequence_tokens": length,
        "target_tokens_per_example": target_length, "human_task_labels": False,
        "formal_training": False, "test_file_is_deliberately_invalid": True,
        "warning": "Targets are unrelated synthetic strings. Finite losses or selected exports have no research-quality meaning. Use --defer-test; do not use adapters as experimental endpoints.",
        "files_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}}
    (out / "manifest.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["lengths", "stress-data"])
    parser.add_argument("--model", required=True)
    parser.add_argument("--cases", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--length", type=int, default=2048)
    args = parser.parse_args()
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(args.model, trust_remote_code=False, local_files_only=True)
    if args.command == "lengths":
        if args.cases is None:
            parser.error("lengths requires --cases")
        result = lengths(tokenizer, read_jsonl(args.cases))
        with args.out.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    else:
        result = stress_data(tokenizer, args.length, args.out)
    print(json.dumps({k: v for k, v in result.items() if k not in {"rows", "files_sha256"}}, indent=2))
