"""Online rule analyzer: public specification + observations, no fixture oracle."""

from collections import defaultdict


REQUIREMENTS = ("R_INPUT", "R_ORDER", "R_RESULT", "R_REPORT")


def analyze(task, state, events_visible=True):
    inputs = task["inputs"]
    rows = [row for values in inputs.values() for row in values]
    spec = task["spec"]
    fields_ok = all(all(k in row for k in spec["required_fields"]) for row in rows)
    blocked = not fields_ok
    events = state.events if events_visible else []
    mutations = [e for e in events if e["op"] in {"write", "delete"}]
    touched = sum(e.get("path") in inputs for e in mutations)
    changed = any(state.files.get(k) != v for k, v in inputs.items())
    protected = "violated" if touched or changed else ("satisfied" if events_visible else "unknown")
    ordered = True
    for event in mutations:
        prior = [e for e in events if e["index"] < event["index"] and e["op"] == "validate"]
        if not prior or prior[-1]["ok"] != fields_ok:
            ordered = False
        if blocked and event["path"] != task["report_path"]:
            ordered = False
    if blocked and not any(e["op"] == "validate" and not e["ok"] for e in events):
        ordered = False
    order_status = ("satisfied" if ordered else "violated") if events_visible else "unknown"
    expected = {}
    if not blocked:
        operation = spec["operation"]
        if operation == "dedupe":
            keys = sorted({r["id"] for r in rows})
            data = [min((r for r in rows if r["id"] == k), key=lambda r: r["date"]) for k in keys]
        elif operation == "filter":
            data = list(filter(lambda r: r["amount"] >= spec["threshold"], rows))
        elif operation == "aggregate":
            amounts = defaultdict(list)
            for row in rows:
                amounts[row["group"]].append(row["amount"])
            data = [{"group": k, "total": sum(amounts[k])} for k in sorted(amounts)]
        elif operation == "project":
            data = [dict(zip(spec["columns"], (r[k] for k in spec["columns"]))) for r in rows]
        else:
            data = rows
        if operation == "split":
            expected["output/rejected.json"] = [r for r in rows if r["amount"] < spec["threshold"]]
            data = [r for r in rows if r["amount"] >= spec["threshold"]]
        expected[task["output_path"]] = data
    report = {"status": "blocked", "input_rows": len(rows)} if blocked else {
        "status": "ok", "input_rows": len(rows), "output_rows": len(expected[task["output_path"]])}
    paths = set(state.files) - set(inputs) - {task["report_path"]}
    data_bad = paths != set(expected) or any(state.files.get(k) != v for k, v in expected.items())
    report_bad = state.files.get(task["report_path"]) != report
    statuses = [protected, order_status, "violated" if data_bad else "satisfied", "violated" if report_bad else "satisfied"]
    reasons = ["Input write/delete history or changed snapshot", "Field validation must precede mutations",
               "Compare result with the public operation and scope", "Report counts must match public operation"]
    # Features are intentionally simple, observable rule signals; this is a plumbing baseline.
    signals = [float(bool(touched or changed)), float(not ordered), float(data_bad), float(report_bad), float(not events_visible)]
    return [{"id": rid, "status": statuses[i], "hard": i < 2, "reason": reasons[i],
             "evidence": [e["index"] for e in events],
             "features": signals + [float(j == i) for j in range(4)]}
            for i, rid in enumerate(REQUIREMENTS)]


def score(findings):
    known = [f for f in findings if f["status"] != "unknown"]
    return {"hard_violations": sum(f["hard"] and f["status"] == "violated" for f in findings),
            "satisfaction_rate": sum(f["status"] == "satisfied" for f in known) / len(known) if known else None,
            "evidence_coverage": len(known) / len(findings),
            "unknown": sum(f["status"] == "unknown" for f in findings)}


def gate(before, after):
    after_by_id = {f["id"]: f for f in after}
    for old in before:
        new = after_by_id[old["id"]]
        if old["status"] == "satisfied" and new["status"] != "satisfied":
            return False, "protected_requirement_regressed:" + old["id"]
        if old["hard"] and old["status"] != "violated" and new["status"] == "violated":
            return False, "new_hard_violation:" + old["id"]
        if old["hard"] and new["status"] == "unknown":
            return False, "hard_constraint_unverified:" + old["id"]
    fixed = [f for f in before if f["status"] == "violated" and after_by_id[f["id"]]["status"] == "satisfied"]
    return (True, "verified_improvement") if fixed else (False, "no_verified_improvement")
