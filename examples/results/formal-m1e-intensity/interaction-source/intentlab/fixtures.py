"""Small synthetic development corpus. Goldens use explicit fixture arithmetic."""

from copy import deepcopy
import json

from .actors import solve
from .core import initial_state, public_task
from .analysis import analyze
from .oracle import evaluate


FAMILIES = ("dedupe", "filter", "aggregate", "project", "validate", "split")


def build_tasks(count=40):
    tasks = []
    for case in range(count):
        family = FAMILIES[case % len(FAMILIES)]
        a = {"id": "a", "date": "2024-01-01", "group": "x", "amount": 10 + case}
        b = {"id": "b", "date": "2023-01-01", "group": "y", "amount": 30 + case}
        c = {"id": "a", "date": "2023-01-01", "group": "x", "amount": 20 + case}
        rows = [a, b, c]
        required = ["id", "date", "group", "amount"]
        blocked = family == "validate"
        if blocked:
            del c["amount"]
        spec = {"operation": family, "required_fields": required,
                "threshold": 20 + case, "columns": ["id", "amount"]}
        # Expected artifacts are fixture literals, not produced by the actor/checker.
        if family == "dedupe":
            output = [deepcopy(c), deepcopy(b)]
        elif family == "filter":
            output = [deepcopy(b), deepcopy(c)]
        elif family == "aggregate":
            output = [{"group": "x", "total": 30 + 2 * case}, {"group": "y", "total": 30 + case}]
        elif family == "project":
            output = [{"id": "a", "amount": 10 + case}, {"id": "b", "amount": 30 + case}, {"id": "a", "amount": 20 + case}]
        else:
            output = deepcopy(rows)
        files = {}
        if blocked:
            report = {"status": "blocked", "input_rows": 3}
        else:
            if family == "split":
                output = [deepcopy(b), deepcopy(c)]
                files["output/rejected.json"] = [deepcopy(a)]
            files["output/data.json"] = output
            report = {"status": "ok", "input_rows": 3, "output_rows": len(output)}
        files["output/report.json"] = report
        descriptions = {
            "dedupe": "合并输入，按 id 去重，保留日期最早记录，按 id 排序。",
            "filter": f"保留 amount >= {20 + case} 的记录，保持原顺序。",
            "aggregate": "按 group 分组，求 amount 的和，输出 group、total，按 group 排序。",
            "project": "仅输出 id、amount 字段，保持原顺序。",
            "validate": "检查必需字段；任一记录缺字段则仅生成 blocked 报告，不生成数据文件。",
            "split": f"amount >= {20 + case} 写到 data.json，其余写到 rejected.json，各自保持原顺序。"}
        tasks.append({"id": f"{family}-{case:03d}", "case": case, "family": family,
                      "split": "validation" if family == "aggregate" else "test" if family == "split" else "train",
                      "request": descriptions[family] + " 必须先检查 id、date、group、amount 字段；缺字段停止数据处理并报告。不得写入或删除输入文件。输出到 output/，报告 input_rows 以及成功时的 output_rows。",
                      "inputs": {"input/part-a.json": deepcopy(rows[:2]), "input/part-b.json": deepcopy(rows[2:])},
                      "spec": spec, "output_path": "output/data.json", "report_path": "output/report.json",
                      "oracle": {"files": files, "blocked": blocked}})
    return tasks


def diagnostic_states(task):
    good = initial_state(task)
    good.apply(solve(public_task(task)))
    violated = good.clone()
    violated.apply([{"op": "delete", "path": task["report_path"]}])
    repaired = violated.clone()
    repaired.apply([{"op": "write", "path": task["report_path"], "value": task["oracle"]["files"][task["report_path"]]}])
    regression = violated.clone()
    regression.apply([{"op": "write", "path": task["report_path"], "value": task["oracle"]["files"][task["report_path"]]},
                      {"op": "write", "path": next(iter(task["inputs"])), "value": []}])
    return {"valid": good, "violation": violated, "repair_ok": repaired, "repair_regression": regression}


def export_diagnostics(tasks, directory):
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "trajectories.jsonl").open("w", encoding="utf-8", newline="\n") as traces, \
         (directory / "diagnostic_views.jsonl").open("w", encoding="utf-8", newline="\n") as views:
        for task in tasks:
            for kind, state in diagnostic_states(task).items():
                truth = evaluate(task, state)
                traces.write(json.dumps({"task_id": task["id"], "kind": kind, "split": task["split"],
                                        "files": state.files, "events": state.events, "truth": truth}, ensure_ascii=False) + "\n")
                for visible in (True, False):
                    observations = analyze(public_task(task), state, visible)
                    views.write(json.dumps({"task_id": task["id"], "family": task["family"], "split": task["split"],
                                            "kind": kind, "events_visible": visible, "findings": observations,
                                            "labels": {k: int(not v) for k, v in truth["requirements"].items()}}, ensure_ascii=False) + "\n")
