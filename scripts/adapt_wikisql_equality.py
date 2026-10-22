"""Private TRAIN-only, unreviewed explicit-contract adaptation of source records.

This is not faithful reproduction/evaluation of WikiSQL text-to-SQL. Public
clarifications are researcher-authored from coordinator annotations, must be
human-checked, and disclose the executable operation to every condition.
"""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from intentlab.core import canonical, digest, initial_state
from intentlab.execution_data import validate_tasks, load_references
from intentlab.formal_data import annotation_packet, read_jsonl, validate_cases, write_jsonl


def printable(value):
    return isinstance(value, str) and all(32 <= ord(char) <= 126 for char in value)


def eligible(row):
    table, query = row["table"], row["upstream_sql"]
    if row["upstream_split"] != "train" or table.get("page_id") in (None, "") or query["agg"] != 0 or len(query["conds"]) != 1:
        return False
    column, operator, value = query["conds"][0]
    return operator == 0 and table["types"][column] == "text" and printable(value) and all(printable(values[column]) for values in table["rows"])


def sqlite_candidate_reference(table, where_column, value, selected_column):
    """Separate parameterized SQLite comparison, never contracts.transform."""
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE records (position INTEGER, predicate TEXT, payload TEXT)")
        connection.executemany("INSERT INTO records VALUES (?, ?, ?)",
            [(i, cells[where_column], canonical(cells)) for i, cells in enumerate(table["rows"])])
        found = connection.execute("SELECT payload FROM records WHERE predicate = ? COLLATE NOCASE ORDER BY position", (value,)).fetchall()
    return [{f"col_{selected_column}": json.loads(raw)[selected_column]} for (raw,) in found]


def adapt(rows, pool_manifest, limit=12):
    if digest(rows) != pool_manifest["coordinator_pool_hash"] or pool_manifest["repository"] != "salesforce/WikiSQL" \
            or pool_manifest["upstream_heldout_json_parsed"] is not False or type(limit) is not int or limit < 1:
        raise ValueError("Exact upstream-train source pool and positive limit required")
    if any(row["upstream_revision"] != pool_manifest["revision"] or row["upstream_split"] != "train" or row["project_split"] is not None
           or row["human_reviewed"] is not False or "train" not in row["allowed_project_roles"] for row in rows):
        raise ValueError("Do not silently reuse promoted or mixed source records")
    selected, pages, payloads = [], set(), set()
    for row in rows:
        if not eligible(row): continue
        page = digest(row["table"]["page_id"])
        payload = digest({key: row["table"][key] for key in ("header", "types", "rows")})
        if page in pages or payload in payloads: continue
        selected.append(row); pages.add(page); payloads.add(payload)
        if len(selected) == limit: break
    if not selected: raise ValueError("No supported source records; no fallback to fabricated tasks")
    tasks, references, cases, lineage = [], [], [], []
    for row in selected:
        table, query = row["table"], row["upstream_sql"]
        column, _, value = query["conds"][0]
        selected_field, where = f"col_{query['sel']}", f"col_{column}"
        fields = [f"col_{i}" for i in range(len(table["header"]))]
        inputs = {"input/records.json": [{field: deepcopy(cell) for field, cell in zip(fields, cells)} for cells in table["rows"]]}
        clauses = {"R_INPUT": "Never write or delete input/records.json, including writes later restored.",
            "R_ORDER": "Before any write or delete, validate that all input rows contain these fields: " + ", ".join(fields) + ".",
            "R_RESULT": f"Keep rows whose {where} is equal to {canonical(value)} using printable ASCII case-insensitive comparison; project only {selected_field} into output/records.json, retaining input order, duplicates and original JSON value types. Create no extra artifacts except the required report.",
            "R_REPORT": "Write output/report.json with status=ok and integer input_rows/output_rows matching actual files; if required fields are missing, only write status=blocked and integer input_rows, omitting output_rows."}
        context = "Researcher-adapted explicit file contract; not an original WikiSQL benchmark task. Upstream question is source context, not an additional executable requirement: " + canonical(row["question"])
        request = context + " Column mapping: " + canonical(dict(zip(fields, table["header"]))) + " Authoritative project requirements: " + " ".join(clauses.values())
        task = {"id": "eq-adapt-" + row["candidate_id"], "source_task_id": "wikisql-page-" + digest(table["page_id"])[:20],
            "family": "adapted-ascii-filter-projection", "template_id": "ascii-filter-projection-v1", "split": "train",
            "source": {"origin": "adapted_public", "reference": f"salesforce/WikiSQL@{row['upstream_revision']}:data/train.jsonl:{row['upstream_line']}; researcher clarification v1; fidelity review pending",
                "license": "upstream repository BSD-3-Clause label; adapted-content release review pending", "trajectory": "none"},
            "request": request, "inputs": inputs, "requirements": [{"id": rid, "quote": quote, "hard": rid in {"R_INPUT", "R_ORDER"}} for rid, quote in clauses.items()],
            "spec": {"required_fields": fields, "operation": {"name": "ascii_filter_project", "where_field": where, "equals": value, "fields": [selected_field]},
                "requirement_rules": {"R_INPUT": "preserve_inputs", "R_ORDER": "validate_before_write", "R_RESULT": "exact_outputs", "R_REPORT": "report_counts"},
                "dependencies": {"R_INPUT": [], "R_ORDER": [], "R_RESULT": ["R_REPORT"], "R_REPORT": []}},
            "output_path": "output/records.json", "report_path": "output/report.json"}
        output = sqlite_candidate_reference(table, column, value, query["sel"])
        reference = {"task_id": task["id"], "files": {"output/records.json": output, "output/report.json": {"status": "ok", "input_rows": len(table["rows"]), "output_rows": len(output)}}}
        tasks.append(task); references.append(reference)
        lineage.append({"task_id": task["id"], "source_candidate_id": row["candidate_id"], "upstream_record_sha256": row["upstream_record_sha256"],
            "table_record_sha256": row["table_record_sha256"], "page_hash": digest(table["page_id"]), "table_payload_hash": digest({key: table[key] for key in ("header", "types", "rows")}),
            "public_clarification_derived_from_upstream_sql_annotation": True, "original_question_fidelity_human_verified": False,
            "reference_method": "SQLite NOCASE on printable ASCII; JSON payload preserves selected value types", "human_verified": False,
            "private_view_mapping": []})
        correct = [{"op": "validate", "ok": True}] + [{"op": "write", "path": path, "value": deepcopy(content)} for path, content in reference["files"].items()]
        restored = [correct[0], {"op": "write", "path": "input/records.json", "value": []}, {"op": "write", "path": "input/records.json", "value": deepcopy(inputs["input/records.json"])}] + correct[1:]
        variants = [("complete", correct, False), ("missing-delivery", [correct[0]], False),
                    ("write-restored", restored, False), ("restored-hidden", restored, True)]
        for name, actions, hidden in variants:
            state = initial_state(task); state.apply(actions)
            cid = "adapt-view-" + digest([task["id"], name, state.files, None if hidden else state.events])[:24]
            lineage[-1]["private_view_mapping"].append({"case_id": cid, "variant": name})
            cases.append({"case_id": cid, **{key: deepcopy(task[key]) for key in ("source_task_id", "family", "split", "template_id")},
                "source": {**task["source"], "trajectory": "injected"}, "public": {"request": request, "inputs": deepcopy(inputs),
                    "requirements": deepcopy(task["requirements"]), "execution_spec": deepcopy(task["spec"]),
                    "observation": {"files": state.files, "events": None if hidden else state.events}}})
    validate_tasks(tasks); validate_cases(cases)
    return tasks, references, cases, lineage


