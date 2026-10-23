"""Reviewed diagnostic data, separate from synthetic fixture supervision.

Annotation identity is an auditable declaration, not proof of human identity.
Never create reviews or adjudications automatically in this module.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import unicodedata

from .core import canonical, digest
from .report import save_json


SPLITS = ("train", "validation", "test", "ood")
STATUSES = ("satisfied", "violated", "unknown")


def read_jsonl(path, allow_empty=False):
    rows = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                rows.append(json.loads(line))
            except ValueError as exc:
                raise ValueError(f"Invalid JSON in {path}:{number}") from exc
    if (not rows and not allow_empty) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("Expected nonempty JSONL objects")
    return rows


def write_jsonl(path, rows):
    with Path(path).open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(canonical(row) + "\n")


def require_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Nonempty {label} required")


def normalized_request(text):
    # Candidate grouping only: also require manual semantic/near-duplicate review.
    text = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"\s+", " ", text).strip()


def validate_cases(cases):
    """Reject cross-split derivations and unknown payload keys before export."""
    seen, groups, requests, families = set(), {}, {}, defaultdict(set)
    counts, tasks = Counter(), defaultdict(set)
    for row in cases:
        expected = {"case_id", "source_task_id", "split", "family", "template_id", "source", "public"}
        if set(row) != expected:
            raise ValueError("Case must contain only the documented metadata and public payload")
        for key in ("case_id", "source_task_id", "family", "template_id"):
            require_text(row[key], key)
        if row["case_id"] in seen or row["split"] not in SPLITS:
            raise ValueError("Duplicate case ID or unsupported split")
        seen.add(row["case_id"])
        split = row["split"]
        source = row["source"]
        if not isinstance(source, dict) or set(source) != {"origin", "reference", "license", "trajectory"}:
            raise ValueError("Source needs origin, reference, license and trajectory")
        if source["origin"] not in {"human_authored", "model_generated", "adapted_public", "program_generated"}:
            raise ValueError("Unknown task origin")
        if source["trajectory"] not in {"natural", "injected", "none"}:
            raise ValueError("Unknown trajectory provenance")
        for key in ("reference", "license"):
            require_text(source[key], key)
        public = row["public"]
        allowed = {"request", "inputs", "requirements", "observation"}
        if isinstance(public, dict) and "execution_spec" in public:
            allowed.add("execution_spec")
        if not isinstance(public, dict) or set(public) != allowed:
            raise ValueError("Public payload needs request, inputs, requirements and observation only")
        if not isinstance(public["inputs"], dict):
            raise ValueError("Original public inputs must be an object")
        require_text(public["request"], "request")
        requirements = public["requirements"]
        if not isinstance(requirements, list) or not requirements:
            raise ValueError("Nonempty requirements required")
        ids = set()
        for req in requirements:
            if not isinstance(req, dict) or set(req) != {"id", "quote", "hard"}:
                raise ValueError("Requirement must contain id, quote and hard only")
            require_text(req["id"], "requirement ID")
            require_text(req["quote"], "requirement quote")
            if req["id"] in ids or type(req["hard"]) is not bool or req["quote"] not in public["request"]:
                raise ValueError("Duplicate ID, invalid hard flag or unsupported source quote")
            ids.add(req["id"])
        if "execution_spec" in public:
            from .contracts import validate_spec
            validate_spec(public["execution_spec"], requirements)
        observation = public["observation"]
        if not isinstance(observation, dict) or set(observation) != {"files", "events"}:
            raise ValueError("Observation needs files and events")
        if not isinstance(observation["files"], dict):
            raise ValueError("Observed files must be an object")
        events = observation["events"]
        if events is not None and (not isinstance(events, list) or any(
                not isinstance(event, dict) or type(event.get("index")) is not int
                or event["index"] != i for i, event in enumerate(events))):
            raise ValueError("Observed events must have consecutive authoritative indices")
        # Different evidence views of a task must stay together. Template grouping
        # is strict here: an author cannot split one template across collections.
        for kind, value in (("task", row["source_task_id"]), ("template", row["template_id"])):
            key = (kind, value)
            if key in groups and groups[key] != split:
                raise ValueError(f"Cross-split {kind} leakage: {value}")
            groups[key] = split
        request_key = normalized_request(public["request"])
        if request_key in requests and requests[request_key] != split:
            raise ValueError("Normalized request duplicated across splits")
        requests[request_key] = split
        families[row["family"]].add(split)
        counts[split] += 1
        tasks[split].add(row["source_task_id"])
    if any("ood" in values and len(values) > 1 for values in families.values()):
        raise ValueError("OOD operation family overlaps another split")
    return {"cases": dict(counts), "source_task_groups": {k: len(v) for k, v in tasks.items()},
            "manual_review_required": "Semantic near-duplicates, provenance and requirement completeness"}


def output_schema(requirements):
    return {"type": "object", "additionalProperties": False, "required": ["findings"], "properties": {
        "findings": {"type": "array", "minItems": len(requirements), "maxItems": len(requirements),
            "items": {"type": "object", "additionalProperties": False,
                "required": ["id", "status", "evidence"], "properties": {
                    "id": {"enum": [r["id"] for r in requirements]},
                    "status": {"enum": list(STATUSES)},
                    "evidence": {"type": "array", "uniqueItems": True, "items": {"type": "string"}}}}}}}


def evidence_catalog(public):
    """References support file snapshots, the request and visible events."""
    catalog = {"request": public["request"]}
    catalog["snapshot_paths"] = sorted(public["observation"]["files"])
    catalog.update({"input:" + path: value for path, value in public["inputs"].items()})
    catalog.update({"file:" + path: value for path, value in public["observation"]["files"].items()})
    catalog.update({"event:" + str(event["index"]): event
                    for event in public["observation"]["events"] or []})
    return catalog


def formal_prompt(public):
    return ("Inspect only the public requirements and observations. Return JSON matching the schema. "
            "Include each requirement ID exactly once. Unknown history does not prove compliance. "
            "A current snapshot can prove a violation even when history is hidden. "
            "Cite only keys in evidence_catalog; empty evidence is allowed for unknown.\n"
            + canonical({"public": public, "evidence_catalog": evidence_catalog(public),
                         "output_schema": output_schema(public["requirements"])}) + "\nJSON:\n")


def validate_findings(findings, public):
    ids = {r["id"] for r in public["requirements"]}
    catalog = evidence_catalog(public)
    if not isinstance(findings, list) or len(findings) != len(ids):
        raise ValueError("Exactly one finding per requirement required")
    result = {}
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != {"id", "status", "evidence"}:
            raise ValueError("Finding needs id, status and evidence only")
        rid = finding["id"]
        evidence = finding["evidence"]
        if not isinstance(rid, str) or rid not in ids or rid in result or finding["status"] not in STATUSES:
            raise ValueError("Invalid requirement ID or status")
        if not isinstance(evidence, list) or any(not isinstance(ref, str) or ref not in catalog for ref in evidence):
            raise ValueError("Evidence must reference visible catalog entries")
        if len(set(evidence)) != len(evidence) or (finding["status"] != "unknown" and not evidence):
            raise ValueError("Known judgments require evidence; references must be unique")
        result[rid] = finding
    return result


def annotation_packet(cases, out):
    validate_cases(cases)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    # Both reviewers receive the same unlabeled records independently.
    write_jsonl(out / "cases.jsonl", [{"case_id": row["case_id"], "public": row["public"]} for row in cases])
    write_jsonl(out / "review-template.jsonl", [{"case_id": row["case_id"], "reviewer": "",
        "human_verified": False, "findings": [{"id": req["id"], "status": "", "evidence": []}
            for req in row["public"]["requirements"]]} for row in cases])
    (out / "README.md").write_text(
        "# Independent annotation packet\n\n"
        "These are unreviewed development candidates, not a released benchmark.\n"
        "Give cases.jsonl and a separate copy of review-template.jsonl to each reviewer.\n"
        "Reviewers must not see each other's labels before submitting. Fill reviewer with a stable identity,\n"
        "set human_verified=true only after actual human review, and judge every listed requirement.\n"
        "Allowed status: satisfied / violated / unknown. Cite request, input:<path>, file:<path>, or visible event:<index>.\n"
        "A changed snapshot can prove violation without history; a restored snapshot cannot prove no historical writes.\n"
        "Known judgments need supporting evidence. Do not infer missing history.\n"
        "Combine the two completed review files, then run the conflicts command. A different person arbitrates conflicts.\n"
        "Do not invent reviewer identities or submit automated labels as human verification.\n",
        encoding="utf-8")


def index_reviews(cases, reviews):
    validate_cases(cases)
    by_case = {row["case_id"]: row for row in cases}
    indexed = defaultdict(dict)
    for review in reviews:
        if set(review) != {"case_id", "reviewer", "human_verified", "findings"}:
            raise ValueError("Unsupported review fields")
        require_text(review["reviewer"], "reviewer identity")
        cid, reviewer = review["case_id"], review["reviewer"]
        if cid not in by_case or review["human_verified"] is not True or reviewer in indexed[cid]:
            raise ValueError("Unknown case, unverified review or duplicate reviewer")
        indexed[cid][reviewer] = validate_findings(review["findings"], by_case[cid]["public"])
    for cid in by_case:
        if len(indexed[cid]) != 2:
            raise ValueError(f"Two distinct human-verified reviews required for {cid}")
    return by_case, indexed


def adjudication_packet(cases, reviews, out):
    by_case, indexed = index_reviews(cases, reviews)
    queue, templates = [], []
    for cid, case in by_case.items():
        first, second = indexed[cid].values()
        if any(first[rid]["status"] != second[rid]["status"] or
               set(first[rid]["evidence"]) != set(second[rid]["evidence"]) for rid in first):
            queue.append({"case_id": cid, "public": case["public"], "reviews": indexed[cid]})
            templates.append({"case_id": cid, "adjudicator": "", "human_verified": False, "reason": "",
                "findings": [{"id": req["id"], "status": "", "evidence": []}
                             for req in case["public"]["requirements"]]})
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    write_jsonl(out / "disagreements.jsonl", queue)
    write_jsonl(out / "adjudication-template.jsonl", templates)
    return {"unresolved_cases": len(queue), "total_cases": len(cases)}


def resolve_reviews(cases, reviews, adjudications=()):
    by_case, indexed = index_reviews(cases, reviews)
    adjudicated = {}
    for row in adjudications:
        if set(row) != {"case_id", "adjudicator", "human_verified", "reason", "findings"}:
            raise ValueError("Unsupported adjudication fields")
        for key in ("adjudicator", "reason"):
            require_text(row[key], key)
        cid = row["case_id"]
        if cid not in by_case or row["human_verified"] is not True or cid in adjudicated:
            raise ValueError("Unknown, duplicate or unverified adjudication")
        if row["adjudicator"] in indexed[cid]:
            raise ValueError("Adjudicator must be independent of the two reviewers")
        adjudicated[cid] = validate_findings(row["findings"], by_case[cid]["public"])
    selected, conflicts, agreements = {}, [], 0
    first_counts, second_counts = Counter(), Counter()
    total = 0
    for cid, case in by_case.items():
        first, second = [indexed[cid][name] for name in sorted(indexed[cid])]
        disagree = False
        for rid in first:
            a, b = first[rid]["status"], second[rid]["status"]
            first_counts[a] += 1
            second_counts[b] += 1
            total += 1
            agreements += a == b
            # Evidence disagreements also require explicit reconciliation.
            disagree |= a != b or set(first[rid]["evidence"]) != set(second[rid]["evidence"])
        if disagree:
            conflicts.append(cid)
            if cid not in adjudicated:
                raise ValueError(f"Unresolved status/evidence disagreement for {cid}")
            selected[cid] = adjudicated[cid]
        else:
            if cid in adjudicated:
                raise ValueError("Unnecessary adjudication would override agreed labels")
            selected[cid] = first
    observed = agreements / total
    expected = sum(first_counts[s] * second_counts[s] for s in STATUSES) / total ** 2
    reviewer_pairs = {tuple(sorted(values)) for values in indexed.values()}
    # Pooled agreement is descriptive; pooled kappa is inappropriate if pairs change.
    kappa = (observed - expected) / (1 - expected) if expected < 1 and len(reviewer_pairs) == 1 else None
    return selected, {"status_agreement": observed, "status_items": total,
        "cohen_kappa": kappa, "reviewer_pairs": len(reviewer_pairs),
        "adjudicated_cases": conflicts, "human_identity": "self-declared; inspect external audit records",
        "evidence_semantics": "reviewer-verified; reference existence is checked programmatically"}


def export_reviewed(cases, reviews, adjudications, out):
    selected, agreement = resolve_reviews(cases, reviews, adjudications)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    groups = {name: [] for name in SPLITS}
    for row in cases:
        groups[row["split"]].append({"task_id": row["source_task_id"], "case_id": row["case_id"],
            "family": row["family"], "template_id": row["template_id"], "source": row["source"],
            "prompt": formal_prompt(row["public"]), "completion": canonical({"findings": [
                selected[row["case_id"]][req["id"]] for req in row["public"]["requirements"]]})})
    for split, rows in groups.items():
        if rows and split in {"train", "validation"}:
            write_jsonl(out / f"{split}.jsonl", rows)
        elif rows:
            # Do not create test.jsonl alongside training data. Inference inputs
            # and offline gold live separately, outside the training loader.
            sealed = out / "heldout" / split
            sealed.mkdir(parents=True)
            write_jsonl(sealed / "cases.jsonl", [case for case in cases if case["split"] == split])
            write_jsonl(sealed / "gold.jsonl", [{"case_id": row["case_id"],
                "findings": json.loads(row["completion"])["findings"]} for row in rows])
    save_json(out / "manifest.json", {"kind": "human_reviewed_diagnostics", "schema_version": 1,
        "cases_hash": digest(cases), "reviews_hash": digest(reviews), "adjudications_hash": digest(adjudications),
        "audit": validate_cases(cases), "agreement": agreement,
        "files_sha256": {path.relative_to(out).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                         for path in sorted(out.rglob("*.jsonl"))},
        "protocol_frozen": False, "warning": "Export is not preregistration or proof of independent provenance."})
    return {key: len(value) for key, value in groups.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["audit", "packet", "conflicts", "export"])
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--reviews", type=Path)
    parser.add_argument("--adjudications", type=Path)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    cases = read_jsonl(args.cases)
    if args.command == "audit":
        result = validate_cases(cases)
    elif args.command == "packet":
        if args.out is None:
            parser.error("--out is required")
        annotation_packet(cases, args.out)
        result = {"packet": str(args.out), "human_verified": False}
    elif args.command == "conflicts":
        if args.reviews is None or args.out is None:
            parser.error("--reviews and --out are required")
        result = adjudication_packet(cases, read_jsonl(args.reviews), args.out)
    else:
        if args.reviews is None or args.out is None:
            parser.error("--reviews and --out are required")
        result = export_reviewed(cases, read_jsonl(args.reviews),
            read_jsonl(args.adjudications) if args.adjudications else [], args.out)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
