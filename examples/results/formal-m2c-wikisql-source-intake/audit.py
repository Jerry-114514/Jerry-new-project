"""Verify the metadata-only source index; optionally replay pinned upstream train."""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from intentlab.core import canonical, digest
from intentlab.formal_data import read_jsonl
from scripts.intake_wikisql import LIMITS, MEMBERS, build_pool


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def quality(rows):
    content, pages = defaultdict(list), defaultdict(list)
    missing = []
    for row in rows:
        table = row["table"]
        content[digest({key: table[key] for key in ("header", "types", "rows")})].append(row["candidate_id"])
        page = table.get("page_id")
        if page is None or page == "": missing.append(row["candidate_id"])
        else: pages[digest({"upstream_page_id": page})].append(row["candidate_id"])
    return {"scope": "source_only_unreviewed", "selected_candidates": len(rows),
        "distinct_table_ids": len({row["table_id"] for row in rows}), "distinct_exact_table_payloads": len(content),
        "exact_table_payload_duplicate_groups": {key: value for key, value in content.items() if len(value) > 1},
        "distinct_supplied_page_id_values": len(pages),
        "duplicate_supplied_page_id_groups": {key: value for key, value in pages.items() if len(value) > 1},
        "missing_page_id_candidates": missing, "table_metadata_fields": sorted({key for row in rows for key in row["table"]}),
        "structural_template_group_sizes": dict(sorted(Counter(row["query_template_sha256"] for row in rows).items())),
        "parent_page_or_worker_independence_audited": False, "project_cases_created": 0, "human_verified_sources": 0}


def audit(root, archive=None):
    root = Path(root)
    source = read(Path(__file__).resolve().parents[3] / "configs/wikisql-source.json")
    manifest, rows = read(root / "pool/manifest.json"), read_jsonl(root / "pool/public-index.jsonl")
    if manifest["archive"] != source["archive"] or manifest["revision"] != source["revision"] \
            or manifest["repository"] != source["repository"] or manifest["parsed_members"] != list(MEMBERS) \
            or manifest["upstream_heldout_json_parsed"] is not False or manifest["selection_limits"] != LIMITS:
        raise ValueError("Pinned source, train-only members or structural policy changed")
    if len(rows) != manifest["selected_source_candidates"] or digest(rows) != manifest["public_index_sha256"] \
            or len({row["candidate_id"] for row in rows}) != len(rows) \
            or len({row["table_id"] for row in rows}) != len(rows) \
            or manifest["distinct_table_ids"] != len(rows) \
            or len({row["query_template_sha256"] for row in rows}) != manifest["structural_query_template_groups"]:
        raise ValueError("Source index coverage, table grouping or canonical record digest changed")
    expected = {"candidate_id", "upstream_line", "upstream_record_sha256", "table_id", "table_record_sha256", "question_sha256",
                "query_template_sha256", "selection_priority", "rank", "table_rows", "table_columns"}
    if any(set(row) != expected or row["rank"] != rank or not 1 <= row["upstream_line"] <= manifest["upstream_train_records"]
           or not 1 <= row["table_rows"] <= LIMITS["rows"] or not 1 <= row["table_columns"] <= LIMITS["columns"]
           for rank, row in enumerate(rows, 1)):
        raise ValueError("Public index payload/rank/shape changed")
    if manifest["human_verified_sources"] != 0 or manifest["project_cases_created"] != 0 \
            or any(manifest[key] is not False for key in ("formal_minimum_tasks_satisfied", "license_and_release_review_complete", "annotation_ready", "execution_adapter_ready")):
        raise ValueError("Source pool was promoted to approved project tasks")
    checks = read(root / "quality.json")
    if checks["selected_candidates"] != len(rows) or checks["human_verified_sources"] != 0 or checks["project_cases_created"] != 0:
        raise ValueError("Quality report population or approval scope changed")
    if archive is not None:
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "replay"
            reproduced = build_pool(archive, source, out, manifest["requested_candidates"], manifest["selection_seed"])
            if canonical(reproduced) != canonical(manifest) or (out / "public-index.jsonl").read_bytes() != (root / "pool/public-index.jsonl").read_bytes():
                raise ValueError("Pinned upstream train replay differs from metadata/index")
            if canonical(quality(read_jsonl(out / "coordinator-pool.jsonl"))) != canonical(checks):
                raise ValueError("Exact-content/page-ID/template quality audit differs from raw-source replay")
    return {"scope": "upstream_train_source_intake_only", "selected_source_candidates": len(rows),
        "distinct_table_ids": len(rows), "structural_query_template_groups": manifest["structural_query_template_groups"],
        "distinct_exact_table_payloads": checks["distinct_exact_table_payloads"],
        "distinct_supplied_page_id_values": checks["distinct_supplied_page_id_values"],
        "missing_page_ids": len(checks["missing_page_id_candidates"]), "duplicate_page_id_groups": len(checks["duplicate_supplied_page_id_groups"]),
        "full_upstream_train_replayed": archive is not None, "project_cases_created": 0, "human_verified_sources": 0,
        "formal_minimum_tasks_satisfied": False,
        "warning": "Source metadata only unless --archive is supplied. Six hundred source candidates are not six hundred independently verified project tasks; no annotation, execution adaptation, release review or sealed project test/OOD completion."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    report = audit(root, args.archive)
    name = "source-replay-verification.json" if args.archive else "verification.json"
    (root / name).write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    sums = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and p.name != "checksums.json" and "__pycache__" not in p.parts}
    (root / "checksums.json").write_text(json.dumps(sums, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
