"""Schema-first diagnostic inference with no gold input for evaluated cases."""

import argparse
import hashlib
import json
from pathlib import Path
import time

from .core import canonical, digest
from .formal_data import formal_prompt, normalized_request, read_jsonl, resolve_reviews, validate_cases
from .model_backend import LocalBackend
from .report import save_json


def reviewed_examples(cases, reviews, adjudications=(), limit=3, case_ids=None):
    if type(limit) is not int or limit < 1 or any(row["split"] not in {"train", "validation"} for row in cases):
        raise ValueError("Few-shot examples must be reviewed train/development cases")
    labels, _ = resolve_reviews(cases, reviews, adjudications)
    by_id = {row["case_id"]: row for row in cases}
    if case_ids is not None:
        if not case_ids or len(set(case_ids)) != len(case_ids) or any(cid not in by_id for cid in case_ids):
            raise ValueError("Few-shot IDs must be unique reviewed development cases")
        selected = [by_id[cid] for cid in case_ids]
    else:
        selected = sorted(cases, key=lambda row: row["case_id"])[:limit]
    return [{"case": row, "findings": [labels[row["case_id"]][req["id"]]
                for req in row["public"]["requirements"]]}
            for row in selected]


def reject_example_overlap(cases, examples):
    for example in examples:
        source = example["case"]
        for row in cases:
            if any(row[key] == source[key] for key in ("case_id", "source_task_id", "template_id")):
                raise ValueError("Few-shot example overlaps evaluation identity or template")
            if normalized_request(row["public"]["request"]) == normalized_request(source["public"]["request"]):
                raise ValueError("Few-shot example duplicates evaluation request")
            if row["split"] == "ood" and row["family"] == source["family"]:
                raise ValueError("Few-shot example leaks OOD family")


def diagnostic_prompt(case, examples=()):
    reject_example_overlap([case], examples)
    prefix = ""
    if examples:
        prefix = "Reviewed examples (do not reuse their answers for the new observation):\n" + canonical([
            {"input": row["case"]["public"], "output": {"findings": row["findings"]}} for row in examples]) + "\n"
    return prefix + formal_prompt(case["public"])


def run_diagnostics(cases, backend, out, examples=(), model_identity=None):
    validate_cases(cases)
    reject_example_overlap(cases, examples)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    manifest = {"kind": "formal_diagnostic_inference", "cases_hash": digest(cases),
        "examples_hash": digest(examples), "example_count": len(examples), "model_identity": model_identity,
        "condition": "schema_fewshot" if examples else "schema_zero_shot", "status": "running",
        "budget_unit": "diagnostic evidence view; reset per case", "gold_loaded": False,
        "effective_context_limit": getattr(backend, "context", None),
        "case_count": len(cases), "errors": 0,
        "warning": "Inference completion is not a diagnostic accuracy result or preregistration."}
    save_json(out / "manifest.json", manifest)
    started = time.perf_counter()
    with (out / "predictions.jsonl").open("w", encoding="utf-8", newline="\n") as predictions, \
         (out / "calls.jsonl").open("w", encoding="utf-8", newline="\n") as calls:
        for row in cases:
            backend.reset()
            prompt = diagnostic_prompt(row, examples)
            record = {"case_id": row["case_id"], "prompt_hash": digest(prompt)}
            call_start = time.perf_counter()
            try:
                result = backend.complete(prompt, role="analyzer")
                text = result["text"]
                record.update(status="generated", usage=result["usage"])
            except (ValueError, RuntimeError, OSError, TimeoutError) as exc:
                text = ""
                record.update(status="error", error_type=type(exc).__name__, error=str(exc))
                manifest["errors"] += 1
            record["seconds"] = time.perf_counter() - call_start
            record["budget"] = backend.ledger.snapshot()
            predictions.write(canonical({"case_id": row["case_id"], "text": text}) + "\n")
            calls.write(canonical(record) + "\n")
            predictions.flush()
            calls.flush()
    manifest.update(status="completed", seconds=time.perf_counter() - started,
        file_sha256={path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                     for path in (out / "predictions.jsonl", out / "calls.jsonl")})
    save_json(out / "manifest.json", manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    parser.add_argument("--max-new-tokens", type=int, default=512)
    parser.add_argument("--token-budget", type=int, default=8192)
    parser.add_argument("--context-limit", type=int, default=2048)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--example-cases", type=Path)
    parser.add_argument("--example-reviews", type=Path)
    parser.add_argument("--example-adjudications", type=Path)
    parser.add_argument("--example-count", type=int, default=3)
    parser.add_argument("--example-ids", nargs="+", help="Explicit reviewed IDs in frozen order; overrides example-count")
    args = parser.parse_args()
    cases = read_jsonl(args.cases)
    validate_cases(cases)
    examples = []
    if args.example_cases or args.example_reviews or args.example_adjudications:
        if args.example_cases is None or args.example_reviews is None:
            parser.error("Both --example-cases and --example-reviews required")
        examples = reviewed_examples(read_jsonl(args.example_cases), read_jsonl(args.example_reviews),
            read_jsonl(args.example_adjudications) if args.example_adjudications else [], args.example_count, args.example_ids)
    elif args.example_ids:
        parser.error("--example-ids requires reviewed example inputs")
    reject_example_overlap(cases, examples)
    if args.out.exists():
        parser.error("Choose a new output directory; do not overwrite prior predictions")
    from .neural import local_model_fingerprint
    identity = {"path": str(args.model.resolve()), "weights_fingerprint": local_model_fingerprint(args.model),
                "device": args.device, "max_new_tokens": args.max_new_tokens, "token_budget": args.token_budget,
                "context_limit": args.context_limit}
    backend = LocalBackend(args.model, args.device, args.max_new_tokens, args.token_budget, context_limit=args.context_limit)
    try:
        print(json.dumps(run_diagnostics(cases, backend, args.out, examples, identity), indent=2))
    finally:
        backend.close()


if __name__ == "__main__":
    main()
