"""Exercise two real model identities under one ledger; not an efficacy test."""

import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from intentlab.formal_data import formal_prompt, read_jsonl, validate_cases
from intentlab.model_pool import LocalModelPool
from intentlab.neural import dependencies, local_model_fingerprint
from intentlab.report import save_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actor", type=Path, required=True)
    parser.add_argument("--analyzer", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--device", choices=["cpu", "cuda"], default="cpu")
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Choose a fresh output path")
    cases = read_jsonl(args.cases)
    validate_cases(cases)
    identities = {role: {"path": str(path.resolve()), "artifact_fingerprint": local_model_fingerprint(path)}
                  for role, path in (("actor", args.actor), ("analyzer", args.analyzer))}
    pool = LocalModelPool({"actor": args.actor, "analyzer": args.analyzer}, args.device,
                          max_new_tokens=256, token_budget=8192)
    torch, _ = dependencies()
    if args.device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    responses = []
    try:
        for role, prompt in (("actor", 'Return exactly the JSON object {"actions": []}.'),
                             ("analyzer", formal_prompt(cases[0]["public"])),
                             ("actor", 'Return exactly the JSON object {"actions": []}.')):
            responses.append({"role": role, **pool.role(role).complete(prompt)})
        snapshot = pool.snapshot()
        assert snapshot["shared_token_ledger"]["charged_tokens"] <= 8192
        assert snapshot["shared_token_ledger"]["calls"] == 3
        report = {"kind": "real_separate_role_interface_audit", "status": "completed",
            "identities": identities, "snapshot": snapshot, "responses": responses,
            "wall_seconds": time.perf_counter() - started,
            "warning": "Three engineering calls with an existing development adapter; not formal closed-loop quality or fairness evidence."}
        if args.device == "cuda":
            report["peak_allocated_bytes"] = torch.cuda.max_memory_allocated()
            report["peak_reserved_bytes"] = torch.cuda.max_memory_reserved()
        save_json(args.out, report)
        print(json.dumps({"status": report["status"], "wall_seconds": report["wall_seconds"],
                          "charged_tokens": snapshot["shared_token_ledger"]["charged_tokens"],
                          "loads": len(snapshot["model_loads"])}, indent=2))
    finally:
        pool.close()


if __name__ == "__main__":
    main()
