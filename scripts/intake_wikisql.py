"""Pinned upstream TRAIN-only source pool, not executable or human-reviewed cases.

Reads two allowlisted tar members without extracting paths or running SQL/code.
Raw questions/tables/SQL stay in the coordinator pool; the public index contains
identifiers, sizes and hashes only. No project test/OOD material is produced.
"""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.core import canonical, digest
from intentlab.formal_data import normalized_request, write_jsonl

MEMBERS = ("data/train.tables.jsonl", "data/train.jsonl")
LIMITS = {"rows": 8, "columns": 6, "table_payload_characters": 1800, "question_characters": 300, "conditions": 3}


def archive_identity(path):
    path = Path(path)
    size = path.stat().st_size
    sha, blob = hashlib.sha256(), hashlib.sha1(f"blob {size}\0".encode())
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            sha.update(chunk); blob.update(chunk)
    return {"bytes": size, "sha256": sha.hexdigest(), "git_blob_sha1": blob.hexdigest()}


def objects(archive, name, hashes):
    members = [member for member in archive.getmembers() if member.name == name]
    if len(members) != 1 or not members[0].isreg() or members[0].size > 256 * 1024**2:
        raise ValueError("Exactly one bounded regular upstream train member required: " + name)
    sha = hashlib.sha256()
    with archive.extractfile(members[0]) as stream:
        number = 0
        while raw := stream.readline(8 * 1024**2 + 1):
            number += 1
            if len(raw) > 8 * 1024**2:
                raise ValueError("Oversized upstream JSONL record")
            sha.update(raw)
            if not raw.strip():
                raise ValueError("Blank upstream JSONL record")
            row = json.loads(raw.decode("utf-8"), parse_constant=lambda value: (_ for _ in ()).throw(ValueError("Nonfinite JSON constant")))
            if not isinstance(row, dict):
                raise ValueError("Upstream JSONL object required")
            yield number, row, hashlib.sha256(raw.rstrip(b"\r\n")).hexdigest()
    hashes[name] = sha.hexdigest()


def table_reason(table):
    headers, types, rows = (table.get(key) for key in ("header", "types", "rows"))
    if not isinstance(headers, list) or not 1 <= len(headers) <= LIMITS["columns"] \
            or any(not isinstance(value, str) or not value for value in headers) \
            or not isinstance(types, list) or len(types) != len(headers) or any(value not in {"text", "real"} for value in types) \
            or not isinstance(rows, list) or not 1 <= len(rows) <= LIMITS["rows"]:
        return "table_shape_or_type"
    if any(not isinstance(row, list) or len(row) != len(headers) or any(
            value is not None and type(value) not in {str, int, float, bool} or type(value) is float and not math.isfinite(value)
            for value in row) for row in rows):
        return "invalid_table_cell"
    if len(canonical({"header": headers, "rows": rows})) > LIMITS["table_payload_characters"]:
        return "table_payload_length"
    return None


def query_template(row, table):
    sql = row.get("sql")
    if not isinstance(sql, dict) or set(sql) != {"sel", "agg", "conds"}:
        return None
    columns = len(table["header"])
    if type(sql["sel"]) is not int or not 0 <= sql["sel"] < columns \
            or type(sql["agg"]) is not int or not 0 <= sql["agg"] <= 5 \
            or not isinstance(sql["conds"], list) or len(sql["conds"]) > LIMITS["conditions"]:
        return None
    shape = []
    for condition in sql["conds"]:
        if not isinstance(condition, list) or len(condition) != 3:
            return None
        column, operator, value = condition
        if type(column) is not int or not 0 <= column < columns or type(operator) is not int or not 0 <= operator <= 2 \
                or type(value) not in {str, int, float} or type(value) is float and not math.isfinite(value):
            return None
        shape.append([table["types"][column], operator])
    return digest({"aggregation": sql["agg"], "selected_type": table["types"][sql["sel"]], "conditions": sorted(shape)})


