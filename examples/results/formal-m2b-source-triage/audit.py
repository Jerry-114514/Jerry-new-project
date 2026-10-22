"""Reproduce the public source triage and verify that every human field is blank."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from intentlab.formal_data import read_jsonl
from intentlab.source_triage import validate_semantic_review, write_triage


def audit(root):
    root = Path(root)
    batches = {"inputs/new-cases.jsonl": read_jsonl(root / "inputs/new-cases.jsonl"),
               "inputs/old-cases.jsonl": read_jsonl(root / "inputs/old-cases.jsonl")}
    with tempfile.TemporaryDirectory() as d:
        out = Path(d) / "replayed"
        summary = write_triage(batches, out)
        archived = root / "triage"
        if {p.name for p in out.iterdir()} != {p.name for p in archived.iterdir()}:
            raise ValueError("Triage artifact coverage changed")
        for p in out.iterdir():
            if p.read_bytes() != (archived / p.name).read_bytes():
                raise ValueError("Triage/blank review differs from inputs: " + p.name)
    cases = read_jsonl(root / "triage/coordinator-cases.jsonl")
    review = json.loads((root / "triage/semantic-review-template.json").read_text(encoding="utf-8"))
    if review["human_verified"] is not False or any(row["decision"] for row in review["pair_reviews"]):
        raise ValueError("Blank templates were promoted to human approval")
    try:
        validate_semantic_review(cases, review)
    except ValueError:
        pass
    else:
        raise ValueError("Blank source review passed formal semantic validation")
    return {"scope": "development", "views": summary["unique_case_ids"], "contracts": summary["unique_public_contracts"],
        "flagged_cross_split_pairs": summary["flagged_cross_split_pairs"], "blank_source_group_reviews": len(review["source_groups"]),
        "blank_pair_reviews": len(review["pair_reviews"]), "human_reviews_completed": 0,
        "semantic_dedup_review_complete": False, "formal_readiness_evidence": False,
        "warning": "Two public batches only. Shared operation is risk triage, not duplicate proof or independently verified sample size. Does not cover all legacy fixtures or external/pretraining sources."}


if __name__ == "__main__":
    root = Path(__file__).resolve().parent
    report = audit(root)
    (root / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    sums = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and p.name != "checksums.json" and "__pycache__" not in p.parts}
    (root / "checksums.json").write_text(json.dumps(sums, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
