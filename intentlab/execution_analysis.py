"""Public-rule baseline; private reference files are not imported or accepted."""

from .contracts import public_solution
from .core import canonical
from copy import deepcopy


def analyze_execution(task, state, events_visible=True):
    rules = task["spec"]["requirement_rules"]
    originals = task["inputs"]
    visible = state.events if events_visible else []
    touches = [event for event in visible if event["op"] in {"write", "delete"} and event["path"] in originals]
    changed = [path for path, value in originals.items() if path not in state.files or canonical(state.files[path]) != canonical(value)]
    protected = "violated" if touches or changed else "satisfied" if events_visible else "unknown"
    mutations = [event for event in visible if event["op"] in {"write", "delete"}]
    rows = [row for values in originals.values() for row in values]
    fields_ok = all(all(key in row for key in task["spec"]["required_fields"]) for row in rows)
    ordered = any(event["op"] == "validate" and event["ok"] == fields_ok for event in visible)
    for event in mutations:
        previous = [item for item in visible if item["index"] < event["index"] and item["op"] == "validate"]
        last = previous[-1]["ok"] if previous else None
        failure_report = (not fields_ok and last is False and event["op"] == "write" and event["path"] == task["report_path"])
        if not failure_report and (not fields_ok or last is not True):
            ordered = False
    order_status = ("satisfied" if ordered else "violated") if events_visible else "unknown"
    expected_actions = public_solution(task)
    expected = {action["path"]: action["value"] for action in expected_actions if action["op"] == "write"}
    actual_data = set(state.files) - set(originals) - {task["report_path"]}
    expected_data = set(expected) - {task["report_path"]}
    result_ok = actual_data == expected_data and all(
        path in state.files and canonical(state.files[path]) == canonical(expected[path]) for path in expected_data)
    report = dict(expected[task["report_path"]])
    shape_ok = True
    if fields_ok:
        value = state.files.get(task["output_path"])
        shape_ok = isinstance(value, list)
        if shape_ok:
            report["output_rows"] = len(value)
    report_ok = shape_ok and task["report_path"] in state.files and canonical(state.files[task["report_path"]]) == canonical(report)
    statuses = {"preserve_inputs": protected, "validate_before_write": order_status,
                "exact_outputs": "satisfied" if result_ok else "violated",
                "report_counts": "satisfied" if report_ok else "violated"}
    evidence = ["request", "snapshot_paths"] + ["input:" + path for path in originals]
    evidence += ["file:" + path for path in state.files]
    evidence += ["event:" + str(event["index"]) for event in visible]
    return [{"id": req["id"], "hard": req["hard"], "status": statuses[rules[req["id"]]],
             "evidence": [] if statuses[rules[req["id"]]] == "unknown" else evidence,
             "reason": "public_executable_rule"} for req in task["requirements"]]


class HybridExecutionAnalyzer:
    """Public executable checks govern covered requirements; LM is a sidecar.

    These contracts cover every requirement. Consequently the gate equals the
    rule baseline, not a claim that the language model's diagnosis improved.
    Hidden-history unknowns remain unknown, regardless of LM confidence.
    """

    def __init__(self, model_analyzer):
        self.model_analyzer = model_analyzer
        self.decisions = []

    @property
    def errors(self):
        return getattr(self.model_analyzer, "errors", [])

    def __call__(self, task, state, events_visible=True):
        model = self.model_analyzer(task, state, events_visible)
        rules = analyze_execution(task, state, events_visible)
        by_id = {row["id"]: row for row in model}
        if len(model) != len(rules) or set(by_id) != {row["id"] for row in rules}:
            raise ValueError("Hybrid model findings do not cover the public requirements")
        merged = [dict(row, reason="hybrid_public_rule_authority") for row in rules]
        self.decisions.append({"model_findings": deepcopy(model), "rule_findings": deepcopy(rules),
            "effective_findings": deepcopy(merged), "events_visible": events_visible,
            "overrides": [{"id": row["id"], "model_status": by_id[row["id"]]["status"], "effective_status": row["status"]}
                          for row in rules if by_id[row["id"]]["status"] != row["status"]]})
        return merged


class ContractRuleActor:
    """Correct engineering rule actor, clearly separate from a measured LLM."""

    def propose(self, task, state, phase, target=None, attempt=0):
        actions = public_solution(task)
        if phase == "repair" and target is not None:
            ids = {target} if isinstance(target, str) else set(target)
            rules = task["spec"]["requirement_rules"]
            paths = set()
            if any(rules[rid] == "exact_outputs" for rid in ids):
                paths.add(task["output_path"])
            if any(rules[rid] == "report_counts" for rid in ids):
                paths.add(task["report_path"])
            actions = [action for action in actions if action["op"] == "validate" or action.get("path") in paths]
        return {"actions": actions, "usage": None}


def execution_scope(task, failures, policy, rejected_before):
    rules = task["spec"]["requirement_rules"]
    if policy == "fixed-full":
        return [rid for rid, rule in rules.items() if rule in {"exact_outputs", "report_counts"}]
    target = failures[0]["id"]
    if policy == "dynamic" and rejected_before:
        selected, pending = {target}, [target]
        while pending:
            for rid in task["spec"]["dependencies"][pending.pop()]:
                if rid not in selected:
                    selected.add(rid)
                    pending.append(rid)
        return sorted(selected)
    return target
