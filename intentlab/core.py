"""In-memory files and replayable events; never execute model-provided code."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import PurePosixPath
import hashlib
import json


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def valid_path(path):
    if not isinstance(path, str) or not path or "\\" in path or ":" in path:
        raise ValueError("Paths must be relative POSIX paths")
    p = PurePosixPath(path)
    if p.is_absolute() or ".." in p.parts or str(p) != path or path == ".":
        raise ValueError("Invalid virtual path")
    return path


@dataclass
class State:
    files: dict
    events: list = field(default_factory=list)
    validation_fields: tuple = ()
    validation_inputs: tuple = ()

    def clone(self):
        return deepcopy(self)

    def apply(self, actions):
        """Validate the entire proposal before applying it, then record each effect."""
        if not isinstance(actions, list) or len(actions) > 16:
            raise ValueError("Expected at most 16 actions")
        for action in actions:
            if not isinstance(action, dict) or action.get("op") not in {"validate", "write", "delete"}:
                raise ValueError("Unsupported action")
            if action["op"] == "validate":
                if type(action.get("ok")) is not bool:
                    raise ValueError("validate.ok must be boolean")
            else:
                valid_path(action.get("path"))
                if action["op"] == "write":
                    if "value" not in action:
                        raise ValueError("write.value required")
                    canonical(action["value"])
        for action in actions:
            event = deepcopy(action)
            event["index"] = len(self.events)
            if action["op"] == "validate":
                # Validation is a tool result, never an actor assertion.
                event["claimed_ok"] = action["ok"]
                event["ok"] = all(
                    isinstance(self.files.get(path), list)
                    and all(isinstance(row, dict) and all(k in row for k in self.validation_fields)
                            for row in self.files[path])
                    for path in self.validation_inputs)
            if action["op"] in {"write", "delete"}:
                path = action["path"]
                event["before"] = digest(self.files[path]) if path in self.files else None
                if action["op"] == "write":
                    self.files[path] = deepcopy(action["value"])
                    event["after"] = digest(self.files[path])
                else:
                    self.files.pop(path, None)
                    event["after"] = None
            self.events.append(event)


def public_task(task):
    """The actor and online analyzer never receive the fixture oracle."""
    return deepcopy({k: v for k, v in task.items() if k != "oracle"})


def initial_state(task):
    return State(deepcopy(task["inputs"]), validation_fields=tuple(task["spec"]["required_fields"]),
                 validation_inputs=tuple(task["inputs"]))


def replay_events(task, events):
    """Re-execute committed tools, checking event evidence rather than trusting it."""
    state = initial_state(task)
    for event in events:
        if event["op"] == "validate":
            action = {"op": "validate", "ok": event.get("claimed_ok", event["ok"])}
        else:
            action = {k: event[k] for k in ("op", "path", "value") if k in event}
        state.apply([action])
        if state.events[-1] != event:
            raise ValueError("Recorded event differs from re-executed tool evidence")
    return state


def load_tasks(path):
    tasks = json.loads(path.read_text(encoding="utf-8"))
    seen = set()
    for task in tasks:
        if task["id"] in seen:
            raise ValueError("Duplicate task ID")
        seen.add(task["id"])
        for name in task["inputs"]:
            valid_path(name)
        for name in [task["output_path"], task["report_path"]]:
            valid_path(name)
            if name in task["inputs"]:
                raise ValueError("Fixture output overlaps input")
        if set(task["oracle"]["files"]) & set(task["inputs"]):
            raise ValueError("Oracle outputs overlap input")
    return tasks
