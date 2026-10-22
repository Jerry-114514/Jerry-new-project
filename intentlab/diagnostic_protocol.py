"""Frozen nine-condition diagnostic generation, then a separate one-time reveal.

Only reveal reads held-out gold. Neither entry changes training or selects
models using held-out results. A failed claimed attempt requires explicit
coordinator investigation; changing the output path does not restart it.
"""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
import math
import os
from pathlib import Path
import socket

from .core import State, canonical, digest
from .execution_analysis import analyze_execution
from .execution_data import load_execution_tasks
from .execution_models import verify_execution_models
from .execution_protocol import contract_identity
from .formal_data import formal_prompt, read_jsonl, validate_cases, validate_findings, write_jsonl
from .formal_eval import paired_task_bootstrap, score_predictions
from .formal_inference import reject_example_overlap, run_diagnostics
from .model_backend import LocalBackend
from .protocol import file_hash, read_json
from .report import save_json


CONDITIONS = ["A", "B", "C"] + [f"{name}-seed-{seed}" for name in ("D", "E") for seed in (0, 1, 2)]


def claim(protocol, phase, out):
    # Shared across arbitrary output locations; keep this coordinator directory
    # persistent. This is an operational guard, not tamper-proof preregistration.
    path = Path(protocol["dataset_export"]["root"]).parent / f"diagnostic-{protocol['lock_hash']}-{phase}.claim.json"
    record = {"phase": phase, "protocol_hash": protocol["lock_hash"], "out": str(Path(out).resolve()),
              "pid": os.getpid(), "host": socket.gethostname(), "created_utc": datetime.now(timezone.utc).isoformat()}
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(canonical(record) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return record


def frozen_rows(protocol, relative):
    if relative not in protocol["dataset_export"]["files_sha256"]:
        raise ValueError("Missing frozen diagnostic input: " + relative)
    path = Path(protocol["dataset_export"]["root"]) / relative
    if file_hash(path) != protocol["dataset_export"]["files_sha256"][relative]:
        raise ValueError("Frozen diagnostic input changed: " + relative)
    rows = read_jsonl(path)
    if file_hash(path) != protocol["dataset_export"]["files_sha256"][relative]:
        raise ValueError("Frozen diagnostic input changed while reading: " + relative)
    return rows


def public_inputs(protocol):
    cases = [row for split in ("test", "ood") for row in frozen_rows(protocol, f"heldout/{split}/cases.jsonl")]
    validate_cases(cases)
    if {row["split"] for row in cases} != {"test", "ood"}:
        raise ValueError("Both test and OOD public cases required")
    record = protocol["annotation_inputs"]["cases"]
    if file_hash(record["path"]) != record["sha256"]:
        raise ValueError("Public source cases changed")
    source_cases = read_jsonl(record["path"])
    validate_cases(source_cases)  # Strict public case schema, no review/gold fields.
    sources = {row["case_id"]: row for row in source_cases}
    pairs = {row["case_id"]: row for split in ("train", "validation") for row in frozen_rows(protocol, split + ".jsonl")}
    examples = []
    for cid in protocol["spec"]["few_shot_case_ids"]:
        row, pair = sources[cid], pairs[cid]
        if row["split"] not in {"train", "validation"} or pair["prompt"] != formal_prompt(row["public"]):
            raise ValueError("Few-shot public case differs from its reviewed development export")
        value = json.loads(pair["completion"])
        if set(value) != {"findings"}:
            raise ValueError("Invalid reviewed example completion")
        validate_findings(value["findings"], row["public"])
        examples.append({"case": row, "findings": value["findings"]})
    if not examples:
        raise ValueError("Frozen reviewed few-shot examples required")
    reject_example_overlap(cases, examples)
    record = protocol["execution_binding"]["files"]["tasks"]
    if file_hash(record["path"]) != record["sha256"]:
        raise ValueError("Frozen public execution tasks changed")
    tasks = load_execution_tasks(record["path"])
    indexed = {contract_identity(task, dict(request=task["request"], inputs=task["inputs"],
                requirements=task["requirements"], execution_spec=task["spec"])): task for task in tasks}
    if len(indexed) != len(tasks) or set(indexed) != {contract_identity(row, row["public"]) for row in cases}:
        raise ValueError("Public diagnostic contracts differ from frozen execution tasks")
    return cases, examples, indexed


def model_path(protocol, binding, condition):
    if condition in {"A", "B"}:
        return protocol["models"]["analyzer_base"]["path"]
    schedule = {"D": "cosine", "E": "plateau"}[condition[0]]
    return str(Path(binding["matrix"]["root"]) / (schedule + condition[1:]) / "model")


def backend_for(protocol, path, factory=None):
    if factory is not None and protocol["scope"] != "engineering":
        raise ValueError("Injected test backends are forbidden in formal evaluation")
    if protocol["scope"] == "formal" and Path(path).resolve() != Path(protocol["models"]["analyzer_base"]["path"]):
        adapter = read_json(Path(path) / "adapter_config.json")
        if (Path(path) / "tiny_base_recipe.json").exists() or adapter.get("peft_type") != "LORA" \
                or Path(adapter["base_model_name_or_path"]).resolve() != Path(protocol["models"]["analyzer_base"]["path"]):
            raise ValueError("Every formal D/E export must use the frozen original base")
    budgets = protocol["spec"]["budgets"]
    return (factory or LocalBackend)(path, device=protocol["spec"]["training"]["device"],
        max_new_tokens=budgets["max_new_tokens"], token_budget=budgets["token_budget"], context_limit=budgets["context_limit"])


def rule_predictions(cases, tasks, out):
    out.mkdir()
    predictions = []
    for row in cases:
        public = row["public"]
        task = tasks[contract_identity(row, public)]
        obs = public["observation"]
        state = State(deepcopy(obs["files"]), deepcopy(obs["events"] or []))
        findings = analyze_execution(task, state, events_visible=obs["events"] is not None)
        findings = [{key: item[key] for key in ("id", "status", "evidence")} for item in findings]
        validate_findings(findings, public)
        predictions.append({"case_id": row["case_id"], "text": canonical({"findings": findings})})
    write_jsonl(out / "predictions.jsonl", predictions)
    write_jsonl(out / "calls.jsonl", [{"case_id": row["case_id"], "status": "public_rule", "model_calls": 0} for row in cases])
    save_json(out / "manifest.json", {"status": "completed", "condition": "public_rule", "gold_loaded": False,
              "warning": "Uses only coded public rules, not independent static references."})


def seal_files(root):
    return {p.relative_to(root).as_posix(): file_hash(p) for p in sorted(root.rglob("*"))
            if p.is_file() and p != root / "manifest.json"}


def generate(protocol, binding, out, engineering=False, backend_factory=None):
    verify_execution_models(protocol, binding, engineering)
    if backend_factory is not None and protocol["scope"] != "engineering":
        raise ValueError("Injected test backends are forbidden in formal evaluation")
    out = Path(out)
    if out.exists():
        raise ValueError("Choose a fresh diagnostic generation directory")
    attempt = claim(protocol, "generation", out)
    out.mkdir(parents=True, exist_ok=False)
    manifest = {"kind": "frozen_diagnostic_predictions", "schema_version": 1, "scope": protocol["scope"],
        "protocol_hash": protocol["lock_hash"], "model_binding_hash": binding["binding_hash"], "status": "running",
        "conditions": CONDITIONS, "claim": attempt, "gold_loaded": False,
        "test_backend_injected": backend_factory is not None,
        "warning": "Predictions only; not an accuracy result, formal data certification or durable model backup."}
    save_json(out / "manifest.json", manifest)
    try:
        cases, examples, tasks = public_inputs(protocol)
        manifest.update(cases_hash=digest(cases), examples_hash=digest(examples))
        for condition in CONDITIONS:
            manifest["active_condition"] = condition
            save_json(out / "manifest.json", manifest)
            if condition == "C":
                rule_predictions(cases, tasks, out / condition)
                continue
            backend = backend_for(protocol, model_path(protocol, binding, condition), backend_factory)
            try:
                run_diagnostics(cases, backend, out / condition, examples if condition == "B" else (),
                    {"frozen_condition": condition, "binding_hash": binding["binding_hash"]})
            finally:
                backend.close()
        verify_execution_models(protocol, binding, engineering)
        # Recheck public input bytes after all conditions; no gold is opened.
        again, ex, _ = public_inputs(protocol)
        if digest(again) != manifest["cases_hash"] or digest(ex) != manifest["examples_hash"]:
            raise ValueError("Public diagnostic input changed during generation")
        manifest.update(status="sealed", files_sha256=seal_files(out))
        manifest["seal_hash"] = digest(manifest)
    except Exception as exc:
        manifest.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        save_json(out / "manifest.json", manifest)
        raise
    save_json(out / "manifest.json", manifest)
    return manifest


def verify_predictions(protocol, binding, directory, engineering=False):
    verify_execution_models(protocol, binding, engineering)
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    if manifest.get("kind") != "frozen_diagnostic_predictions" or manifest.get("status") != "sealed" \
            or manifest.get("conditions") != CONDITIONS or manifest.get("gold_loaded") is not False \
            or manifest.get("scope") != protocol["scope"] or manifest.get("protocol_hash") != protocol["lock_hash"] \
            or manifest.get("model_binding_hash") != binding["binding_hash"] \
            or manifest.get("seal_hash") != digest({k: v for k, v in manifest.items() if k != "seal_hash"}) \
            or seal_files(directory) != manifest["files_sha256"]:
        raise ValueError("Diagnostic predictions are incomplete, changed or from another protocol")
    if protocol["scope"] == "formal" and manifest["test_backend_injected"]:
        raise ValueError("Injected model predictions cannot be formal evidence")
    cases, examples, _ = public_inputs(protocol)
    if manifest["cases_hash"] != digest(cases) or manifest["examples_hash"] != digest(examples):
        raise ValueError("Sealed diagnostic inputs changed")
    expected = {row["case_id"] for row in cases}
    for condition in CONDITIONS:
        if read_json(directory / condition / "manifest.json")["status"] != "completed":
            raise ValueError("Condition generation did not complete")
        rows = read_jsonl(directory / condition / "predictions.jsonl")
        if len(rows) != len(expected) or {row["case_id"] for row in rows} != expected \
                or any(set(row) != {"case_id", "text"} or not isinstance(row["text"], str) for row in rows):
            raise ValueError("All conditions must retain exactly all cases, including failed predictions")
    return manifest, cases


def heldout_loss(protocol, path, cases, gold, record_path):
    """Identical inference precision for all D/E exports; no fitting or selection."""
    from .neural import batch_tensors, encode_pair, token_loss
    backend = backend_for(protocol, path)
    records = []
    try:
        with Path(record_path).open("x", encoding="utf-8", newline="\n") as stream:
            for row in cases:
                if backend.device == "cuda":
                    from .gpu_lease import ensure_gpu_lease
                    ensure_gpu_lease()
                pair = {"task_id": row["source_task_id"], "prompt": formal_prompt(row["public"]),
                        "completion": canonical({"findings": [gold[row["case_id"]][req["id"]] for req in row["public"]["requirements"]]})}
                encoded = encode_pair(backend.tokenizer, pair, min(backend.context, protocol["spec"]["training"]["max_length"]))
                batch = batch_tensors([encoded], backend.tokenizer.pad_token_id, backend.device)
                with backend.torch.no_grad():
                    loss, count = token_loss(backend.model, batch)
                total = float(loss.item())
                if not math.isfinite(total) or total < 0:
                    raise ValueError("Invalid held-out target loss")
                records.append({"case_id": row["case_id"], "source_task_id": row["source_task_id"],
                                "split": row["split"], "loss_sum": total, "target_tokens": count})
                stream.write(canonical(records[-1]) + "\n")
                stream.flush()
    finally:
        backend.close()
    return records


def reveal(protocol, binding, predictions, out, engineering=False, loss_function=None):
    manifest, cases = verify_predictions(protocol, binding, predictions, engineering)
    if loss_function is not None and protocol["scope"] != "engineering":
        raise ValueError("Injected test loss is forbidden in formal evaluation")
    out, predictions = Path(out), Path(predictions)
    if out.exists():
        raise ValueError("Choose a fresh reveal directory")
    attempt = claim(protocol, "reveal", out)  # Durable marker precedes the first gold read.
    out.mkdir(parents=True, exist_ok=False)
    receipt = {"kind": "frozen_diagnostic_reveal", "schema_version": 1, "scope": protocol["scope"],
        "protocol_hash": protocol["lock_hash"], "model_binding_hash": binding["binding_hash"],
        "prediction_seal_hash": manifest["seal_hash"], "claim": attempt, "status": "running",
        "test_loss_injected": loss_function is not None, "gold_opened_after_claim": True}
    save_json(out / "manifest.json", receipt)
    try:
        gold = {}
        for split in ("test", "ood"):
            for row in frozen_rows(protocol, f"heldout/{split}/gold.jsonl"):
                if set(row) != {"case_id", "findings"} or row["case_id"] in gold:
                    raise ValueError("Malformed or duplicate held-out gold")
                gold[row["case_id"]] = row["findings"]
        if set(gold) != {row["case_id"] for row in cases}:
            raise ValueError("Held-out gold coverage differs")
        gold = {row["case_id"]: validate_findings(gold[row["case_id"]], row["public"]) for row in cases}
        scores, losses = {}, {}
        for condition in CONDITIONS:
            raw = read_jsonl(predictions / condition / "predictions.jsonl")
            scores[condition] = {}
            for split in ("test", "ood"):
                subset = [row for row in cases if row["split"] == split]
                ids = {row["case_id"] for row in subset}
                scores[condition][split] = score_predictions(subset,
                    {case["case_id"]: [gold[case["case_id"]][req["id"]] for req in case["public"]["requirements"]] for case in subset},
                    [row for row in raw if row["case_id"] in ids])
        save_json(out / "scores.json", scores)
        populations = None
        for condition in CONDITIONS[3:]:
            receipt["active_loss_condition"] = condition
            save_json(out / "manifest.json", receipt)
            loss_path = out / (condition + "-loss.jsonl")
            rows = (loss_function(protocol, model_path(protocol, binding, condition), cases, gold) if loss_function
                    else heldout_loss(protocol, model_path(protocol, binding, condition), cases, gold, loss_path))
            indexed = {row["case_id"]: row for row in rows}
            if len(indexed) != len(rows) or set(indexed) != set(gold) or any(
                    type(row["target_tokens"]) is not int or row["target_tokens"] < 1
                    or not math.isfinite(row["loss_sum"]) or row["loss_sum"] < 0
                    or row["source_task_id"] != case["source_task_id"] or row["split"] != case["split"]
                    for case in cases for row in [indexed[case["case_id"]]]):
                raise ValueError("Invalid complete held-out loss records")
            tokens = {cid: row["target_tokens"] for cid, row in indexed.items()}
            if populations is not None and tokens != populations:
                raise ValueError("Target token populations differ between D/E models")
            populations = tokens
            if loss_function:
                write_jsonl(loss_path, rows)
            losses[condition] = {}
            for split in ("test", "ood"):
                group = [row for row in rows if row["split"] == split]
                total, count = sum(row["loss_sum"] for row in group), sum(row["target_tokens"] for row in group)
                losses[condition][split] = {"loss_sum": total, "target_tokens": count, "loss": total / count}
        save_json(out / "losses.json", losses)
        stats = protocol["spec"]["statistics"]
        comparisons = {condition: {split: paired_task_bootstrap(scores["B"][split]["per_task_error_rate"],
            scores[condition][split]["per_task_error_rate"], seed=stats["bootstrap_seed"], samples=stats["bootstrap_samples"])
            for split in ("test", "ood")} for condition in CONDITIONS[3:6]}
        save_json(out / "rq1-per-seed.json", comparisons)
        verify_predictions(protocol, binding, predictions, engineering)
        receipt.update(status="completed", files_sha256=seal_files(out),
            loss_precision="BF16 model + FP32 summed CE on CUDA; FP32 CPU; identical for all six exports",
            warning="Seedwise task-conditional RQ1 intervals only. M8 seed aggregation, RQ4 cluster inference and Holm reporting remain required.")
        receipt["receipt_hash"] = digest(receipt)
    except Exception as exc:
        receipt.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        save_json(out / "manifest.json", receipt)
        raise
    save_json(out / "manifest.json", receipt)
    return receipt


def verify_reveal(protocol, binding, predictions, directory, engineering=False):
    """Validate M5 completion for later execution without reopening gold."""
    sealed, _ = verify_predictions(protocol, binding, predictions, engineering)
    directory = Path(directory)
    receipt = read_json(directory / "manifest.json")
    required = {"scores.json", "losses.json", "rq1-per-seed.json"} | {name + "-loss.jsonl" for name in CONDITIONS[3:]}
    if receipt.get("kind") != "frozen_diagnostic_reveal" or receipt.get("status") != "completed" \
            or receipt.get("scope") != protocol["scope"] or receipt.get("protocol_hash") != protocol["lock_hash"] \
            or receipt.get("model_binding_hash") != binding["binding_hash"] \
            or receipt.get("prediction_seal_hash") != sealed["seal_hash"] \
            or receipt.get("receipt_hash") != digest({k: v for k, v in receipt.items() if k != "receipt_hash"}) \
            or seal_files(directory) != receipt.get("files_sha256") \
            or not required <= set(receipt["files_sha256"]):
        raise ValueError("Missing, changed or incomplete M5 completion receipt")
    if protocol["scope"] == "formal" and receipt["test_loss_injected"]:
        raise ValueError("Injected test losses cannot be formal evidence")
    return {"verified": True, "status": receipt["status"], "scope": receipt["scope"],
            "protocol_hash": protocol["lock_hash"], "receipt_hash": receipt["receipt_hash"], "gold_reopened": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["generate", "verify", "reveal", "verify-reveal"])
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--predictions", type=Path)
    parser.add_argument("--reveal", type=Path, help="Completed reveal directory for verify-reveal")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--engineering", action="store_true")
    args = parser.parse_args()
    protocol, binding = read_json(args.protocol), read_json(args.binding)
    if args.command == "generate":
        if args.out is None:
            parser.error("generate requires --out")
        result = generate(protocol, binding, args.out, args.engineering)
    else:
        if args.predictions is None:
            parser.error("verify/reveal requires --predictions")
        if args.command == "verify-reveal":
            if args.reveal is None:
                parser.error("verify-reveal requires --reveal")
            result = verify_reveal(protocol, binding, args.predictions, args.reveal, args.engineering)
        elif args.command == "verify":
            result = verify_predictions(protocol, binding, args.predictions, args.engineering)[0]
        else:
            if args.out is None:
                parser.error("reveal requires --out")
            result = reveal(protocol, binding, args.predictions, args.out, args.engineering)
    print(json.dumps({key: result[key] for key in ("status", "scope", "protocol_hash")}, indent=2))


if __name__ == "__main__":
    main()