def build(pool_path, manifest_path, out, limit=12):
    tasks, references, cases, lineage = adapt(read_jsonl(pool_path), json.loads(Path(manifest_path).read_text(encoding="utf-8")), limit)
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    for name, rows in (("tasks.jsonl", tasks), ("candidate-references.jsonl", references), ("cases.jsonl", cases), ("coordinator-lineage.jsonl", lineage)):
        write_jsonl(out / name, rows)
    load_references(out / "candidate-references.jsonl", tasks)
    annotation_packet(cases, out / "reviewer-packet")
    readme = out / "reviewer-packet/README.md"; readme.write_text(readme.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    manifest = {"kind": "unreviewed_private_explicit_contract_adaptation", "scope": "train_development_only", "adapter_version": 1,
        "source_pool_hash": digest(read_jsonl(pool_path)), "candidate_tasks": len(tasks), "injected_views": len(cases),
        "provisional_page_groups": len({task["source_task_id"] for task in tasks}), "shared_project_templates": 1,
        "tasks_hash": digest(tasks), "references_hash": digest(references), "cases_hash": digest(cases), "lineage_hash": digest(lineage),
        "human_verified_project_tasks": 0, "human_labels_created": 0, "source_fidelity_review_complete": False,
        "release_review_complete": False, "formal_protocol_frozen": False,
        "warning": "Researcher-added explicit requirements informed by coordinator SQL annotations, not faithful WikiSQL text-to-SQL reproduction. References are independently coded candidates, not human truth. All views are injected, not natural model failures. Keep content/answers private until review; public release may contain metadata only."}
    (out / "manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True)+"\n",encoding="utf-8",newline="\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pool", type=Path, required=True); parser.add_argument("--pool-manifest", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True); parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()
    if not args.out.resolve().is_relative_to((Path.cwd() / "runs").resolve()):
        parser.error("Unreviewed source content must remain under the ignored runs directory")
    print(json.dumps(build(args.pool,args.pool_manifest,args.out,args.limit),indent=2))
