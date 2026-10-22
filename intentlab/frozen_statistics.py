"""Verified M5/M6/M7 statistics stage; not full scientific M8 acceptance."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .core import canonical, digest
from . import frozen_ablation
from .formal_data import read_jsonl
from .protocol import read_json
from .report import save_json
from .research_statistics import analyze_records, validate_analysis_plan
from .diagnostic_protocol import seal_files


def inputs(directory):
    directory = Path(directory)
    return (read_json(directory / "scores.json"),
        {f"{condition}-seed-{seed}": read_jsonl(directory / f"{condition}-seed-{seed}-loss.jsonl")
         for condition in ("D", "E") for seed in (0, 1, 2)})


def preflight(protocol, binding, predictions, diagnostic_reveal, execution_interactions, execution_reveal,
              ablation_interactions, ablation_reveal, engineering=False):
    validate_analysis_plan(protocol["spec"]["statistics"], formal=protocol["scope"] == "formal")
    m7 = frozen_ablation.verify_scoring(protocol, binding, predictions, diagnostic_reveal,
        execution_interactions, execution_reveal, ablation_interactions, ablation_reveal, engineering)
    return {"M5": read_json(Path(diagnostic_reveal) / "manifest.json")["receipt_hash"],
            "M6": read_json(Path(execution_reveal) / "manifest.json")["receipt_hash"], "M7": m7["receipt_hash"]}


def compute(protocol, diagnostic_reveal, execution_reveal, ablation_reveal):
    scores, losses = inputs(diagnostic_reveal)
    report = analyze_records(protocol, scores, losses, read_jsonl(Path(execution_reveal) / "runs.jsonl"),
                             read_jsonl(Path(ablation_reveal) / "runs.jsonl"), include_auxiliary=True)
    report["remaining"].remove("verified statistics entry/receipt")
    report["analysis_stage_receipt"] = "manifest.json"
    return report


def run(protocol, binding, predictions, diagnostic_reveal, execution_interactions, execution_reveal,
        ablation_interactions, ablation_reveal, out, engineering=False):
    common = (protocol, binding, predictions, diagnostic_reveal, execution_interactions, execution_reveal,
              ablation_interactions, ablation_reveal)
    upstream = preflight(*common, engineering)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    manifest = {"kind": "frozen_statistics_analysis", "schema_version": 1, "scope": protocol["scope"],
        "status": "running", "protocol_hash": protocol["lock_hash"], "model_binding_hash": binding["binding_hash"],
        "upstream_receipts": upstream, "statistics_settings_hash": digest(protocol["spec"]["statistics"]),
        "created_utc": datetime.now(timezone.utc).isoformat(), "gold_or_references_reopened": False,
        "m8_complete": False,
        "warning": "Completed statistics-stage integrity is not full M8 acceptance, scientific assumption validation or durable model backup. Identical frozen analyses may be reproduced at fresh output directories."}
    save_json(out / "manifest.json", manifest)
    try:
        report = compute(protocol, diagnostic_reveal, execution_reveal, ablation_reveal)
        save_json(out / "report.json", report)
        if preflight(*common, engineering) != upstream:
            raise ValueError("Upstream experiment receipts changed during statistics")
        manifest.update(status="completed", files_sha256=seal_files(out))
        manifest["receipt_hash"] = digest(manifest)
    except Exception as exc:
        manifest.update(status="failed", error_type=type(exc).__name__, error=str(exc))
        save_json(out / "manifest.json", manifest)
        raise
    save_json(out / "manifest.json", manifest)
    return manifest


def verify(protocol, binding, predictions, diagnostic_reveal, execution_interactions, execution_reveal,
           ablation_interactions, ablation_reveal, directory, engineering=False):
    upstream = preflight(protocol, binding, predictions, diagnostic_reveal, execution_interactions, execution_reveal,
                         ablation_interactions, ablation_reveal, engineering)
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json")
    if manifest.get("kind") != "frozen_statistics_analysis" or manifest.get("schema_version") != 1 \
            or manifest.get("status") != "completed" or manifest.get("scope") != protocol["scope"] \
            or manifest.get("protocol_hash") != protocol["lock_hash"] or manifest.get("model_binding_hash") != binding["binding_hash"] \
            or manifest.get("upstream_receipts") != upstream or manifest.get("statistics_settings_hash") != digest(protocol["spec"]["statistics"]) \
            or manifest.get("gold_or_references_reopened") is not False or manifest.get("m8_complete") is not False \
            or manifest.get("receipt_hash") != digest({k: v for k, v in manifest.items() if k != "receipt_hash"}) \
            or manifest.get("files_sha256") != seal_files(directory) or "report.json" not in manifest["files_sha256"]:
        raise ValueError("Missing, changed or incomplete frozen statistics receipt")
    if canonical(read_json(directory / "report.json")) != canonical(compute(protocol, diagnostic_reveal, execution_reveal, ablation_reveal)):
        raise ValueError("Statistics report differs from registered arithmetic recomputation")
    if preflight(protocol, binding, predictions, diagnostic_reveal, execution_interactions, execution_reveal,
                 ablation_interactions, ablation_reveal, engineering) != upstream:
        raise ValueError("Upstream receipts changed during statistics verification")
    return {"status": "completed", "scope": protocol["scope"], "protocol_hash": protocol["lock_hash"],
            "receipt_hash": manifest["receipt_hash"], "gold_or_references_reopened": False, "m8_complete": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "verify"])
    for name in ("protocol", "binding", "predictions", "diagnostic-reveal", "execution-interactions",
                 "execution-reveal", "ablation-interactions", "ablation-reveal"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--statistics", type=Path)
    parser.add_argument("--engineering", action="store_true")
    args = parser.parse_args()
    common = (read_json(args.protocol), read_json(args.binding), args.predictions, args.diagnostic_reveal,
              args.execution_interactions, args.execution_reveal, args.ablation_interactions, args.ablation_reveal)
    if args.command == "run":
        if args.out is None:
            parser.error("run requires --out")
        result = run(*common, args.out, args.engineering)
    else:
        if args.statistics is None:
            parser.error("verify requires --statistics")
        result = verify(*common, args.statistics, args.engineering)
    print(json.dumps({key: result[key] for key in ("status", "scope", "protocol_hash", "m8_complete")}, indent=2))


if __name__ == "__main__":
    main()
