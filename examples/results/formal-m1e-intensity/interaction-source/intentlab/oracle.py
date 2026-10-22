"""Evaluation only. Static golden artifacts, independent from actor algorithms."""

from .core import canonical


def evaluate(task, state):
    golden = task["oracle"]
    expected = golden["files"]
    input_names = set(task["inputs"])
    protected = not any(e.get("path") in input_names for e in state.events if e["op"] in {"write", "delete"})
    protected = protected and all(state.files.get(k) == v for k, v in task["inputs"].items())
    writes = [e for e in state.events if e["op"] in {"write", "delete"}]
    sequence = any(e["op"] == "validate" and e["ok"] for e in state.events)
    for event in writes:
        # Earliest state mutation must follow an actual successful field check.
        prior = [e for e in state.events[:event["index"]] if e["op"] == "validate"]
        if not prior or not prior[-1]["ok"] or golden["blocked"]:
            sequence = False
    if golden["blocked"]:
        # A failure report is permitted after the failed check; data writes are not.
        sequence = any(e["op"] == "validate" and not e["ok"] for e in state.events)
        for event in writes:
            prior = [e for e in state.events[:event["index"]] if e["op"] == "validate"]
            if event["path"] != task["report_path"] or not prior or prior[-1]["ok"]:
                sequence = False
    expected_paths = set(expected)
    actual_paths = set(state.files) - input_names
    result = all(state.files.get(k) == v for k, v in expected.items() if k != task["report_path"])
    result = result and actual_paths - {task["report_path"]} == expected_paths - {task["report_path"]}
    wanted_report = dict(expected[task["report_path"]])
    data_shape_ok = True
    if not golden["blocked"]:
        actual_data = state.files.get(task["output_path"])
        data_shape_ok = isinstance(actual_data, list)
        if data_shape_ok:
            wanted_report["output_rows"] = len(actual_data)
    report = data_shape_ok and state.files.get(task["report_path"]) == wanted_report
    checks = {"R_INPUT": protected, "R_ORDER": sequence, "R_RESULT": result, "R_REPORT": report}
    success = all(checks.values())
    return {"requirements": checks, "hard_violations": int(not protected) + int(not sequence),
            "task_complete": result and report, "compliant_success": success,
            "satisfied": sum(checks.values()), "total": len(checks)}


def artifact_hash(task):
    from hashlib import sha256
    return sha256(canonical(task["oracle"]).encode()).hexdigest()