def build_pool(archive_path, source, out, limit=600, seed=20261023):
    out = Path(out)
    if out.exists():
        raise FileExistsError("Source pool output must be new")
    if type(limit) is not int or limit < 1 or type(seed) is not int:
        raise ValueError("Positive candidate limit and integer selection seed required")
    if source.get("repository") != "salesforce/WikiSQL" or source.get("usage") != "train_development_sources_only" \
            or not isinstance(source.get("revision"), str) or len(source["revision"]) != 40:
        raise ValueError("Pinned upstream source specification required")
    identity = archive_identity(archive_path)
    if identity != source["archive"]:
        raise ValueError("Upstream archive size/Git/SHA256 identity mismatch")
    tables, reasons, member_hashes = {}, Counter(), {}
    with tarfile.open(archive_path, "r:bz2") as archive:
        for number, table, raw_hash in objects(archive, MEMBERS[0], member_hashes):
            tid = table.get("id")
            if not isinstance(tid, str) or not tid or tid in tables:
                raise ValueError("Missing or duplicate upstream table ID")
            tables[tid] = (table, raw_hash, table_reason(table))
        candidates, total = [], 0
        for number, row, raw_hash in objects(archive, MEMBERS[1], member_hashes):
            total += 1
            tid, question = row.get("table_id"), row.get("question")
            if not isinstance(tid, str) or tid not in tables:
                reasons["missing_table"] += 1; continue
            table, table_hash, reason = tables[tid]
            if reason:
                reasons[reason] += 1; continue
            if not isinstance(question, str) or not question.strip() or len(question) > LIMITS["question_characters"]:
                reasons["question_shape_or_length"] += 1; continue
            template = query_template(row, table)
            if template is None:
                reasons["query_shape_or_operator"] += 1; continue
            candidates.append({"candidate_id": "wikisql-train-line-" + str(number), "upstream_line": number,
                "upstream_record_sha256": raw_hash, "table_id": tid, "table_record_sha256": table_hash,
                "question_sha256": digest(question), "question": question, "table": table, "upstream_sql": row["sql"],
                "query_template_sha256": template, "selection_priority": digest([seed, tid, normalized_request(question), raw_hash])})
    selected, used_tables, used_questions = [], set(), set()
    for row in sorted(candidates, key=lambda row: (row["selection_priority"], row["upstream_line"])):
        question = normalized_request(row["question"])
        if row["table_id"] in used_tables or question in used_questions:
            continue
        used_tables.add(row["table_id"]); used_questions.add(question)
        selected.append(row)
        if len(selected) == limit:
            break
    if not selected:
        raise ValueError("No structurally eligible source candidates")
    pool, index = [], []
    for rank, row in enumerate(selected, 1):
        public = {key: row[key] for key in ("candidate_id", "upstream_line", "upstream_record_sha256", "table_id",
            "table_record_sha256", "question_sha256", "query_template_sha256", "selection_priority")}
        public.update(rank=rank, table_rows=len(row["table"]["rows"]), table_columns=len(row["table"]["header"]))
        index.append(public)
        pool.append({**row, "upstream_revision": source["revision"], "upstream_split": "train", "project_split": None,
            "allowed_project_roles": ["train", "validation"], "coordinator_only": True, "human_reviewed": False,
            "annotation_ready": False, "execution_adapter_ready": False})
    manifest = {"kind": "external_source_candidates_not_project_cases", "schema_version": 1,
        "repository": source["repository"], "revision": source["revision"], "archive": identity,
        "parsed_members": list(MEMBERS), "member_sha256": member_hashes, "upstream_heldout_json_parsed": False,
        "upstream_train_records": total, "upstream_train_tables": len(tables), "structurally_eligible_records": len(candidates),
        "structural_exclusion_counts": dict(sorted(reasons.items())), "selection_seed": seed, "selection_limits": LIMITS,
        "requested_candidates": limit, "selected_source_candidates": len(selected), "distinct_table_ids": len(used_tables),
        "structural_query_template_groups": len({row["query_template_sha256"] for row in selected}),
        "human_verified_sources": 0, "project_cases_created": 0, "formal_minimum_tasks_satisfied": False,
        "license_and_release_review_complete": False, "annotation_ready": False, "execution_adapter_ready": False,
        "public_index_sha256": digest(index), "coordinator_pool_hash": digest(pool),
        "warning": "Source intake only. Table IDs are not proof of distinct pages/workers or independent tasks. Structural templates repeat. No model score selects candidates. Upstream SQL is coordinator reference material, not public model input or project human labels. Never treat this public upstream pool as a new sealed test/OOD benchmark."}
    out.mkdir(parents=True, exist_ok=False)
    write_jsonl(out / "public-index.jsonl", index)
    write_jsonl(out / "coordinator-pool.jsonl", pool)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--source-spec", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=600)
    parser.add_argument("--seed", type=int, default=20261023)
    args = parser.parse_args()
    result = build_pool(args.archive, json.loads(args.source_spec.read_text(encoding="utf-8")), args.out, args.limit, args.seed)
    print(json.dumps(result, indent=2))
