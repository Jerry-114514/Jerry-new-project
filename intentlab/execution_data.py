"""Public execution tasks and separate static references for offline scoring."""

from copy import deepcopy
import json
from pathlib import Path

from .contracts import validate_spec
from .core import valid_path
from .formal_data import read_jsonl, validate_cases


def validate_tasks(tasks):
    seen, cases = set(), []
    for task in tasks:
        expected = {"id", "source_task_id", "family", "split", "template_id", "source", "request", "inputs",
                    "requirements", "spec", "output_path", "report_path"}
        if not isinstance(task, dict) or set(task) != expected:
            raise ValueError("Execution task must contain only allowlisted public fields")
        if not isinstance(task["id"], str) or not task["id"] or task["id"] in seen:
            raise ValueError("Missing or duplicate execution task ID")
        seen.add(task["id"])
        if not isinstance(task["inputs"], dict) or not task["inputs"] or any(not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
                                     for rows in task["inputs"].values()):
            raise ValueError("Execution inputs must be nonempty file mappings of record arrays")
        for path in task["inputs"]:
            valid_path(path)
        for key in ("output_path", "report_path"):
            valid_path(task[key])
            if task[key] in task["inputs"]:
                raise ValueError("Output overlaps protected input")
        if task["output_path"] == task["report_path"]:
            raise ValueError("Data and report paths overlap")
        public_case = {"case_id": task["id"], "source_task_id": task["source_task_id"], "family": task["family"],
            "split": task["split"], "template_id": task["template_id"], "source": task["source"],
            "public": {"request": task["request"], "inputs": task["inputs"], "requirements": task["requirements"],
                       "execution_spec": deepcopy(task["spec"]),
                       "observation": {"files": deepcopy(task["inputs"]), "events": []}}}
        validate_cases([public_case])
        validate_spec(task["spec"], task["requirements"])
        json.dumps(task, ensure_ascii=False, allow_nan=False)
        cases.append(public_case)
    validate_cases(cases)
    return tasks


def load_execution_tasks(path):
    tasks = read_jsonl(path)
    return validate_tasks(tasks)


def load_references(path, tasks):
    return validate_references(read_jsonl(path), tasks)


def validate_references(records, tasks):
    """Validate in-memory references with the same rules as file loading."""
    by_id = {task["id"]: task for task in tasks}
    references = {}
    for record in records:
        if set(record) != {"task_id", "files"} or record["task_id"] not in by_id or record["task_id"] in references:
            raise ValueError("Unknown, duplicate or malformed offline reference")
        task = by_id[record["task_id"]]
        if not isinstance(record["files"], dict):
            raise ValueError("Reference files must be an object")
        for path in record["files"]:
            valid_path(path)
            if path in task["inputs"]:
                raise ValueError("Private reference cannot prescribe input changes")
        if task["report_path"] not in record["files"]:
            raise ValueError("Reference needs an explicit report artifact")
        blocked = any(any(key not in row for key in task["spec"]["required_fields"])
                      for rows in task["inputs"].values() for row in rows)
        expected_paths = {task["report_path"]} if blocked else {task["report_path"], task["output_path"]}
        if set(record["files"]) != expected_paths or not isinstance(record["files"][task["report_path"]], dict):
            raise ValueError("Reference paths/report shape conflict with the public contract")
        if not blocked and not isinstance(record["files"][task["output_path"]], list):
            raise ValueError("Expected output must be a record array")
        json.dumps(record, allow_nan=False)
        references[record["task_id"]] = record
    if set(references) != set(by_id):
        raise ValueError("Offline references must cover every execution task")
    return references
