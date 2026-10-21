"""Scripted fixtures and a bounded HTTP JSON adapter. No hidden labels are read."""

from __future__ import annotations

from copy import deepcopy
import json
import urllib.request


def solve(task):
    spec = task["spec"]
    rows = [deepcopy(row) for values in task["inputs"].values() for row in values]
    needed = set(spec["required_fields"])
    ok = all(needed <= set(row) for row in rows)
    if not ok:
        return [{"op": "validate", "ok": False},
                {"op": "write", "path": task["report_path"], "value": {"status": "blocked", "input_rows": len(rows)}}]
    operation = spec["operation"]
    if operation == "dedupe":
        best = {}
        for row in rows:
            key = row["id"]
            if key not in best or row["date"] < best[key]["date"]:
                best[key] = row
        output = sorted(best.values(), key=lambda r: r["id"])
    elif operation == "filter":
        output = [r for r in rows if r["amount"] >= spec["threshold"]]
    elif operation == "aggregate":
        groups = {}
        for row in rows:
            groups[row["group"]] = groups.get(row["group"], 0) + row["amount"]
        output = [{"group": k, "total": groups[k]} for k in sorted(groups)]
    elif operation == "project":
        output = [{k: r[k] for k in spec["columns"]} for r in rows]
    elif operation in {"validate", "split"}:
        output = rows
    else:
        raise ValueError(f"Unknown operation: {operation}")
    files = {task["output_path"]: output}
    if operation == "split":
        files[task["output_path"]] = [r for r in rows if r["amount"] >= spec["threshold"]]
        files["output/rejected.json"] = [r for r in rows if r["amount"] < spec["threshold"]]
    report = {"status": "ok", "input_rows": len(rows), "output_rows": len(files[task["output_path"]])}
    files[task["report_path"]] = report
    return [{"op": "validate", "ok": True}] + [{"op": "write", "path": k, "value": v} for k, v in files.items()]


class ScriptedActor:
    """A deliberately imperfect test double, not a measured LLM."""

    def propose(self, task, state, phase, target=None, attempt=0):
        actions = solve(task)
        if phase == "initial":
            # Some conditions are correct already; others omit a required report.
            if task["case"] % 3 != 0:
                actions = [a for a in actions if a.get("path") != task["report_path"]]
            if task["case"] % 7 == 0:
                actions += [{"op": "write", "path": next(iter(task["inputs"])), "value": []}]
        elif phase == "repair":
            # First repair intentionally demonstrates a historical-constraint risk.
            if attempt == 0 and task["case"] % 4 == 1:
                actions += [{"op": "write", "path": next(iter(task["inputs"])), "value": []}]
            if target == "R_REPORT":
                actions = [a for a in actions if a["op"] == "validate" or a.get("path") == task["report_path"] or a.get("path") in task["inputs"]]
        return {"actions": actions, "claim": "completed", "usage": None}


class HTTPActor:
    """Custom /propose protocol, intentionally independent of provider-specific SDKs."""

    def __init__(self, url, timeout=60):
        if not url.startswith(("http://", "https://")):
            raise ValueError("Actor URL must be HTTP(S)")
        self.url = url
        self.timeout = timeout

    def propose(self, task, state, phase, target=None, attempt=0):
        payload = {"task": task, "state": {"files": state.files, "events": state.events},
                   "phase": phase, "target": target, "attempt": attempt}
        request = urllib.request.Request(self.url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self.timeout) as response:
            data = response.read(1_000_001)
        if len(data) > 1_000_000:
            raise ValueError("Actor response exceeds 1 MB")
        result = json.loads(data)
        if not isinstance(result, dict) or not isinstance(result.get("actions"), list):
            raise ValueError("Actor response must contain actions")
        return result
