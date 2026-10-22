import json
from collections import defaultdict
from pathlib import Path


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def summarize(records):
    grouped = defaultdict(list)
    for record in records:
        grouped[record["policy"]].append(record)
    result = {}
    for policy, rows in grouped.items():
        n = len(rows)
        result[policy] = {"runs": n,
                          "compliant_success_rate": sum(r["metrics"]["compliant_success"] for r in rows) / n,
                          "task_completion_rate": sum(r["metrics"]["task_complete"] for r in rows) / n,
                          "hard_violation_run_rate": sum(r["metrics"]["hard_violations"] > 0 for r in rows) / n,
                          "errors": sum(r["status"] == "error" for r in rows),
                          "actor_calls": sum(r["cost"]["actor_calls"] for r in rows),
                          "checks": sum(r["cost"]["checks"] for r in rows),
                          "rejected_candidates": sum(r["cost"]["rejected"] for r in rows),
                          "verification_calls": sum(r["cost"]["verifications"] for r in rows)}
        measured = [r["elapsed_seconds"] for r in rows if "elapsed_seconds" in r]
        result[policy]["timed_runs"] = len(measured)
        result[policy]["mean_elapsed_seconds"] = sum(measured) / len(measured) if measured else None
        ledgers = [r.get("shared_token_ledger") or r.get("model_pool", {}).get("shared_token_ledger") for r in rows]
        ledgers = [ledger for ledger in ledgers if ledger is not None]
        if ledgers:
            result[policy]["budgeted_runs"] = len(ledgers)
            result[policy]["charged_model_tokens"] = sum(ledger["charged_tokens"] for ledger in ledgers)
            result[policy]["known_prompt_tokens"] = sum(ledger["known_prompt_tokens"] for ledger in ledgers)
            result[policy]["known_completion_tokens"] = sum(ledger["known_completion_tokens"] for ledger in ledgers)
            result[policy]["failed_generation_reservations"] = sum(ledger["failed_reservations"] for ledger in ledgers)
            result[policy]["denied_model_calls"] = sum(ledger["denied_calls"] for ledger in ledgers)
            result[policy]["token_accounting"] = "Charged totals include conservative reservations on failed generation"
    return result


def save_experiment(records, directory, manifest):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "runs.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary = summarize(records)
    save_json(directory / "summary.json", summary)
    save_json(directory / "manifest.json", manifest)
    explanation = {"scripted": "This is an engineered scripted-actor demonstration, not evidence of LLM improvement.",
                   "local_model": "Real local causal-LM inference. Inspect JSON errors, token usage and dataset limitations; a smoke run is not efficacy evidence.",
                   "http": "HTTP actor experiment; inspect provider, budgets and dataset limitations before interpreting."}
    lines = ["# Local functional experiment", "", explanation[manifest["actor"]], "",
             "| Policy | Runs | Compliant success | Completion | Hard-violation runs | Checks | Rejected |", "| --- | ---: | ---: | ---: | ---: | ---: | ---: |"]
    for policy, row in summary.items():
        lines.append(f"| {policy} | {row['runs']} | {row['compliant_success_rate']:.3f} | {row['task_completion_rate']:.3f} | {row['hard_violation_run_rate']:.3f} | {row['checks']} | {row['rejected_candidates']} |")
    lines += ["", "Unknown evidence is not a pass. Historical input writes remain violations even after restoration.",
              "Candidate effects occur only in cloned virtual state; a rejected candidate never commits.",
              "Call/action counters alone do not establish compute fairness; local model_usage records tokens separately."]
    (directory / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary
